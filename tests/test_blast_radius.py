"""Tests for blast radius analysis."""


from app.parsing.tree_sitter_parser import (
    CodeSymbol,
    FileAnalysis,
    detect_language,
    extract_python_symbols,
    find_modified_symbols,
)
from app.services.blast_radius import (
    _classify_impact_risk,
    _detect_security_boundaries,
)


class TestDetectLanguage:
    def test_python(self):
        assert detect_language("app/main.py") == "python"

    def test_javascript(self):
        assert detect_language("src/index.js") == "javascript"

    def test_typescript(self):
        assert detect_language("src/app.tsx") == "typescript"

    def test_unknown(self):
        assert detect_language("readme.md") is None


class TestExtractPythonSymbols:
    def test_extracts_functions(self):
        code = "def hello():\n    pass\n\ndef world(x, y):\n    return x + y"
        analysis = extract_python_symbols(code, "test.py")
        funcs = [s for s in analysis.symbols if s.kind == "function"]
        assert len(funcs) == 2
        assert funcs[0].name == "hello"
        assert funcs[1].name == "world"

    def test_extracts_classes(self):
        code = "class User:\n    name: str\n\nclass Admin(User):\n    role: str"
        analysis = extract_python_symbols(code, "test.py")
        classes = [s for s in analysis.symbols if s.kind == "class"]
        assert len(classes) == 2
        assert classes[0].name == "User"
        assert classes[1].name == "Admin"

    def test_extracts_imports(self):
        code = "import os\nfrom pathlib import Path\nfrom typing import Optional"
        analysis = extract_python_symbols(code, "test.py")
        assert "os" in analysis.imports
        assert "pathlib.Path" in analysis.imports

    def test_handles_syntax_error(self):
        code = "def broken(\n"
        analysis = extract_python_symbols(code, "test.py")
        assert len(analysis.symbols) == 0

    def test_extracts_async_functions(self):
        code = "async def fetch_data(url):\n    pass"
        analysis = extract_python_symbols(code, "test.py")
        funcs = [s for s in analysis.symbols if s.kind == "function"]
        assert len(funcs) == 1
        assert funcs[0].name == "fetch_data"


class TestFindModifiedSymbols:
    def test_finds_overlapping_symbols(self):
        analysis = FileAnalysis(
            file_path="test.py",
            language="python",
            symbols=[
                CodeSymbol(
                    name="authenticate",
                    kind="function",
                    file_path="test.py",
                    start_line=10,
                    end_line=20,
                ),
                CodeSymbol(
                    name="helper",
                    kind="function",
                    file_path="test.py",
                    start_line=25,
                    end_line=30,
                ),
            ],
        )
        modified = find_modified_symbols(analysis, {12, 13, 14})
        assert len(modified) == 1
        assert modified[0].name == "authenticate"

    def test_no_overlap(self):
        analysis = FileAnalysis(
            file_path="test.py",
            language="python",
            symbols=[
                CodeSymbol(
                    name="func",
                    kind="function",
                    file_path="test.py",
                    start_line=10,
                    end_line=20,
                ),
            ],
        )
        modified = find_modified_symbols(analysis, {5, 6})
        assert len(modified) == 0


class TestDetectSecurityBoundaries:
    def test_detects_auth_boundary(self):
        analysis = FileAnalysis(
            file_path="auth.py",
            language="python",
            symbols=[
                CodeSymbol(
                    name="authenticate_user",
                    kind="function",
                    file_path="auth.py",
                    start_line=1,
                    end_line=10,
                ),
            ],
        )
        boundaries = _detect_security_boundaries(analysis)
        assert len(boundaries) == 1
        assert boundaries[0].boundary_type == "auth"

    def test_detects_crypto_boundary(self):
        analysis = FileAnalysis(
            file_path="crypto.py",
            language="python",
            symbols=[
                CodeSymbol(
                    name="encrypt_data",
                    kind="function",
                    file_path="crypto.py",
                    start_line=1,
                    end_line=10,
                ),
            ],
        )
        boundaries = _detect_security_boundaries(analysis)
        assert len(boundaries) == 1
        assert boundaries[0].boundary_type == "crypto"

    def test_no_security_boundary(self):
        analysis = FileAnalysis(
            file_path="utils.py",
            language="python",
            symbols=[
                CodeSymbol(
                    name="format_date",
                    kind="function",
                    file_path="utils.py",
                    start_line=1,
                    end_line=5,
                ),
            ],
        )
        boundaries = _detect_security_boundaries(analysis)
        assert len(boundaries) == 0


class TestClassifyImpactRisk:
    def test_security_symbol_high(self):
        sym = CodeSymbol(
            name="auth", kind="function", file_path="a.py",
            start_line=1, end_line=5,
        )
        assert _classify_impact_risk(sym, is_security=True) == "high"

    def test_class_medium(self):
        sym = CodeSymbol(
            name="User", kind="class", file_path="a.py",
            start_line=1, end_line=10,
        )
        assert _classify_impact_risk(sym, is_security=False) == "medium"

    def test_large_function_medium(self):
        sym = CodeSymbol(
            name="process", kind="function", file_path="a.py",
            start_line=1, end_line=100,
        )
        assert _classify_impact_risk(sym, is_security=False) == "medium"

    def test_small_function_low(self):
        sym = CodeSymbol(
            name="helper", kind="function", file_path="a.py",
            start_line=1, end_line=5,
        )
        assert _classify_impact_risk(sym, is_security=False) == "low"
