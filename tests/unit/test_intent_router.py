import pytest

from src.query.intent_router import classify_intent

# Highest-value test in the suite (CLAUDE.md section 10): impact-analysis phrasings
# must route to 'graph', never 'vector'. Not negotiable.
CASES = [
    # --- graph: impact/blast-radius phrasings (must never be vector) ---
    ("what breaks if I change the response shape of /users/{id}/flight-history", "graph"),
    ("what depends on the documents table", "graph"),
    ("who calls the gdpr-anonymize endpoint", "graph"),
    ("who consumes POST /v1/query", "graph"),
    ("what would break if I change this schema", "graph"),
    ("if I change this endpoint, what breaks", "graph"),
    ("what's the impact of removing this table", "graph"),
    ("what is the blast radius of changing auth", "graph"),
    ("which projects depend on knowledgebase-service", "graph"),
    ("if we change the payment API, what happens", "graph"),
    # --- sql: structured/aggregate questions ---
    ("which of my repos use AWS Lambda and Postgres", "sql"),
    ("how many projects use FastAPI", "sql"),
    ("list all projects that use Python", "sql"),
    ("count of repos with no manifest", "sql"),
    # --- vector: descriptive/semantic questions ---
    ("summarize my experience with multi-agent systems", "vector"),
    ("find project docs that mention distributed caching", "vector"),
    ("where do I implement rate limiting", "vector"),
    ("how did auth evolve in plane-refunds-gdpr-agent", "vector"),
    ("what does the pr-review-bot project do", "vector"),
    # --- hybrid: explicit compound signal ---
    ("list all projects that use Postgres and also summarize what they do", "hybrid"),
]


@pytest.mark.parametrize("query,expected", CASES)
def test_classify_intent(query: str, expected: str) -> None:
    assert classify_intent(query) == expected


def test_all_graph_phrasings_route_to_graph_not_vector() -> None:
    impact_phrasings = [
        "what breaks if I change X",
        "what depends on Y",
        "who calls Z",
    ]
    for phrasing in impact_phrasings:
        assert classify_intent(phrasing) == "graph"
