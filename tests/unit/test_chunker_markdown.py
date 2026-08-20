from src.ingestion.chunker_markdown import MAX_CONTENT_BYTES, chunk_markdown


def test_splits_on_headings() -> None:
    content = "# Title\nintro text\n\n## Section A\ncontent a\n\n## Section B\ncontent b\n"
    chunks = chunk_markdown(content)
    assert len(chunks) == 3
    assert chunks[0].startswith("# Title")
    assert chunks[1].startswith("## Section A")
    assert chunks[2].startswith("## Section B")


def test_no_headings_is_single_chunk() -> None:
    content = "just some plain text\nwith no headings at all"
    assert chunk_markdown(content) == [content]


def test_empty_content_produces_no_chunks() -> None:
    assert chunk_markdown("") == []
    assert chunk_markdown("   \n  ") == []


def test_oversized_content_is_skipped() -> None:
    huge = "# Title\n" + ("x" * (MAX_CONTENT_BYTES + 1))
    assert chunk_markdown(huge) == []


def test_text_before_first_heading_becomes_its_own_chunk() -> None:
    content = "intro paragraph\n\n## Section\nbody\n"
    chunks = chunk_markdown(content)
    assert chunks[0] == "intro paragraph"
    assert chunks[1].startswith("## Section")


def test_multiple_paragraphs_in_a_section_become_separate_chunks() -> None:
    content = "## Section\npara one\n\npara two\n\npara three\n"
    chunks = chunk_markdown(content)
    assert chunks == [
        "## Section\npara one",
        "## Section\npara two",
        "## Section\npara three",
    ]


def test_heading_with_no_body_is_its_own_chunk() -> None:
    content = "## Empty Section\n"
    assert chunk_markdown(content) == ["## Empty Section"]


def test_paragraph_split_limits_secret_blast_radius() -> None:
    content = (
        "## Configuration\n"
        "Useful setup notes that explain how the service is wired together.\n\n"
        "OPENAI_API_KEY=sk-fake1234567890fake1234567890fake\n\n"
        "More useful architecture notes that should still be retrievable.\n"
    )
    chunks = chunk_markdown(content)
    assert len(chunks) == 3
    assert "Useful setup notes" in chunks[0]
    assert "More useful architecture notes" in chunks[2]
