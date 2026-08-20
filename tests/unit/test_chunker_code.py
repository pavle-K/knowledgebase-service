from src.ingestion.chunker_code import (
    MAX_FILE_BYTES,
    chunk_code_file,
    detect_language,
    is_candidate_code_file,
    is_excluded_code_path,
)


def test_detect_language() -> None:
    assert detect_language("src/main.py") == "python"
    assert detect_language("src/app.ts") == "typescript"
    assert detect_language("src/App.tsx") == "tsx"
    assert detect_language("src/index.js") == "javascript"
    assert detect_language("README.md") is None


def test_excluded_code_paths() -> None:
    assert is_excluded_code_path("node_modules/foo/index.js")
    assert is_excluded_code_path(".venv/lib/foo.py")
    assert is_excluded_code_path("package-lock.json")
    assert is_excluded_code_path("poetry.lock")
    assert not is_excluded_code_path("src/main.py")


def test_is_candidate_code_file() -> None:
    assert is_candidate_code_file("src/main.py")
    assert is_candidate_code_file("src/app.ts")
    assert not is_candidate_code_file("node_modules/foo.js")
    assert not is_candidate_code_file("image.png")
    assert not is_candidate_code_file("README.md")


# --- Python (ast-based) ---


def test_python_function_and_class_boundaries() -> None:
    content = """def top_level_function(x):
    return x + 1


class MyClass:
    \"\"\"A docstring.\"\"\"

    def method_one(self):
        return 1

    def method_two(self):
        return 2
"""
    chunks = chunk_code_file("src/example.py", content)
    by_name = {c.symbol_name: c for c in chunks}

    assert set(by_name) == {
        "top_level_function",
        "MyClass",
        "MyClass.method_one",
        "MyClass.method_two",
    }
    assert by_name["top_level_function"].symbol_type == "function"
    assert by_name["MyClass"].symbol_type == "class"
    assert by_name["MyClass"].docstring == "A docstring."
    assert by_name["MyClass.method_one"].symbol_type == "method"
    assert "return 1" in by_name["MyClass.method_one"].content


def test_python_nested_class_in_class() -> None:
    content = """class Outer:
    class Inner:
        def inner_method(self):
            return 1

    def outer_method(self):
        return 2
"""
    chunks = chunk_code_file("src/nested.py", content)
    names = {c.symbol_name for c in chunks}
    # Only direct children of Outer are captured as methods/nested class;
    # Inner.inner_method (grandchild) is not walked - modest scope by design.
    assert "Outer" in names
    assert "Outer.outer_method" in names


def test_python_syntax_error_degrades_gracefully() -> None:
    content = "def broken(:\n    this is not valid python\n"
    assert chunk_code_file("src/broken.py", content) == []


def test_python_async_function() -> None:
    content = "async def fetch_data():\n    return await something()\n"
    chunks = chunk_code_file("src/async_example.py", content)
    assert len(chunks) == 1
    assert chunks[0].symbol_name == "fetch_data"
    assert chunks[0].symbol_type == "function"


def test_oversized_file_is_skipped() -> None:
    content = "def f():\n    pass\n" + ("# padding\n" * MAX_FILE_BYTES)
    assert chunk_code_file("src/huge.py", content) == []


def test_vendored_file_is_skipped() -> None:
    content = "def f():\n    pass\n"
    assert chunk_code_file("node_modules/pkg/index.py", content) == []


# --- JavaScript / TypeScript (tree-sitter) ---


def test_javascript_function_class_and_arrow() -> None:
    content = """function add(a, b) {
    return a + b;
}

class Greeter {
    greet(name) {
        return "hello " + name;
    }
}

const multiply = (a, b) => {
    return a * b;
};
"""
    chunks = chunk_code_file("src/example.js", content)
    by_name = {c.symbol_name: c for c in chunks}

    assert by_name["add"].symbol_type == "function"
    assert by_name["Greeter"].symbol_type == "class"
    assert by_name["Greeter.greet"].symbol_type == "method"
    assert by_name["multiply"].symbol_type == "function"


def test_typescript_extension_uses_typescript_grammar() -> None:
    content = "function greet(name: string): string {\n    return `hi ${name}`;\n}\n"
    chunks = chunk_code_file("src/greet.ts", content)
    assert len(chunks) == 1
    assert chunks[0].symbol_name == "greet"
    assert chunks[0].language == "typescript"


def test_tsx_extension_uses_tsx_grammar() -> None:
    content = "function Component() {\n    return null;\n}\n"
    chunks = chunk_code_file("src/Component.tsx", content)
    assert len(chunks) == 1
    assert chunks[0].language == "tsx"


# --- Heuristic fallback ---


def test_heuristic_fallback_for_unsupported_language() -> None:
    content = "\n".join(f"line {i}" for i in range(150))
    chunks = chunk_code_file("script.sh", content)
    assert len(chunks) == 3  # 150 lines / 60 per chunk
    assert all(c.symbol_type == "module" for c in chunks)
    assert all(c.symbol_name == "" for c in chunks)
