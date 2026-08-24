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
    assert repos[0].created_at == "2026-01-01T00:00:00Z"
    assert repos[0].stargazers_count == 3
    assert repos[0].language == "Python"


@respx.mock
def test_get_account_info_parses_authenticated_user() -> None:
    respx.get(f"{GITHUB_API_BASE}/user").mock(
        return_value=httpx.Response(200, json=_load("user.json"))
    )

    client = GitHubClient(token="fake-token")
    account = client.get_account_info()

    assert account.login == "pavle-K"
    assert account.created_at == "2015-03-01T00:00:00Z"
    assert account.public_repos == 12
    assert account.private_repos == 4
    assert account.followers == 7


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


@respx.mock
def test_list_all_files_returns_only_blobs() -> None:
    respx.get(f"{GITHUB_API_BASE}/repos/pavle-K/knowledgebase-service/git/trees/main").mock(
        return_value=httpx.Response(200, json=_load("tree_listing.json"))
    )

    client = GitHubClient(token="fake-token")
    files = client.list_all_files("pavle-K/knowledgebase-service", "main")

    assert files == ["README.md", "src/main.py", "node_modules/pkg/index.js"]


@respx.mock
def test_list_all_files_returns_empty_on_404() -> None:
    respx.get(f"{GITHUB_API_BASE}/repos/pavle-K/empty/git/trees/main").mock(
        return_value=httpx.Response(404, json={"message": "Not Found"})
    )

    client = GitHubClient(token="fake-token")
    assert client.list_all_files("pavle-K/empty", "main") == []


@respx.mock
def test_list_all_files_returns_empty_on_409_empty_repo() -> None:
    # GitHub returns 409, not 404, for a repo with no commits yet.
    respx.get(f"{GITHUB_API_BASE}/repos/pavle-K/empty-repo/git/trees/main").mock(
        return_value=httpx.Response(409, json={"message": "Git Repository is empty."})
    )

    client = GitHubClient(token="fake-token")
    assert client.list_all_files("pavle-K/empty-repo", "main") == []


@respx.mock
def test_list_commits_parses_message_author_and_date() -> None:
    respx.get(f"{GITHUB_API_BASE}/repos/pavle-K/demo/commits", params={"page": "1"}).mock(
        return_value=httpx.Response(200, json=_load("commits_list.json"))
    )

    client = GitHubClient(token="fake-token")
    commits = client.list_commits("pavle-K/demo", max_count=10)

    assert len(commits) == 2
    assert commits[0].sha == "abc123"
    assert commits[0].message == "Add rate limiting"
    assert commits[0].author == "pavle-K"
    assert commits[0].committed_at == "2026-01-15T10:00:00Z"


@respx.mock
def test_list_commits_stops_at_max_count() -> None:
    respx.get(f"{GITHUB_API_BASE}/repos/pavle-K/demo/commits", params={"page": "1"}).mock(
        return_value=httpx.Response(200, json=_load("commits_list.json"))
    )

    client = GitHubClient(token="fake-token")
    commits = client.list_commits("pavle-K/demo", max_count=1)

    assert len(commits) == 1


@respx.mock
def test_list_commits_returns_empty_on_409_empty_repo() -> None:
    respx.get(f"{GITHUB_API_BASE}/repos/pavle-K/empty/commits", params={"page": "1"}).mock(
        return_value=httpx.Response(409, json={"message": "Git Repository is empty."})
    )

    client = GitHubClient(token="fake-token")
    assert client.list_commits("pavle-K/empty", max_count=10) == []


@respx.mock
def test_get_commit_detail_parses_files_and_stats() -> None:
    respx.get(f"{GITHUB_API_BASE}/repos/pavle-K/demo/commits/abc123").mock(
        return_value=httpx.Response(200, json=_load("commit_detail.json"))
    )

    client = GitHubClient(token="fake-token")
    detail = client.get_commit_detail("pavle-K/demo", "abc123")

    assert detail is not None
    assert detail.additions == 12
    assert detail.deletions == 2
    assert len(detail.files) == 1
    assert detail.files[0].filename == "src/guardrails.py"
    assert detail.files[0].patch is not None


@respx.mock
def test_get_commit_detail_returns_none_on_404() -> None:
    respx.get(f"{GITHUB_API_BASE}/repos/pavle-K/demo/commits/deadbeef").mock(
        return_value=httpx.Response(404, json={"message": "Not Found"})
    )

    client = GitHubClient(token="fake-token")
    assert client.get_commit_detail("pavle-K/demo", "deadbeef") is None
