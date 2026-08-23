import pytest

from src.query.graph_traversal import ImpactedProject, ImpactResult
from src.query.query_synthesis import build_synthesis
from src.query.sql_exec import SqlResult
from src.query.synthesizer import FakeLLMClient


def _base_state(**overrides: object) -> dict:
    state = {
        "query": "test query",
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


def test_graph_project_not_found_is_low_confidence() -> None:
    result = ImpactResult(
        project_found=False,
        interface_declared=False,
        interface_source=None,
        provider_manifest_missing=True,
        impacted=[],
    )
    state = _base_state(intent="graph", graph_result=result)
    summary, confidence, coverage_note = build_synthesis(state, FakeLLMClient())
    assert confidence == "low"
    assert "No project" in summary


def test_graph_undeclared_interface_is_low_confidence() -> None:
    result = ImpactResult(
        project_found=True,
        interface_declared=False,
        interface_source=None,
        provider_manifest_missing=False,
        impacted=[],
    )
    state = _base_state(intent="graph", graph_result=result)
    _, confidence, _ = build_synthesis(state, FakeLLMClient())
    assert confidence == "low"


def test_graph_static_analysis_source_is_medium_confidence() -> None:
    result = ImpactResult(
        project_found=True,
        interface_declared=True,
        interface_source="static_analysis",
        provider_manifest_missing=False,
        impacted=[],
    )
    state = _base_state(intent="graph", graph_result=result)
    _, confidence, _ = build_synthesis(state, FakeLLMClient())
    assert confidence == "medium"


def test_graph_manifest_source_is_high_confidence() -> None:
    result = ImpactResult(
        project_found=True,
        interface_declared=True,
        interface_source="manifest",
        provider_manifest_missing=False,
        impacted=[ImpactedProject(name="consumer", repo_url="https://x", distance=1)],
    )
    state = _base_state(intent="graph", graph_result=result)
    summary, confidence, coverage_note = build_synthesis(state, FakeLLMClient())
    assert confidence == "high"
    assert coverage_note is None
    assert "consumer" in summary


def test_graph_missing_manifest_produces_coverage_note() -> None:
    result = ImpactResult(
        project_found=True,
        interface_declared=True,
        interface_source="manifest",
        provider_manifest_missing=True,
        impacted=[],
    )
    state = _base_state(intent="graph", graph_result=result)
    _, _, coverage_note = build_synthesis(state, FakeLLMClient())
    assert coverage_note is not None
    assert "no project.yaml" in coverage_note


def test_sql_error_is_low_confidence_and_never_fabricates() -> None:
    result = SqlResult(
        rows=None, sql="select bad_column", attempts=3, error="column does not exist"
    )
    state = _base_state(intent="sql", sql_result=result)
    summary, confidence, _ = build_synthesis(state, FakeLLMClient())
    assert confidence == "low"
    assert "3 attempts" in summary


def test_sql_error_does_not_leak_raw_driver_error_to_caller(
    caplog: pytest.LogCaptureFixture,
) -> None:
    result = SqlResult(
        rows=None,
        sql="select bad_column",
        attempts=3,
        error='column "bad_column" does not exist HINT: Perhaps you meant "good_column".',
    )
    state = _base_state(intent="sql", sql_result=result)

    with caplog.at_level("WARNING"):
        summary, _, _ = build_synthesis(state, FakeLLMClient())

    assert "good_column" not in summary
    assert "HINT" not in summary
    assert "good_column" in caplog.text


def test_sql_empty_rows_is_high_confidence_no_llm_call() -> None:
    result = SqlResult(rows=[], sql="select name from projects where 1=0", attempts=1, error=None)
    state = _base_state(intent="sql", sql_result=result)
    llm = FakeLLMClient()
    summary, confidence, _ = build_synthesis(state, llm)
    assert confidence == "high"
    assert llm.call_count == 0
    assert "No rows" in summary
