from src.ingestion.webhook_layers import affected_layers, is_l1_document_path


def test_readme_at_root_is_l1_document() -> None:
    assert is_l1_document_path("README.md")
    assert affected_layers("README.md") == {"documents"}


def test_docs_folder_markdown_is_l1_document() -> None:
    assert is_l1_document_path("docs/architecture.md")
    assert affected_layers("docs/architecture.md") == {"documents"}


def test_markdown_outside_docs_is_not_l1_document() -> None:
    # Matches the seed sync's actual scope exactly - it never looks here either.
    assert not is_l1_document_path("notes/CHANGELOG.md")
    assert affected_layers("notes/CHANGELOG.md") == set()


def test_python_file_touches_code_and_commits() -> None:
    assert affected_layers("src/main.py") == {"code", "commits"}


def test_project_yaml_touches_graph_only() -> None:
    assert affected_layers("project.yaml") == {"graph"}


def test_requirements_txt_touches_graph_only() -> None:
    assert affected_layers("requirements.txt") == {"graph"}


def test_unrelated_file_touches_nothing() -> None:
    assert affected_layers("assets/logo.png") == set()


def test_vendored_code_file_touches_nothing() -> None:
    assert affected_layers("node_modules/pkg/index.js") == set()
