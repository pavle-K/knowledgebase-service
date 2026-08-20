"""Thin GitHub REST client: repo metadata, READMEs, /docs markdown files."""

from __future__ import annotations

import base64
from dataclasses import dataclass

import httpx

GITHUB_API_BASE = "https://api.github.com"


@dataclass(frozen=True)
class RepoInfo:
    name: str
    full_name: str
    html_url: str
    description: str | None
    default_branch: str
    is_private: bool
    fork: bool


class GitHubClient:
    def __init__(self, token: str, base_url: str = GITHUB_API_BASE) -> None:
        self._client = httpx.Client(
            base_url=base_url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=30.0,
        )

    def close(self) -> None:
        self._client.close()

    def list_repos(self) -> list[RepoInfo]:
        repos: list[RepoInfo] = []
        page = 1
        while True:
            response = self._client.get(
                "/user/repos",
                params={"per_page": 100, "page": page, "affiliation": "owner"},
            )
            response.raise_for_status()
            batch = response.json()
            if not batch:
                break
            repos.extend(
                RepoInfo(
                    name=item["name"],
                    full_name=item["full_name"],
                    html_url=item["html_url"],
                    description=item.get("description"),
                    default_branch=item["default_branch"],
                    is_private=item["private"],
                    fork=item["fork"],
                )
                for item in batch
            )
            page += 1
        return repos

    def get_readme(self, full_name: str) -> str | None:
        response = self._client.get(f"/repos/{full_name}/readme")
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return base64.b64decode(response.json()["content"]).decode("utf-8", errors="replace")

    def get_file(self, full_name: str, path: str) -> str | None:
        response = self._client.get(f"/repos/{full_name}/contents/{path}")
        if response.status_code == 404:
            return None
        response.raise_for_status()
        data = response.json()
        if isinstance(data, list) or data.get("encoding") != "base64":
            return None
        return base64.b64decode(data["content"]).decode("utf-8", errors="replace")

    def list_docs_files(self, full_name: str, path: str = "docs") -> list[str]:
        response = self._client.get(f"/repos/{full_name}/contents/{path}")
        if response.status_code == 404:
            return []
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, list):
            return []
        return [
            item["path"] for item in data if item["type"] == "file" and item["name"].endswith(".md")
        ]
