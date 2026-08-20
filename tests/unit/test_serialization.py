from src.api.serialization import state_to_data
from src.query.graph_traversal import ImpactedProject, ImpactResult
from src.query.sql_exec import SqlResult
from src.query.vector_search import SearchResult


def _base_state(**overrides: object) -> dict:
    state = {
        "query": "test",
        "layers": None,
        "intent": "vector",
        "sql_result": None,
        "vector_results": [],
        "graph_result": None,
        "summary": "",
        "confidence": "",
        "coverage_note": None,
    }
    state.update(overrides)
    return state


def test_sql_intent_returns_rows() -> None:
    result = SqlResult(
        rows=[{"name": "x"}], sql="select name from projects", attempts=1, error=None
    )
    state = _base_state(intent="sql", sql_result=result)
    assert state_to_data(state) == [{"name": "x"}]


def test_sql_intent_with_error_returns_none() -> None:
    state = _base_state(intent="sql", sql_result=None)
    assert state_to_data(state) is None


def test_graph_intent_serializes_impacted_projects() -> None:
    result = ImpactResult(
        project_found=True,
        interface_declared=True,
        interface_source="manifest",
        provider_manifest_missing=False,
        impacted=[ImpactedProject(name="consumer", repo_url="https://x", distance=1)],
    )
    state = _base_state(intent="graph", graph_result=result)
    assert state_to_data(state) == [{"name": "consumer", "repo_url": "https://x", "distance": 1}]


def test_graph_intent_with_no_result_returns_none() -> None:
    state = _base_state(intent="graph", graph_result=None)
    assert state_to_data(state) is None


def test_vector_intent_serializes_search_results() -> None:
    results = [SearchResult(project_name="p", source_path="README.md", content="c", distance=0.1)]
    state = _base_state(intent="vector", vector_results=results)
    data = state_to_data(state)
    assert data == [
        {
            "project_name": "p",
            "source_path": "README.md",
            "content": "c",
            "distance": 0.1,
            "layer": "document",
            "symbol_name": None,
            "symbol_type": None,
            "committed_at": None,
        }
    ]


def test_hybrid_intent_combines_sql_and_vector() -> None:
    sql_result = SqlResult(rows=[{"name": "x"}], sql="select 1", attempts=1, error=None)
    vector_results = [
        SearchResult(project_name="p", source_path="README.md", content="c", distance=0.1)
    ]
    state = _base_state(intent="hybrid", sql_result=sql_result, vector_results=vector_results)
    data = state_to_data(state)
    assert data["sql_rows"] == [{"name": "x"}]
    assert len(data["vector_results"]) == 1
