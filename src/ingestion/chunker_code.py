"""Chunk source code by symbol (function/class/method) - never whole files.

tree-sitter for JS/TS (language-aware), stdlib ast for Python, a simple
heuristic splitter for everything else. Skips vendored dirs, lockfiles, and
oversized files.
"""

from __future__ import annotations

import ast
import fnmatch
from dataclasses import dataclass

import tree_sitter_javascript as tsjs
import tree_sitter_typescript as tsts
from tree_sitter import Language, Node, Parser

MAX_FILE_BYTES = 200_000
HEURISTIC_CHUNK_LINES = 60

VENDORED_DIR_PATTERNS = ["node_modules/*", ".venv/*", "venv/*", "dist/*", "build/*", ".git/*"]
LOCKFILE_NAMES = {
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "poetry.lock",
    "Pipfile.lock",
    "Cargo.lock",
    "composer.lock",
    "Gemfile.lock",
}

# Extensions attempted at all. Anything else is skipped - not "code" for L2 purposes.
CODE_EXTENSIONS = {
    ".py",
    ".js",
    ".jsx",
    ".mjs",
    ".cjs",
    ".ts",
    ".tsx",
    ".go",
    ".rs",
    ".java",
    ".rb",
    ".php",
    ".c",
    ".cpp",
    ".h",
    ".hpp",
    ".cs",
    ".swift",
    ".kt",
    ".sh",
    ".sql",
}

_LANGUAGE_BY_EXTENSION = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "typescript",
    ".tsx": "tsx",
}


@dataclass(frozen=True)
class CodeChunk:
    symbol_name: str | None
    symbol_type: str  # 'function' | 'class' | 'method' | 'module'
    language: str
    start_line: int
    end_line: int
    content: str
    docstring: str | None = None


def is_excluded_code_path(path: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    if name in LOCKFILE_NAMES:
        return True
    return any(fnmatch.fnmatch(path, pattern) for pattern in VENDORED_DIR_PATTERNS)


def detect_language(file_path: str) -> str | None:
    for ext, language in _LANGUAGE_BY_EXTENSION.items():
        if file_path.endswith(ext):
            return language
    return None


def is_candidate_code_file(file_path: str) -> bool:
    if is_excluded_code_path(file_path):
        return False
    return any(file_path.endswith(ext) for ext in CODE_EXTENSIONS)


def _lines(content: str, start: int, end: int) -> str:
    return "\n".join(content.splitlines()[start - 1 : end])


def _chunk_python(content: str, language: str) -> list[CodeChunk]:
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return []

    chunks: list[CodeChunk] = []
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.ClassDef):
            chunks.append(
                CodeChunk(
                    symbol_name=node.name,
                    symbol_type="class",
                    language=language,
                    start_line=node.lineno,
                    end_line=node.end_lineno or node.lineno,
                    content=_lines(content, node.lineno, node.end_lineno or node.lineno),
                    docstring=ast.get_docstring(node),
                )
            )
            for child in ast.iter_child_nodes(node):
                if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                    chunks.append(
                        CodeChunk(
                            symbol_name=f"{node.name}.{child.name}",
                            symbol_type="method",
                            language=language,
                            start_line=child.lineno,
                            end_line=child.end_lineno or child.lineno,
                            content=_lines(content, child.lineno, child.end_lineno or child.lineno),
                            docstring=ast.get_docstring(child),
                        )
                    )
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            chunks.append(
                CodeChunk(
                    symbol_name=node.name,
                    symbol_type="function",
                    language=language,
                    start_line=node.lineno,
                    end_line=node.end_lineno or node.lineno,
                    content=_lines(content, node.lineno, node.end_lineno or node.lineno),
                    docstring=ast.get_docstring(node),
                )
            )
    return chunks


def _ts_language_for(language: str) -> Language:
    if language == "javascript":
        return Language(tsjs.language())
    if language == "typescript":
        return Language(tsts.language_typescript())
    return Language(tsts.language_tsx())


def _node_text(node: Node) -> str:
    return node.text.decode() if node.text is not None else ""


def _function_value_type(declarator: Node) -> Node | None:
    value = declarator.child_by_field_name("value")
    if value is not None and value.type in ("arrow_function", "function_expression"):
        return value
    return None


def _chunk_from_node(
    node: Node, name: str, symbol_type: str, language: str, content: str
) -> CodeChunk:
    start_line = node.start_point[0] + 1
    end_line = node.end_point[0] + 1
    return CodeChunk(
        symbol_name=name,
        symbol_type=symbol_type,
        language=language,
        start_line=start_line,
        end_line=end_line,
        content=_lines(content, start_line, end_line),
    )


def _chunk_treesitter(content: str, language: str) -> list[CodeChunk]:
    ts_language = _ts_language_for(language)
    parser = Parser(ts_language)
    tree = parser.parse(content.encode("utf-8"))

    chunks: list[CodeChunk] = []
    for node in tree.root_node.children:
        if node.type == "function_declaration":
            name_node = node.child_by_field_name("name")
            if name_node is not None:
                chunks.append(
                    _chunk_from_node(node, _node_text(name_node), "function", language, content)
                )
        elif node.type == "class_declaration":
            name_node = node.child_by_field_name("name")
            class_name = _node_text(name_node) if name_node is not None else "anonymous"
            chunks.append(_chunk_from_node(node, class_name, "class", language, content))
            body = node.child_by_field_name("body")
            if body is not None:
                for member in body.children:
                    if member.type == "method_definition":
                        method_name_node = member.child_by_field_name("name")
                        if method_name_node is not None:
                            method_name = f"{class_name}.{_node_text(method_name_node)}"
                            chunks.append(
                                _chunk_from_node(member, method_name, "method", language, content)
                            )
        elif node.type in ("lexical_declaration", "variable_declaration"):
            for declarator in node.children:
                if declarator.type != "variable_declarator":
                    continue
                func_value = _function_value_type(declarator)
                name_node = declarator.child_by_field_name("name")
                if func_value is not None and name_node is not None:
                    name = _node_text(name_node)
                    chunks.append(_chunk_from_node(node, name, "function", language, content))
    return chunks


def _chunk_heuristic(content: str, language: str) -> list[CodeChunk]:
    lines = content.splitlines()
    chunks = []
    for start in range(0, len(lines), HEURISTIC_CHUNK_LINES):
        block = lines[start : start + HEURISTIC_CHUNK_LINES]
        if not any(line.strip() for line in block):
            continue
        chunks.append(
            CodeChunk(
                # Empty string, not None: the (project_id, file_path, symbol_name, start_line)
                # unique constraint can't dedupe NULLs (NULL != NULL), which would duplicate
                # module-level chunks on every re-sync.
                symbol_name="",
                symbol_type="module",
                language=language,
                start_line=start + 1,
                end_line=start + len(block),
                content="\n".join(block),
            )
        )
    return chunks


def chunk_code_file(file_path: str, content: str) -> list[CodeChunk]:
    if not is_candidate_code_file(file_path):
        return []
    if len(content.encode("utf-8")) > MAX_FILE_BYTES:
        return []

    language = detect_language(file_path)
    if language == "python":
        return _chunk_python(content, language)
    if language in ("javascript", "typescript", "tsx"):
        return _chunk_treesitter(content, language)
    return _chunk_heuristic(content, file_path.rsplit(".", 1)[-1])
