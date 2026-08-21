import httpx
import respx

from src.ingestion.exclusion import EXCLUDE_MARKER_PATH, is_excluded
from src.ingestion.github_client import GITHUB_API_BASE, GitHubClient


@respx.mock
def test_is_excluded_true_when_marker_file_present() -> None:
    respx.get(f"{GITHUB_API_BASE}/repos/pavle-K/secret-repo/contents/{EXCLUDE_MARKER_PATH}").mock(
        return_value=httpx.Response(200, json={"content": "", "encoding": "base64"})
    )

    client = GitHubClient(token="fake-token")
    assert is_excluded(client, "pavle-K/secret-repo") is True


@respx.mock
def test_is_excluded_false_when_marker_file_absent() -> None:
    respx.get(f"{GITHUB_API_BASE}/repos/pavle-K/open-repo/contents/{EXCLUDE_MARKER_PATH}").mock(
        return_value=httpx.Response(404, json={"message": "Not Found"})
    )

    client = GitHubClient(token="fake-token")
    assert is_excluded(client, "pavle-K/open-repo") is False
