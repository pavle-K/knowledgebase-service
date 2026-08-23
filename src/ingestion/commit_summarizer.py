"""Commit noise filtering and LLM diff summarization.

Never stores the raw patch - it's used here to build a short summary, then
discarded. Only lockfile-only and pure-whitespace commits are treated as noise.
"""

from __future__ import annotations

from src.ingestion.chunker_code import LOCKFILE_NAMES
from src.ingestion.github_client import CommitFile
from src.query.synthesizer import UNTRUSTED_CONTENT_INSTRUCTION, LLMClient, wrap_untrusted

MAX_DIFF_CHARS = 8000

DIFF_SUMMARY_SYSTEM_PROMPT = (
    "Summarize this git commit in 1-3 sentences: what changed and why it likely matters. "
    "Be concise and factual, based only on the diff and message provided. "
    + UNTRUSTED_CONTENT_INSTRUCTION
)


def _is_lockfile(filename: str) -> bool:
    return filename.rsplit("/", 1)[-1] in LOCKFILE_NAMES


def _is_whitespace_only_patch(patch: str) -> bool:
    added = {line[1:].strip() for line in patch.splitlines() if line.startswith("+")}
    removed = {line[1:].strip() for line in patch.splitlines() if line.startswith("-")}
    return added == removed


def is_noise_commit(files: list[CommitFile]) -> bool:
    if not files:
        return True
    if all(_is_lockfile(f.filename) for f in files):
        return True
    patches = [f.patch for f in files if f.patch]
    if patches and all(_is_whitespace_only_patch(p) for p in patches):
        return True
    return False


def build_diff_text(files: list[CommitFile]) -> str:
    parts = [
        f"--- {f.filename} (+{f.additions}/-{f.deletions}) ---\n{f.patch or '(no patch available)'}"
        for f in files
    ]
    return "\n\n".join(parts)[:MAX_DIFF_CHARS]


def summarize_commit(message: str, diff_text: str, llm: LLMClient) -> str:
    user_prompt = (
        f"Commit message:\n{wrap_untrusted(message)}\n\nDiff:\n{wrap_untrusted(diff_text)}"
    )
    return llm.complete(DIFF_SUMMARY_SYSTEM_PROMPT, user_prompt)
