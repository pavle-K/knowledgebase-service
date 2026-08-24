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
    created_at: str | None = None  # ISO 8601, as returned by GitHub
    pushed_at: str | None = None
    stargazers_count: int | None = None
    language: str | None = None
    forks_count: int | None = None
    open_issues_count: int | None = None


@dataclass(frozen=True)
class AccountInfo:
    login: str
    name: str | None
    bio: str | None
    company: str | None
    blog: str | None
    location: str | None
    created_at: str  # ISO 8601, as returned by GitHub
    public_repos: int
    private_repos: int | None  # only present when authenticated as the account itself
    followers: int
    following: int


@dataclass(frozen=True)
class CommitInfo:
    sha: str
    message: str
    author: str | None
    committed_at: str  # ISO 8601, as returned by GitHub


@dataclass(frozen=True)
class CommitFile:
    filename: str
    additions: int
    deletions: int
    patch: str | None  # absent for binary/huge files


@dataclass(frozen=True)
class CommitDetail:
    files: list[CommitFile]
    additions: int
    deletions: int


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
        per_page = 100
        repos: list[RepoInfo] = []
        page = 1
        while True:
            response = self._client.get(
                "/user/repos",
                params={"per_page": per_page, "page": page, "affiliation": "owner"},
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
                    created_at=item["created_at"],
                    pushed_at=item.get("pushed_at"),
                    stargazers_count=item["stargazers_count"],
                    language=item.get("language"),
                    forks_count=item["forks_count"],
                    open_issues_count=item["open_issues_count"],
                )
                for item in batch
            )
            if len(batch) < per_page:
                break  # short page: no more repos to fetch, save a request
            page += 1
        return repos

    def get_account_info(self) -> AccountInfo:
        """GET /user - the account that owns GITHUB_TOKEN. total_private_repos is only
        present for the authenticated account, not the public /users/{username} view."""
        response = self._client.get("/user")
        response.raise_for_status()
        data = response.json()
        return AccountInfo(
            login=data["login"],
            name=data.get("name"),
            bio=data.get("bio"),
            company=data.get("company"),
            blog=data.get("blog") or None,
            location=data.get("location"),
            created_at=data["created_at"],
            public_repos=data["public_repos"],
            private_repos=data.get("total_private_repos"),
            followers=data["followers"],
            following=data["following"],
        )

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

    def list_all_files(self, full_name: str, ref: str) -> list[str]:
        response = self._client.get(
            f"/repos/{full_name}/git/trees/{ref}", params={"recursive": "1"}
        )
        # 404: ref not found. 409: empty repo (no commits yet) - GitHub's quirky status
        # for this case. Both mean "nothing to list", not an error.
        if response.status_code in (404, 409):
            return []
        response.raise_for_status()
        data = response.json()
        return [item["path"] for item in data.get("tree", []) if item["type"] == "blob"]

    def list_commits(self, full_name: str, max_count: int) -> list[CommitInfo]:
        per_page = 100
        commits: list[CommitInfo] = []
        page = 1
        while len(commits) < max_count:
            response = self._client.get(
                f"/repos/{full_name}/commits", params={"per_page": per_page, "page": page}
            )
            if response.status_code in (404, 409):
                break
            response.raise_for_status()
            batch = response.json()
            if not batch:
                break
            for item in batch:
                commit = item["commit"]
                commits.append(
                    CommitInfo(
                        sha=item["sha"],
                        message=commit["message"],
                        author=commit.get("author", {}).get("name"),
                        committed_at=commit.get("author", {}).get("date"),
                    )
                )
                if len(commits) >= max_count:
                    break
            if len(batch) < per_page:
                break  # short page: no more commits to fetch, save a request
            page += 1
        return commits

    def get_commit_detail(self, full_name: str, sha: str) -> CommitDetail | None:
        response = self._client.get(f"/repos/{full_name}/commits/{sha}")
        if response.status_code == 404:
            return None
        response.raise_for_status()
        data = response.json()
        files = [
            CommitFile(
                filename=f["filename"],
                additions=f["additions"],
                deletions=f["deletions"],
                patch=f.get("patch"),
            )
            for f in data.get("files", [])
        ]
        stats = data.get("stats", {})
        return CommitDetail(
            files=files, additions=stats.get("additions", 0), deletions=stats.get("deletions", 0)
        )
