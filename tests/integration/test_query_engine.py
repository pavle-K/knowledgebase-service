import datetime as dt
import uuid

import psycopg

from src.ingestion.commits import sync_commit
from src.ingestion.documents import upsert_project
from src.ingestion.embedder import FakeEmbedder, format_vector
from src.ingestion.github_client import CommitDetail, CommitFile, CommitInfo, RepoInfo
from src.query.query_engine import run_query_engine
from src.query.synthesizer import FakeLLMClient


def _fake_repo(name: str) -> RepoInfo:
    unique = uuid.uuid4().hex[:8]
    return RepoInfo(
        name=f"{name}-{unique}",
        full_name=f"pavle-K/{name}-{unique}",
        html_url=f"https://github.com/pavle-K/{name}-{unique}",
        description="demo",
        default_branch="main",
        is_private=False,
        fork=False,
    )


def test_vector_intent_routes_through_vector_node(db_conn: psycopg.Connection) -> None:
    project = _fake_repo("vec-proj")
    project_id = upsert_project(db_conn, project)
    embedder = FakeEmbedder()
    content = "This project implements rate limiting for the API."
    embedding = embedder.embed([content])[0]
    db_conn.execute(
        """
        insert into documents
            (project_id, doc_type, source_path, chunk_index, content, embedding, content_hash)
        values (%s, 'readme', 'README.md', 0, %s, %s::vector, 'hash')
        """,
        (project_id, content, format_vector(embedding)),
    )

    llm = FakeLLMClient(response="This project rate-limits API requests.")
    state = run_query_engine(db_conn, embedder, llm, "where do I implement rate limiting")

    assert state["intent"] == "vector"
    assert state["confidence"] == "medium"
    assert state["summary"] == "This project rate-limits API requests."
    assert llm.call_count == 1


def test_graph_intent_routes_through_graph_node_with_high_confidence(
    db_conn: psycopg.Connection,
) -> None:
    provider = _fake_repo("provider")
    provider_id = upsert_project(db_conn, provider)
    consumer_id = upsert_project(db_conn, _fake_repo("consumer"))

    db_conn.execute(
        "insert into exposed_interfaces (project_id, kind, identifier, source)"
        " values (%s, 'http_endpoint', 'POST /v1/query', 'manifest')",
        (provider_id,),
    )
    db_conn.execute(
        "insert into dependencies"
        " (consumer_project_id, provider_project_id, kind, identifier, source)"
        " values (%s, %s, 'http_call', 'POST /v1/query', 'manifest')",
        (consumer_id, provider_id),
    )
    db_conn.execute(
        "update projects set manifest_missing = false where id in (%s, %s)",
        (provider_id, consumer_id),
    )

    embedder = FakeEmbedder()
    llm = FakeLLMClient(response=f"PROJECT: {provider.name}\nINTERFACE: POST /v1/query")

    state = run_query_engine(
        db_conn, embedder, llm, f"what breaks if I change POST /v1/query on {provider.name}"
    )

    assert state["intent"] == "graph"
    assert state["confidence"] == "high"
    assert state["coverage_note"] is None
    assert state["graph_result"] is not None
    assert len(state["graph_result"].impacted) == 1
    assert llm.call_count == 1  # only extraction - graph synthesis is template-based, no LLM


def test_graph_intent_reports_low_confidence_when_extraction_fails(
    db_conn: psycopg.Connection,
) -> None:
    embedder = FakeEmbedder()
    llm = FakeLLMClient(response="UNKNOWN")

    state = run_query_engine(db_conn, embedder, llm, "what breaks if I change something vague")

    assert state["intent"] == "graph"
    assert state["confidence"] == "low"
    assert state["graph_result"] is None


def test_sql_intent_routes_through_self_healing_sql_node(db_conn: psycopg.Connection) -> None:
    project = _fake_repo("sql-proj")
    upsert_project(db_conn, project)
    embedder = FakeEmbedder()
    llm = FakeLLMClient(response=f"select name from projects where name = '{project.name}'")

    state = run_query_engine(db_conn, embedder, llm, "how many projects use Postgres")

    assert state["intent"] == "sql"
    assert state["confidence"] == "high"
    assert state["sql_result"] is not None
    assert state["sql_result"].error is None
    assert state["sql_result"].rows == [{"name": project.name}]
    assert llm.call_count == 2  # generate_sql + sql synthesis


def test_sql_intent_falls_back_to_vector_on_zero_rows(db_conn: psycopg.Connection) -> None:
    project = _fake_repo("fallback-proj")
    project_id = upsert_project(db_conn, project)
    embedder = FakeEmbedder()
    content = "This project is deployed as an AWS Lambda function."
    embedding = embedder.embed([content])[0]
    db_conn.execute(
        """
        insert into documents
            (project_id, doc_type, source_path, chunk_index, content, embedding, content_hash)
        values (%s, 'readme', 'README.md', 0, %s, %s::vector, 'hash')
        """,
        (project_id, content, format_vector(embedding)),
    )

    # Valid SQL that legitimately matches nothing - e.g. an empty technologies table.
    llm = FakeLLMClient(response="select name from projects where name = 'no-such-project'")

    state = run_query_engine(db_conn, embedder, llm, "which of my projects use AWS Lambda")

    assert state["intent"] == "sql"
    assert state["sql_result"] is not None
    assert state["sql_result"].error is None
    assert state["sql_result"].rows == []
    assert len(state["vector_results"]) > 0
    assert state["confidence"] == "medium"
    assert state["coverage_note"] is not None
    assert "semantic search" in state["coverage_note"]
    assert llm.call_count == 2  # generate_sql + fallback synthesis


def test_sql_intent_does_not_fall_back_to_vector_on_error(db_conn: psycopg.Connection) -> None:
    llm = FakeLLMClient(response="select * from not_a_real_table")

    state = run_query_engine(db_conn, FakeEmbedder(), llm, "how many projects use Postgres")

    assert state["intent"] == "sql"
    assert state["sql_result"] is not None
    assert state["sql_result"].error is not None
    assert state["vector_results"] == []
    assert state["confidence"] == "low"
    assert llm.call_count == 3  # 3 self-heal attempts, all fail identically, then give up


def test_hybrid_intent_runs_both_sql_and_vector_nodes(db_conn: psycopg.Connection) -> None:
    project = _fake_repo("hybrid-proj")
    project_id = upsert_project(db_conn, project)
    embedder = FakeEmbedder()
    content = "Uses Postgres for storage."
    embedding = embedder.embed([content])[0]
    db_conn.execute(
        """
        insert into documents
            (project_id, doc_type, source_path, chunk_index, content, embedding, content_hash)
        values (%s, 'readme', 'README.md', 0, %s, %s::vector, 'hash')
        """,
        (project_id, content, format_vector(embedding)),
    )
    llm = FakeLLMClient(response="select name from projects limit 1")

    state = run_query_engine(
        db_conn,
        embedder,
        llm,
        "list all projects that use Postgres and also summarize what they do",
    )

    assert state["intent"] == "hybrid"
    assert state["sql_result"] is not None
    assert state["sql_result"].error is None
    assert len(state["vector_results"]) > 0
    assert llm.call_count == 2  # generate_sql + hybrid synthesis


def test_time_intent_only_returns_commits_within_range(db_conn: psycopg.Connection) -> None:
    project = _fake_repo("time-proj")
    project_id = upsert_project(db_conn, project)
    embedder = FakeEmbedder()
    detail = CommitDetail(
        files=[
            CommitFile(filename="src/f.py", additions=1, deletions=0, patch="@@ -1 +1,2 @@\n+x\n")
        ],
        additions=1,
        deletions=0,
    )

    now = dt.datetime.now(dt.UTC)
    recent = CommitInfo(
        sha="recent1",
        message="Recent work",
        author="pavle-K",
        committed_at=(now - dt.timedelta(days=2)).isoformat(),
    )
    old = CommitInfo(
        sha="old1",
        message="Old work",
        author="pavle-K",
        committed_at=(now - dt.timedelta(days=90)).isoformat(),
    )
    sync_commit(db_conn, project_id, recent, detail, embedder, FakeLLMClient())
    sync_commit(db_conn, project_id, old, detail, embedder, FakeLLMClient())

    llm = FakeLLMClient(response="You worked on recent work.")
    state = run_query_engine(db_conn, embedder, llm, "what did this user work on in the past week")

    assert state["intent"] == "time"
    shas = {r.source_path for r in state["vector_results"]}
    assert "recent1" in shas
    assert "old1" not in shas
    assert llm.call_count == 1  # only synthesis - time parsing is deterministic, no LLM call


def test_latest_intent_returns_newest_commit_first_not_by_similarity(
    db_conn: psycopg.Connection,
) -> None:
    project = _fake_repo("latest-proj")
    project_id = upsert_project(db_conn, project)
    embedder = FakeEmbedder()
    detail = CommitDetail(
        files=[
            CommitFile(filename="src/f.py", additions=1, deletions=0, patch="@@ -1 +1,2 @@\n+x\n")
        ],
        additions=1,
        deletions=0,
    )

    now = dt.datetime.now(dt.UTC)
    # "zzz unrelated wording" would rank last on pure text similarity to the query
    # below - it must still come first here, because it's the newest by date.
    newest = CommitInfo(
        sha="newest1",
        message="zzz unrelated wording",
        author="pavle-K",
        committed_at=now.isoformat(),
    )
    older = CommitInfo(
        sha="older1",
        message="Latest update work",
        author="pavle-K",
        committed_at=(now - dt.timedelta(days=30)).isoformat(),
    )
    sync_commit(db_conn, project_id, newest, detail, embedder, FakeLLMClient())
    sync_commit(db_conn, project_id, older, detail, embedder, FakeLLMClient())

    embed_calls_before = embedder.call_count
    llm = FakeLLMClient(response="The latest update was newest1.")
    state = run_query_engine(db_conn, embedder, llm, "what was the latest update")

    assert state["intent"] == "latest"
    assert state["vector_results"][0].source_path == "newest1"
    assert llm.call_count == 1  # only synthesis
    assert embedder.call_count == embed_calls_before  # no embedding call - pure date sort
