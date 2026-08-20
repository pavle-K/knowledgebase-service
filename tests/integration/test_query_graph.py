import uuid

import psycopg

from src.ingestion.documents import upsert_project
from src.ingestion.embedder import FakeEmbedder, format_vector
from src.ingestion.github_client import RepoInfo
from src.query.graph import run_query
from src.query.synthesizer import FakeLLMClient


def test_run_query_wires_vector_search_into_synthesizer(db_conn: psycopg.Connection) -> None:
    unique = uuid.uuid4().hex[:8]
    repo = RepoInfo(
        name=f"demo-{unique}",
        full_name=f"pavle-K/demo-{unique}",
        html_url=f"https://github.com/pavle-K/demo-{unique}",
        description="demo",
        default_branch="main",
        is_private=False,
        fork=False,
    )
    project_id = upsert_project(db_conn, repo)
    embedder = FakeEmbedder()
    content = "This project uses FastAPI and Postgres with pgvector."
    embedding = embedder.embed([content])[0]
    db_conn.execute(
        """
        insert into documents
            (project_id, doc_type, source_path, chunk_index, content, embedding, content_hash)
        values (%s, 'readme', 'README.md', 0, %s, %s::vector, 'hash')
        """,
        (project_id, content, format_vector(embedding)),
    )

    llm = FakeLLMClient(response="This project uses FastAPI and Postgres.")
    state = run_query(db_conn, embedder, llm, "what does this project use?")

    assert state["summary"] == "This project uses FastAPI and Postgres."
    assert len(state["results"]) == 1
    assert state["results"][0].content == content
    assert llm.call_count == 1
    assert "what does this project use?" in (llm.last_user or "")
