from src.ingestion.graph_static_analysis import (
    find_fastapi_routes,
    find_hardcoded_urls,
    parse_package_json,
    parse_pyproject_toml,
    parse_requirements_txt,
)


def test_parse_requirements_txt() -> None:
    content = "fastapi>=0.115\nrequests==2.31.0\n# a comment\n\n-r other.txt\nnumpy\n"
    deps = parse_requirements_txt(content)
    names = {d.name for d in deps}
    assert names == {"fastapi", "requests", "numpy"}
    fastapi_dep = next(d for d in deps if d.name == "fastapi")
    assert fastapi_dep.version_constraint == ">=0.115"


def test_parse_pyproject_toml_pep621() -> None:
    content = """
[project]
name = "demo"
dependencies = ["httpx>=0.27", "pydantic"]
"""
    deps = parse_pyproject_toml(content)
    names = {d.name for d in deps}
    assert names == {"httpx", "pydantic"}


def test_parse_pyproject_toml_poetry() -> None:
    content = """
[tool.poetry.dependencies]
python = "^3.11"
fastapi = "^0.115"
requests = { version = "^2.31", extras = ["socks"] }
"""
    deps = parse_pyproject_toml(content)
    names = {d.name for d in deps}
    assert names == {"fastapi", "requests"}
    requests_dep = next(d for d in deps if d.name == "requests")
    assert requests_dep.version_constraint == "^2.31"


def test_parse_pyproject_toml_malformed_returns_empty() -> None:
    assert parse_pyproject_toml("not valid [[[ toml") == []


def test_parse_package_json() -> None:
    content = '{"dependencies": {"express": "^4.18"}, "devDependencies": {"jest": "^29.0"}}'
    deps = parse_package_json(content)
    names = {d.name for d in deps}
    assert names == {"express", "jest"}


def test_parse_package_json_malformed_returns_empty() -> None:
    assert parse_package_json("{not valid json") == []


def test_find_fastapi_routes() -> None:
    content = """
@app.get("/healthz")
def healthz():
    return {"status": "ok"}

@router.post("/v1/query")
def query():
    pass
"""
    routes = find_fastapi_routes(content)
    assert {(r.method, r.path) for r in routes} == {("GET", "/healthz"), ("POST", "/v1/query")}


def test_find_hardcoded_urls() -> None:
    content = (
        'response = httpx.get("https://api.github.com/user/repos")\nother = "https://example.com/x"'
    )
    urls = find_hardcoded_urls(content)
    assert urls == ["https://api.github.com/user/repos", "https://example.com/x"]


def test_find_hardcoded_urls_none_found() -> None:
    assert find_hardcoded_urls("just some plain code, no urls here") == []
