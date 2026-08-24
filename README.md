# knowledgebase-service

A queryable knowledge base over a personal GitHub account — not a portfolio search, but a structured map of what has been built and how the pieces connect. It is designed to be consumed by *other agents*, not just humans: a REST API and an MCP server let downstream bots and assistants ask cross-repository questions about a body of work without re-reading every repo themselves.

It answers two different classes of question, backed by two different retrieval strategies:

- **Descriptive** — "Which of my repos use Postgres?", "Summarize my experience with multi-agent systems." Answered with structured SQL and semantic vector search.
- **Structural** — "If I change the response shape of `/users/{id}/flight-history`, which repos break?", "What depends on the `documents` table?" Answered with an explicit, statically-derived dependency graph, walked with a deterministic recursive query — never guessed from embedding similarity.

Domain-specific agents live in their own repositories and call this service over HTTP or MCP for the cross-repo context they don't otherwise have. Most of that calling happens through nine scoped, deterministic endpoints — search docs/code/commits, list dependencies, look up a project — each a direct SQL or vector call with no routing decision involved. Natural-language `/v1/query` is a separate, REST-only path for callers that hand over raw text with no ability to pick a tool themselves (a badge, an Issue bot); it's one entry point among ten, not the shape of the whole system.

## Contents

- [Architecture](#architecture)
- [Data model](#data-model)
- [Query engine](#query-engine)
- [Access tiers](#access-tiers)
- [Trust boundaries](#trust-boundaries)
- [Cost controls](#cost-controls)
- [API](#api)
- [MCP](#mcp)
- [Setup](#setup)
- [Ingesting data](#ingesting-data)
- [Testing](#testing)
- [Deployment](#deployment)
- [Project layout](#project-layout)

## Architecture

```
GITHUB push --(X-Hub-Signature-256)--> webhook/github --(validate, enqueue only)--> SQS --> WORKER LAMBDA
                                       (API Lambda, behind          queue        (no API Gateway,
                                        API Gateway's 30s limit)                  15 min timeout)
                                                                                        |
scheduled sync (daily cron) ------------------------------------------------------------+
                                                                                        |
GITHUB / /docs (manual: resume, notes, ADRs) -------------------------------------------+
                                                                                        v
                                                                    INGESTION PIPELINE (shared)
                                                          fetch -> secret scan -> route by layer
                                                                -> chunk -> embed -> upsert
                                                                                        |
                                                                                        v
                                                                     POSTGRESQL + PGVECTOR
                                                    L1 documents | L2 code chunks | L3 dependency graph | L4 commits
                                                                                        ^
                                                                                        | read-only roles (app_ro / app_ro_public)
                                                                                        v
                                                                    API LAMBDA: FASTAPI + FASTMCP
                                              9 scoped tools (direct SQL/vector/graph, no routing) | /v1/query (LangGraph-routed NL)
                                                                                        |
                                                                          API Gateway (30s timeout)
                                                                    |                            |
                                                              REST consumers                MCP clients
                                                        (other agents, badges, bots)   (Claude Desktop/Code, Cursor)
```

Two Lambdas share one container image but run different entry points: the API Lambda (`src.main`, behind API Gateway) serves REST/MCP reads and, for webhooks, only validates the signature and enqueues to SQS; the worker Lambda (`src.worker_handler`, SQS-triggered, no API Gateway) does the actual ingestion, driven off the same shared pipeline as the scheduled sync and the manual `/docs` source. That split exists because a real push can take minutes to fetch files, embed, and summarize diffs — well past API Gateway's 30-second integration timeout, which is what was silently dropping ingested data before the split.

Ingestion writes through a role with write grants (`app_rw`); every query-path read — REST, MCP, and the LangGraph-routed `/v1/query` path — goes through a role with only `SELECT` privileges, enforced at the database level. The natural-language query path never writes, and that boundary is not just an application-level check: the role itself has no write grants, so a sufficiently creative generated query still can't mutate anything.

The same reasoning governs private repositories. Private repos are ingested in full, but reads are split across two roles: `app_ro` sees the whole corpus, while `app_ro_public` is constrained by row-level security to projects with `is_private = false`. Because the SQL node executes LLM-generated statements, a `WHERE` clause in application code would be the wrong place to enforce this — the policy lives on the tables, so it holds regardless of what SQL is generated. See [Access tiers](#access-tiers).

## Data model

Data is deliberately kept in four differently-shaped layers rather than one undifferentiated vector store, because different questions need different retrieval strategies.

| Layer | Contents | Retrieval | Answers |
|---|---|---|---|
| **L1 — Documents** | READMEs, `/docs` markdown, notes | Vector search | "What is this project about" |
| **L2 — Code chunks** | Functions/classes, chunked by symbol (tree-sitter, with an AST/heuristic fallback) | Vector search + metadata filter | "Where do I implement X" |
| **L3 — Dependency graph** | Declared/statically-parsed endpoints, consumers, package deps | Recursive SQL traversal | "What breaks if I change X" |
| **L4 — Commit history** | Commit metadata + LLM-generated diff summaries (not raw patches) | Vector search + time filter | "How did X evolve" |

The dependency graph (L3) is never inferred from embeddings. Semantic similarity tells you two things look alike, not that one calls the other — impact analysis needs a fact, not a guess. It's populated from two sources, in order of trust:

1. **A `project.yaml` manifest**, checked into the root of a repo. This is the primary, authoritative source.
2. **Static analysis**, as a secondary signal that catches drift when a manifest is missing or stale: package dependencies parsed from `requirements.txt` / `pyproject.toml` / `package.json`, FastAPI route decorators, and hardcoded URLs matching known project domains. This is deliberately modest in scope — it is not a call-graph analyzer.

If a repo has no manifest, it is marked `manifest_missing` rather than silently treated as having no dependencies, and every graph answer reports its confidence honestly: `manifest` (high), `static_analysis` (medium), or `manifest_missing` (low, coverage incomplete).

### `project.yaml` shape

```yaml
name: flight-customer-data-api
description: Universal customer identity and audit logging service.
technologies: [python, fastapi, postgres, aws-lambda, terraform]
exposes:
  - kind: http_endpoint
    identifier: "GET /users/{id}/flight-history"
    contract: { returns: "list[Booking]" }
  - kind: db_table
    identifier: "gdpr_consent_logs"
consumes:
  - kind: http_call
    provider: knowledgebase-service
    identifier: "POST /v1/query"
```

### Secret scanning

Every piece of content — code, docs, commit diffs — is scanned for secrets before it is stored or sent to an embedding provider. A match causes the chunk to be skipped entirely (never redacted-and-stored); the file path and rule ID are recorded in `secret_scan_findings` so the key can be rotated, but the matched value itself is never persisted or logged. `.env*`, `*.pem`, `*.key`, `id_rsa*`, `credentials`, and `.aws/` are excluded by path regardless of scan result. Findings are tracked as resolved/unresolved via `scripts/resolve_secret.py`.

## Query engine

This section covers `/v1/query` only. The other nine endpoints ([API](#api)) call vector search, graph traversal, or a plain lookup directly — no router, no LLM in the loop, no LangGraph involved. `/v1/query` exists for callers that hand over raw text with no ability to pick a tool themselves, and routes through a small [LangGraph](https://github.com/langchain-ai/langgraph) state machine to figure out which of those same underlying operations to call:

```
router --(intent)--> sql | vector | time | graph_traversal
  sql --(zero rows, or hybrid intent)--> vector
  all terminal nodes --> synthesize
```

- **Router** — deterministic (regex-based, not an LLM classifier) intent classification. Impact/blast-radius phrasings ("what breaks if I change...", "what depends on...", "who calls...") are hard-routed to the graph node — this is the single routing rule the system is least willing to get wrong.
- **SQL** — an LLM generates a read-only `SELECT` against the live, introspected schema. On a Postgres error, the error is fed back to the generator and retried, bounded at 3 attempts, then fails cleanly rather than fabricating a result.
- **SQL → Vector fallback** — a SQL query that legitimately executes but returns zero rows often means the structured tables it depends on (manifest-derived tech tags, for instance) are sparse rather than that the answer doesn't exist. In that case the engine falls through to vector search over documents/code and reports `medium` confidence with a coverage note, instead of reporting "no results." A genuine SQL *error* does not trigger this — that stays a self-heal failure, reported as such.
- **Vector** — embeds the query and does a cosine search (pgvector `<->`) filtered to the relevant layer(s).
- **Time** — vector search over commits, pre-filtered by a time range parsed out of the query ("last week", "past month").
- **Graph traversal** — a fixed, parameterized recursive CTE, never LLM-generated SQL:

  ```sql
  with recursive impacted as (
      select d.consumer_project_id, 1 as depth
      from dependencies d
      where d.provider_project_id = :project_id
        and d.identifier = :interface_identifier
      union
      select d2.consumer_project_id, i.depth + 1
      from dependencies d2
      join impacted i on d2.provider_project_id = i.consumer_project_id
      where i.depth < 5
  )
  select distinct p.name, p.repo_url, min(i.depth) as distance
  from impacted i join projects p on p.id = i.consumer_project_id
  group by p.name, p.repo_url
  order by distance
  ```

  Cycles terminate on the depth bound rather than a visited-set; the traversal is deliberately bounded, not exhaustive.
- **Synthesizer** — merges results into a plain-English summary plus `confidence` and an optional `coverage_note`. Graph synthesis is template-based rather than LLM-paraphrased, so the confidence caveats above can't be softened or dropped by a language model.

## Access tiers

Two bearer tokens, mapped to two database roles:

| Token | Database role | Sees |
|---|---|---|
| `API_AUTH_KEY` | `app_ro_public` | Public projects only |
| `API_ADMIN_KEY` | `app_ro` | Every project, including private repos |

The auth middleware resolves the token to a tier and `get_conn` opens the corresponding connection; the filtering itself is row-level security on the tables, not a query-code predicate. A request presenting no recognized token is rejected, and a request whose tier is somehow unset falls back to the public role rather than the privileged one.

`app_ro_public` additionally cannot read `secret_scan_findings` or `ingestion_log` at all — both name file paths and repositories that may be private.

Distribute `API_AUTH_KEY` to consumers that should only see public work. Keep `API_ADMIN_KEY` for your own tooling.

## Trust boundaries

This service ingests text it doesn't control — commit diffs, READMEs, docstrings — from any repository it's pointed at, including ones that accept outside contributions. That content is later interpolated into LLM prompts during commit summarization and answer synthesis, which makes prompt injection a real attack surface: a crafted docstring or changelog entry merged through an ordinary-looking PR can carry text aimed at the model rather than the reader.

Every prompt that interpolates content from a repo — or the caller's own natural-language query — wraps it in explicit `<untrusted_content>` delimiters, paired with a system-prompt instruction that content inside those tags is data to describe, never an instruction to follow. This raises the bar substantially, but it's a mitigation, not a guarantee.

Because of that, the contract for consumers is: **treat this service's output as untrusted input, not a verified instruction.** A `summary` or `data` field from `/v1/query` or `/v1/impact` should never, on its own, be sufficient justification for a downstream agent to take a write action — opening a PR, rotating a credential, modifying infrastructure — particularly one that holds its own write credentials. If a synthesized answer appears to direct an action, route it through the same judgment (or human review) you'd apply to any other untrusted document, not through automatic execution.

## Cost controls

`/v1/query` costs one embedding call plus up to four LLM calls (three self-heal SQL attempts, one synthesis) — a request-shaped cost surface, not a flat one. Three layers bound it:

- **`query` has a hard length cap** — rejected with `422` before it reaches an embedding or LLM call. Configurable via the `MAX_QUERY_LENGTH` env var (default 2000 characters); in the deployed Lambda that's set from the `MAX_QUERY_LENGTH` GitHub Actions variable.
- **API Gateway throttles the whole API** — a global circuit breaker against a request flood, not a per-key quota. Both keys share it. Configurable via the `API_THROTTLE_RATE_LIMIT`/`API_THROTTLE_BURST_LIMIT` GitHub Actions variables (defaults: 20 req/s steady-state, burst of 40); falls back to those defaults if either is unset.
- **Set a hard monthly spend cap in the Anthropic Console and OpenAI's billing settings.** This is the one control that still holds if the two above are ever bypassed or misconfigured — it isn't part of this codebase, set it directly with the provider.

Neither of the first two distinguishes `API_AUTH_KEY` from `API_ADMIN_KEY`, or one consumer from another — that requires per-key quotas and revocation, which this project doesn't yet have.

## API

All endpoints except `/healthz` and `/webhook/github` require a bearer token — see [Access tiers](#access-tiers).

| Method | Path | Description |
|---|---|---|
| `POST` | `/v1/query` | `{ "query": str, "layers": [str]? }` → runs the full LangGraph engine. `query` length is capped — see [Cost controls](#cost-controls). Returns `{ summary, intent, data, confidence, coverage_note, execution_time_ms }`. REST-only; excluded from MCP — see [MCP](#mcp). |
| `POST` | `/v1/impact` | `{ "project": str, "interface": str }` → deterministic graph traversal only, bypassing intent classification. For callers that already know they want an impact answer. |
| `POST` | `/v1/dependencies` | `{ "project": str }` → what a project declares it depends on (the forward direction of the L3 graph), with each edge's `source` (`manifest` or `static_analysis`). |
| `POST` | `/v1/projects` | `{ "technology": str? }` → list projects, optionally filtered by declared technology. |
| `POST` | `/v1/projects/info` | `{ "project": str }` → metadata and tech stack for a single project by name. |
| `POST` | `/v1/projects/links` | `{ "projects": [str]? }` → canonical `{ name, repo_url, description, is_private, repo_created_at, repo_age_days, repo_pushed_at, stargazers_count, language, forks_count, open_issues_count }` per project. Omit `projects` for all of them, or pass names (e.g. ones a prior search/impact call surfaced) to resolve just those — for citing a source and its basic facts, not recalling them from prose. |
| `POST` | `/v1/search/docs` | `{ "query": str, "project": str?, "limit": int? }` → vector search over L1 documents. |
| `POST` | `/v1/search/code` | `{ "query": str, "project": str?, "limit": int? }` → vector search over L2 code chunks. |
| `POST` | `/v1/search/commits` | `{ "query": str, "project": str?, "since": str?, "until": str?, "limit": int? }` → vector search over L4 commit summaries, optionally time-scoped. |
| `POST` | `/v1/commits/recent` | `{ "project": str?, "limit": int? }` → most recent commits by date, not relevance. No query text, no embedding call. |
| `GET` | `/v1/account` | No body → account-level facts: `{ found, login, name, bio, company, blog, location, account_created_at, account_age_days, public_repos, private_repos, followers, following, synced_at }`. `found: false` means no sync has run yet, not that the account is empty. |
| `POST` | `/webhook/github` | GitHub webhook receiver. HMAC-verified via `X-Hub-Signature-256`. Validates and enqueues to SQS only — actual ingestion runs on the separate worker Lambda; see [Architecture](#architecture). Handles `push`, `repository`, `release`, `ping`. |
| `GET` | `/healthz` | Liveness check, unauthenticated. |

Every endpoint except `/v1/query`, `/webhook/github`, and `/healthz` also backs an MCP tool of the same name (`operation_id`) — see [MCP](#mcp).

## MCP

The same FastAPI app is wrapped as an MCP server (`fastmcp`), exposing eleven scoped, layer-specific tools — one per deterministic capability, routed through the real HTTP endpoints (and therefore through the same Bearer-token auth as any REST caller, forwarded from the MCP caller's own `Authorization` header rather than a fixed key):

| Tool | Backing endpoint |
|---|---|
| `healthz` | `GET /healthz` |
| `impact` | `POST /v1/impact` |
| `get_dependencies` | `POST /v1/dependencies` |
| `list_projects` | `POST /v1/projects` |
| `get_project_info` | `POST /v1/projects/info` |
| `get_project_links` | `POST /v1/projects/links` |
| `get_account_info` | `GET /v1/account` |
| `search_docs` | `POST /v1/search/docs` |
| `search_code` | `POST /v1/search/code` |
| `search_commits` | `POST /v1/search/commits` |
| `get_recent_commits` | `POST /v1/commits/recent` |

`get_project_links` exists because the other tools return a project's *name* (`project_name` in search results, `name` in impact/dependency results) but not its repo URL or basic facts (age, stars, language), and an LLM-synthesized answer on the `/v1/query` path tends to drop these even when they're in scope. Calling `get_project_links` — optionally scoped to the names another call just surfaced — resolves them to a canonical, deterministic record rather than trusting a model to remember or reconstruct one. `get_account_info` answers the account-level version of the same question ("how old is this GitHub account", "how many repos, public vs. private") — a single row unscoped by project.

`query` is deliberately **not** exposed as a tool, even though it's REST-accessible. It exists for callers with no ability to choose a tool themselves (a badge, a GitHub Issue bot); an MCP client can already route itself to the right scoped tool directly, so wrapping the LangGraph-routed NL endpoint as a tool would just add a redundant routing hop on top of the one MCP already gives you. The webhook route is explicitly excluded from tool auto-generation as well.

```
python -m scripts.run_mcp
```

Point an MCP client (Claude Desktop, Claude Code, Cursor) at the resulting server to query the knowledge base conversationally.

## Setup

### Requirements

- Python 3.11+
- Docker (for a local Postgres instance)
- A Postgres-with-pgvector database for real use — this project targets a managed serverless provider (e.g. Neon or Supabase); self-managed RDS is not the target deployment shape
- API keys: GitHub (repo read scope), an embedding provider (OpenAI by default), and Anthropic (used to synthesize answers and generate SQL)

### Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### Configure

```bash
cp .env.example .env
```

Fill in `.env`:

| Variable | Purpose |
|---|---|
| `DATABASE_URL_ADMIN` | Owner connection, used only by the migration runner |
| `DATABASE_URL_RW` | App connection for ingestion (`app_rw` role) |
| `DATABASE_URL_RO` | Privileged query-path connection (`app_ro`, `SELECT`-only, sees private projects) |
| `DATABASE_URL_RO_PUBLIC` | Default query-path connection (`app_ro_public`, public projects only) |
| `TEST_DATABASE_URL` | A **disposable** local Postgres used by integration tests — its schema is dropped and rebuilt on every test run. Never point this at a real database. |
| `GITHUB_TOKEN` | GitHub PAT with repo read scope, used by the sync script |
| `EMBEDDING_PROVIDER`, `OPENAI_API_KEY` | Embedding provider, pluggable via the env var |
| `ANTHROPIC_API_KEY`, `LLM_MODEL` | LLM used for SQL generation and answer synthesis |
| `API_AUTH_KEY` | Bearer token for public-tier access |
| `API_ADMIN_KEY` | Bearer token for privileged access to private projects |
| `GITHUB_WEBHOOK_SECRET` | Shared secret for verifying webhook signatures |

The passwords embedded in `DATABASE_URL_RW`, `DATABASE_URL_RO`, and `DATABASE_URL_RO_PUBLIC` are what the migrations set on those roles — change the URL and re-run `make migrate` to rotate.

### Bring up the database and apply migrations

```bash
make db-up      # starts a local pgvector/pgvector:pg16 container
make migrate     # applies migrations/, creating the three roles, grants, and RLS policies
```

Migrations run the same way against a real managed Postgres instance — point `DATABASE_URL_ADMIN`/`_RW`/`_RO` at it and run `make migrate`.

### Run the API locally

```bash
uvicorn src.main:app --reload
curl http://127.0.0.1:8000/healthz
```

## Ingesting data

**Full sync** — walks every non-fork repo on the configured GitHub account and populates all four layers (documents, code, dependency graph, commits), skipping re-embedding for anything whose content hash hasn't changed:

```bash
make sync-local
```

**Incremental sync** — `POST /webhook/github`, configured against a repo's push events, re-ingests only the layers touched by the changed files (a README-only change touches L1; a `.py` change touches L2 and L4; a `project.yaml` or manifest-file change touches L3).

**Ask a question from the CLI:**

```bash
python -m scripts.ask "which of my projects use Postgres"
python -m scripts.impact "knowledgebase-service" "POST /v1/query"
```

`scripts/impact.py` calls the deterministic graph path directly — no LLM involved, no intent classification.

**Manage secret-scan findings:**

```bash
python -m scripts.resolve_secret list
python -m scripts.resolve_secret resolve <finding-id>
```

## Testing

```bash
make test         # full suite with coverage
make test-unit     # unit tests only, no database required
make lint          # ruff check, ruff format --check, mypy
```

Integration tests run against a real Postgres (`TEST_DATABASE_URL`), not a mock or SQLite — pgvector behavior, the read-only roles' write rejection, and the row-level security that hides private projects are all verified against real grants and policies, not application-level string checks. Nothing in the test suite calls a real LLM or embedding provider or the real GitHub API: `FakeEmbedder` returns deterministic hash-seeded vectors, `FakeLLMClient` returns canned responses, and GitHub responses are mocked from committed fixture payloads.

CI (`.github/workflows/test.yml`) runs on every push and PR against a matrix of Python 3.11/3.12, with a real Postgres service container, followed by a smoke test that the app actually serves `/healthz`.

## Deployment

Infrastructure is defined in Terraform (`infra/`) rather than CDK or Pulumi specifically so the `aws` and `github` providers can be applied together in one run — provisioning the Lambda *and* pointing a GitHub webhook at it in a single `terraform apply`.

- `infra/lambda.tf`, `api_gateway.tf` — the FastAPI app, wrapped by [Mangum](https://github.com/jordaneremieff/mangum), deployed as a container-image Lambda behind an HTTP API Gateway; and a second Lambda from the same image (`src.worker_handler.handler`, no API Gateway, 15-minute timeout) that does the actual webhook ingestion — see [Architecture](#architecture)
- `infra/sqs.tf` — the queue connecting the two: the API Lambda gets `sqs:SendMessage` only, the worker gets `sqs:ReceiveMessage`/`DeleteMessage` only, plus a dead-letter queue after 3 failed receives
- `infra/github.tf` — the GitHub webhook pointed at the deployed endpoint
- `infra/bootstrap/` — a small, separately-applied module that provisions the S3 bucket and DynamoDB table used as Terraform's own remote state backend
- `.github/workflows/deploy.yml` — on a successful `test` run against `main`: builds and pushes the container image to ECR, applies Terraform, and smoke-tests the live `/healthz` endpoint before considering the deploy successful
- `.github/workflows/terraform-plan.yml` — posts a `terraform plan` diff as a PR comment for any PR touching `infra/`

Deployment uses OIDC-federated or scoped AWS credentials configured as repository secrets, not long-lived keys embedded anywhere in the repo.

## Project layout

```
src/
  api/          FastAPI routes (9 scoped endpoints + /v1/query), webhook receiver
                (validates + enqueues only), auth middleware, request/response schemas
  db/           migration runner
  ingestion/    GitHub client, chunkers, secret scanner, embedder, graph population,
                webhook_processor (actual ingestion, runs on the worker Lambda), queue_client
  query/        LangGraph engine for /v1/query, plus the direct SQL/vector/graph calls
                the other 9 endpoints use without going through it
  main.py       FastAPI app (API Lambda entry point)
  worker_handler.py  SQS-triggered worker Lambda entry point (no FastAPI/Mangum)
  mcp_server.py MCP tool wrapper
  lambda_handler.py  Mangum entry point for the API Lambda
scripts/        CLI entry points (sync, ask, impact, migrate, resolve-secret, run-mcp)
migrations/     versioned SQL migrations, applied in order
infra/          Terraform: Lambda (API + worker), API Gateway, SQS, ECR, GitHub webhook,
                remote state bootstrap
tests/
  unit/         no network, no database
  integration/  real Postgres via Docker, mocked external APIs
  e2e/          full API surface via FastAPI's TestClient
  fixtures/     sample repo trees and captured webhook payloads
```
