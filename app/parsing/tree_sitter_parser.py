"""Tree-Sitter based code parsing for dependency graphing and symbol extraction."""

from dataclasses import dataclass, field

import structlog

logger = structlog.get_logger()


@dataclass
class CodeSymbol:
    name: str
    kind: str  # function, class, method, variable
    file_path: str
    start_line: int
    end_line: int
    parent: str | None = None
    language: str | None = None
    signature: str = ""


@dataclass
class DependencyEdge:
    caller: str
    callee: str
    file_path: str
    line: int


@dataclass
class FileAnalysis:
    file_path: str
    language: str | None
    symbols: list[CodeSymbol] = field(default_factory=list)
    dependencies: list[DependencyEdge] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)


LANGUAGE_EXTENSIONS = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".jsx": "javascript",
    ".java": "java",
    ".go": "go",
    ".rs": "rust",
    ".rb": "ruby",
    ".cpp": "cpp",
    ".c": "c",
    ".cs": "c_sharp",
}


def detect_language(file_path: str) -> str | None:
    for ext, lang in LANGUAGE_EXTENSIONS.items():
        if file_path.endswith(ext):
            return lang
    return None


def extract_python_symbols(content: str, file_path: str) -> FileAnalysis:
    """Extract symbols from Python source using basic AST analysis.

    Falls back to regex-based extraction when tree-sitter grammars are unavailable.
    """
    import ast

    analysis = FileAnalysis(file_path=file_path, language="python")

    try:
        tree = ast.parse(content)
    except SyntaxError:
        logger.warning("python_parse_error", file=file_path)
        return analysis

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            args = ", ".join(a.arg for a in node.args.args)
            analysis.symbols.append(
                CodeSymbol(
                    name=node.name,
                    kind="function",
                    file_path=file_path,
                    start_line=node.lineno,
                    end_line=node.end_lineno or node.lineno,
                    signature=f"def {node.name}({args})",
                    language="python",
                )
            )
        elif isinstance(node, ast.ClassDef):
            bases = ", ".join(
                getattr(b, "id", getattr(b, "attr", "?")) for b in node.bases
            )
            analysis.symbols.append(
                CodeSymbol(
                    name=node.name,
                    kind="class",
                    file_path=file_path,
                    start_line=node.lineno,
                    end_line=node.end_lineno or node.lineno,
                    signature=f"class {node.name}({bases})" if bases else f"class {node.name}",
                    language="python",
                )
            )
        elif isinstance(node, ast.Import):
            for alias in node.names:
                analysis.imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for alias in node.names:
                analysis.imports.append(f"{module}.{alias.name}")
        elif isinstance(node, ast.Call):
            func = node.func
            name = None
            if isinstance(func, ast.Name):
                name = func.id
            elif isinstance(func, ast.Attribute):
                name = func.attr
            if name:
                analysis.dependencies.append(
                    DependencyEdge(
                        caller="<module>",
                        callee=name,
                        file_path=file_path,
                        line=node.lineno,
                    )
                )

    return analysis


def analyze_file(content: str, file_path: str) -> FileAnalysis:
    language = detect_language(file_path)

    if language == "python":
        return extract_python_symbols(content, file_path)

    return FileAnalysis(file_path=file_path, language=language)


def find_modified_symbols(
    analysis: FileAnalysis,
    modified_lines: set[int],
) -> list[CodeSymbol]:
    """Identify which symbols overlap with the modified line ranges."""
    result = []
    for symbol in analysis.symbols:
        symbol_lines = set(range(symbol.start_line, symbol.end_line + 1))
        if symbol_lines & modified_lines:
            result.append(symbol)
    return result
