# knowledgebase-service

A queryable knowledge base over a personal GitHub account — not a portfolio search, but a structured map of what has been built and how the pieces connect. It is designed to be consumed by *other agents*, not just humans: a REST API and an MCP server let downstream bots and assistants ask cross-repository questions about a body of work without re-reading every repo themselves.

It answers two different classes of question, backed by two different retrieval strategies:

- **Descriptive** — "Which of my repos use Postgres?", "Summarize my experience with multi-agent systems." Answered with structured SQL and semantic vector search.
- **Structural** — "If I change the response shape of `/users/{id}/flight-history`, which repos break?", "What depends on the `documents` table?" Answered with an explicit, statically-derived dependency graph, walked with a deterministic recursive query — never guessed from embedding similarity.

Domain-specific agents live in their own repositories and call this service over HTTP or MCP for the cross-repo context they don't otherwise have.

## Contents

- [Architecture](#architecture)
- [Data model](#data-model)
- [Query engine](#query-engine)
- [API](#api)
- [MCP](#mcp)
- [Setup](#setup)
- [Ingesting data](#ingesting-data)
- [Testing](#testing)
- [Deployment](#deployment)
- [Project layout](#project-layout)

## Architecture

```
GITHUB (repos, code, commits, READMEs)     /docs (manual: resume, notes, ADRs)
              |                                       |
              +-------------------+-------------------+
                                  v
                     INGESTION PIPELINE
    fetch -> secret scan -> route by layer -> chunk -> embed -> upsert
                                  |
                                  v
                   POSTGRESQL + PGVECTOR
       L1 documents | L2 code chunks | L3 dependency graph | L4 commits
                                  ^
                                  | read-only role (app_ro)
                                  v
                    LANGGRAPH QUERY ENGINE
     Router -> [SQL | Vector | Time | Graph] -> Synthesizer
                                  |
                                  v
               FASTAPI + FASTMCP (AWS Lambda + API Gateway)
                    |                            |
              REST consumers                MCP clients
        (other agents, badges, bots)   (Claude Desktop/Code, Cursor)
```

Ingestion writes through a role with write grants (`app_rw`); every query-path read — REST, MCP, and the LangGraph engine — goes through a separate role (`app_ro`) that only has `SELECT` privileges, enforced at the database level. The natural-language query path never writes, and that boundary is not just an application-level check: the role itself has no write grants, so a sufficiently creative generated query still can't mutate anything.

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

Queries run through a small [LangGraph](https://github.com/langchain-ai/langgraph) state machine:

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

## API

All endpoints except `/healthz` and `/webhook/github` require `Authorization: Bearer <API_AUTH_KEY>`.

| Method | Path | Description |
|---|---|---|
| `POST` | `/v1/query` | `{ "query": str, "layers": [str]? }` → runs the full LangGraph engine. Returns `{ summary, intent, data, confidence, coverage_note, execution_time_ms }`. |
| `POST` | `/v1/impact` | `{ "project": str, "interface": str }` → deterministic graph traversal only, bypassing intent classification. For callers that already know they want an impact answer. |
| `POST` | `/webhook/github` | GitHub webhook receiver. HMAC-verified via `X-Hub-Signature-256`. Handles `push`, `repository`, `release`, `ping`. |
| `GET` | `/healthz` | Liveness check, unauthenticated. |

## MCP

The same FastAPI app is wrapped as an MCP server (`fastmcp`), exposing exactly three tools — `query`, `impact`, `healthz` — routed through the real HTTP endpoints (and therefore through the same Bearer-token auth as any REST caller). The webhook route is explicitly excluded from tool auto-generation.

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
| `DATABASE_URL_RO` | App connection for the query path (`app_ro` role, `SELECT`-only) |
| `TEST_DATABASE_URL` | A **disposable** local Postgres used by integration tests — its schema is dropped and rebuilt on every test run. Never point this at a real database. |
| `GITHUB_TOKEN` | GitHub PAT with repo read scope, used by the sync script |
| `EMBEDDING_PROVIDER`, `OPENAI_API_KEY` | Embedding provider, pluggable via the env var |
| `ANTHROPIC_API_KEY`, `LLM_MODEL` | LLM used for SQL generation and answer synthesis |
| `API_AUTH_KEY` | Bearer token required on the REST/MCP surface |
| `GITHUB_WEBHOOK_SECRET` | Shared secret for verifying webhook signatures |

### Bring up the database and apply migrations

```bash
make db-up      # starts a local pgvector/pgvector:pg16 container
make migrate     # applies migrations/, creating the app_rw / app_ro roles and grants
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

Integration tests run against a real Postgres (`TEST_DATABASE_URL`), not a mock or SQLite — pgvector behavior and the `app_ro` role's write rejection are both verified against real grants, not application-level string checks. Nothing in the test suite calls a real LLM or embedding provider or the real GitHub API: `FakeEmbedder` returns deterministic hash-seeded vectors, `FakeLLMClient` returns canned responses, and GitHub responses are mocked from committed fixture payloads.

CI (`.github/workflows/test.yml`) runs on every push and PR against a matrix of Python 3.11/3.12, with a real Postgres service container, followed by a smoke test that the app actually serves `/healthz`.

## Deployment

Infrastructure is defined in Terraform (`infra/`) rather than CDK or Pulumi specifically so the `aws` and `github` providers can be applied together in one run — provisioning the Lambda *and* pointing a GitHub webhook at it in a single `terraform apply`.

- `infra/lambda.tf`, `api_gateway.tf` — the FastAPI app, wrapped by [Mangum](https://github.com/jordaneremieff/mangum), deployed as a container-image Lambda behind an HTTP API Gateway
- `infra/github.tf` — the GitHub webhook pointed at the deployed endpoint
- `infra/bootstrap/` — a small, separately-applied module that provisions the S3 bucket and DynamoDB table used as Terraform's own remote state backend
- `.github/workflows/deploy.yml` — on a successful `test` run against `main`: builds and pushes the container image to ECR, applies Terraform, and smoke-tests the live `/healthz` endpoint before considering the deploy successful
- `.github/workflows/terraform-plan.yml` — posts a `terraform plan` diff as a PR comment for any PR touching `infra/`

Deployment uses OIDC-federated or scoped AWS credentials configured as repository secrets, not long-lived keys embedded anywhere in the repo.

## Project layout

```
src/
  api/          FastAPI routes, auth middleware, request/response schemas
  db/           migration runner
  ingestion/    GitHub client, chunkers, secret scanner, embedder, graph population
  query/        LangGraph query engine, SQL generation, vector search, graph traversal
  main.py       FastAPI app
  mcp_server.py MCP tool wrapper
  lambda_handler.py  Mangum entry point
scripts/        CLI entry points (sync, ask, impact, migrate, resolve-secret, run-mcp)
migrations/     versioned SQL migrations, applied in order
infra/          Terraform: Lambda, API Gateway, ECR, GitHub webhook, remote state bootstrap
tests/
  unit/         no network, no database
  integration/  real Postgres via Docker, mocked external APIs
  e2e/          full API surface via FastAPI's TestClient
  fixtures/     sample repo trees and captured webhook payloads
```
