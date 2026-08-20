import json
from pathlib import Path

import httpx
import respx

from src.ingestion.github_client import GITHUB_API_BASE, GitHubClient

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "github_api"


def _load(name: str) -> dict | list:
    return json.loads((FIXTURES / name).read_text())


@respx.mock
def test_list_repos_excludes_nothing_itself_and_paginates_to_empty() -> None:
    respx.get(f"{GITHUB_API_BASE}/user/repos", params={"page": "1"}).mock(
        return_value=httpx.Response(200, json=_load("repos_page1.json"))
    )
    respx.get(f"{GITHUB_API_BASE}/user/repos", params={"page": "2"}).mock(
        return_value=httpx.Response(200, json=[])
    )

    client = GitHubClient(token="fake-token")
    repos = client.list_repos()

    assert len(repos) == 2
    assert repos[0].full_name == "pavle-K/knowledgebase-service"
    assert repos[0].fork is False
    assert repos[1].fork is True


@respx.mock
def test_get_readme_decodes_base64() -> None:
    respx.get(f"{GITHUB_API_BASE}/repos/pavle-K/knowledgebase-service/readme").mock(
        return_value=httpx.Response(200, json=_load("readme.json"))
    )

    client = GitHubClient(token="fake-token")
    content = client.get_readme("pavle-K/knowledgebase-service")

    assert content == "# Hello\nworld\n"


@respx.mock
def test_get_readme_returns_none_on_404() -> None:
    respx.get(f"{GITHUB_API_BASE}/repos/pavle-K/no-readme/readme").mock(
        return_value=httpx.Response(404, json={"message": "Not Found"})
    )

    client = GitHubClient(token="fake-token")
    assert client.get_readme("pavle-K/no-readme") is None


@respx.mock
def test_list_docs_files_filters_to_markdown_files() -> None:
    respx.get(f"{GITHUB_API_BASE}/repos/pavle-K/knowledgebase-service/contents/docs").mock(
        return_value=httpx.Response(200, json=_load("docs_listing.json"))
    )

    client = GitHubClient(token="fake-token")
    paths = client.list_docs_files("pavle-K/knowledgebase-service")

    assert paths == ["docs/architecture.md"]


@respx.mock
def test_list_docs_files_returns_empty_on_404() -> None:
    respx.get(f"{GITHUB_API_BASE}/repos/pavle-K/no-docs/contents/docs").mock(
        return_value=httpx.Response(404, json={"message": "Not Found"})
    )

    client = GitHubClient(token="fake-token")
    assert client.list_docs_files("pavle-K/no-docs") == []


@respx.mock
def test_get_file_decodes_base64() -> None:
    respx.get(
        f"{GITHUB_API_BASE}/repos/pavle-K/knowledgebase-service/contents/docs/architecture.md"
    ).mock(return_value=httpx.Response(200, json=_load("architecture_doc.json")))

    client = GitHubClient(token="fake-token")
    content = client.get_file("pavle-K/knowledgebase-service", "docs/architecture.md")

    assert content == "# Architecture\ndetails here\n"
