from src.ingestion.commit_summarizer import (
    MAX_DIFF_CHARS,
    build_diff_text,
    is_noise_commit,
    summarize_commit,
)
from src.ingestion.github_client import CommitFile
from src.query.synthesizer import FakeLLMClient

REAL_CHANGE_PATCH = "@@ -1,3 +1,4 @@\n def add(a, b):\n+    # explain\n     return a + b\n"
WHITESPACE_ONLY_PATCH = "@@ -1,2 +1,2 @@\n-def add(a, b):\n+def add(a, b):  \n     return a + b\n"


def test_empty_files_is_noise() -> None:
    assert is_noise_commit([]) is True


def test_lockfile_only_commit_is_noise() -> None:
    files = [CommitFile(filename="package-lock.json", additions=10, deletions=2, patch="...")]
    assert is_noise_commit(files) is True


def test_mixed_lockfile_and_real_file_is_not_noise() -> None:
    files = [
        CommitFile(filename="package-lock.json", additions=10, deletions=2, patch="..."),
        CommitFile(filename="src/main.py", additions=1, deletions=0, patch=REAL_CHANGE_PATCH),
    ]
    assert is_noise_commit(files) is False


def test_whitespace_only_change_is_noise() -> None:
    files = [CommitFile(filename="src/x.py", additions=1, deletions=1, patch=WHITESPACE_ONLY_PATCH)]
    assert is_noise_commit(files) is True


def test_real_content_change_is_not_noise() -> None:
    files = [CommitFile(filename="src/x.py", additions=1, deletions=0, patch=REAL_CHANGE_PATCH)]
    assert is_noise_commit(files) is False


def test_build_diff_text_includes_filenames_and_patches() -> None:
    files = [CommitFile(filename="src/x.py", additions=1, deletions=0, patch=REAL_CHANGE_PATCH)]
    text = build_diff_text(files)
    assert "src/x.py" in text
    assert "explain" in text


def test_build_diff_text_truncates_to_max_chars() -> None:
    huge_patch = "+" + ("x" * (MAX_DIFF_CHARS * 2))
    files = [CommitFile(filename="src/big.py", additions=1, deletions=0, patch=huge_patch)]
    text = build_diff_text(files)
    assert len(text) == MAX_DIFF_CHARS


def test_summarize_commit_calls_llm_with_message_and_diff() -> None:
    llm = FakeLLMClient(response="adds a comment explaining the addition")
    summary = summarize_commit("add comment", "diff content here", llm)

    assert summary == "adds a comment explaining the addition"
    assert llm.call_count == 1
    assert "add comment" in (llm.last_user or "")
    assert "diff content here" in (llm.last_user or "")
