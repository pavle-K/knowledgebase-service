from src.query.impact_extractor import extract_impact_params
from src.query.synthesizer import FakeLLMClient


def test_extracts_project_and_interface() -> None:
    llm = FakeLLMClient(response="PROJECT: knowledgebase-service\nINTERFACE: POST /v1/query")
    result = extract_impact_params("what breaks if I change POST /v1/query", llm)
    assert result == ("knowledgebase-service", "POST /v1/query")


def test_returns_none_on_unknown() -> None:
    llm = FakeLLMClient(response="UNKNOWN")
    assert extract_impact_params("what breaks if I change something vague", llm) is None


def test_returns_none_on_malformed_response() -> None:
    llm = FakeLLMClient(response="I'm not sure what you mean")
    assert extract_impact_params("what breaks", llm) is None
