from tree_sitter import Language, Parser
import tree_sitter_python
import tree_sitter_javascript
import tree_sitter_typescript

import re
import logging

logger = logging.getLogger(__name__)


def _load_language(module, attr="language"):
    """Load a tree-sitter language, handling both old and new API versions."""
    lang_fn = getattr(module, attr)
    capsule = lang_fn() if callable(lang_fn) else lang_fn
    try:
        return Language(capsule)
    except TypeError:
        # Older tree-sitter: Language() doesn't accept PyCapsule directly
        # The capsule IS the language pointer; use Parser.set_language instead
        return capsule


# Map extensions to tree-sitter languages
LANGUAGES = {
    "py": _load_language(tree_sitter_python, "language"),
    "js": _load_language(tree_sitter_javascript, "language"),
    "ts": _load_language(tree_sitter_typescript, "language_typescript"),
}


def parse_diff_hunks(patch: str) -> list[dict]:
    """
    Parses a unified diff patch string into structured hunks.
    Returns a list of dicts containing the added lines and their line numbers.
    """
    hunks = []
    if not patch:
        return hunks

    lines = patch.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("@@"):
            match = re.search(r"@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@", line)
            if match:
                current_line_num = int(match.group(1))
                hunk_added_lines = []

                i += 1
                while i < len(lines) and not lines[i].startswith("@@"):
                    hunk_line = lines[i]
                    if hunk_line.startswith("+"):
                        hunk_added_lines.append({
                            "line_num": current_line_num,
                            "content": hunk_line[1:]
                        })
                        current_line_num += 1
                    elif hunk_line.startswith("-"):
                        pass  # Deleted lines don't increment new file counter
                    elif hunk_line.startswith("\\"):
                        pass  # No newline at end of file
                    else:
                        current_line_num += 1  # Context line
                    i += 1

                if hunk_added_lines:
                    hunks.append(hunk_added_lines)
                continue
        i += 1

    return hunks


def extract_dependencies(node, file_content: str) -> list[str]:
    """Finds all function calls within an AST node to act as dependency edges."""
    dependencies = []

    def walk_calls(n):
        if n.type == "call":
            for child in n.children:
                if child.type in ["identifier", "attribute"]:
                    dependencies.append(file_content[child.start_byte:child.end_byte])
                    break
        for child in n.children:
            walk_calls(child)

    walk_calls(node)
    return list(set(dependencies))


def get_modified_functions(file_content: str, filename: str, added_lines: list[dict]) -> list[dict]:
    """
    Uses Tree-Sitter to find functions/classes enclosing the modified lines,
    and extracts internal function calls to construct the dependency graph.
    """
    ext = filename.split(".")[-1]
    lang = LANGUAGES.get(ext)

    if not lang:
        logger.debug(f"Unsupported language for AST parsing: {ext}")
        return []

    parser = Parser(lang)
    tree = parser.parse(bytes(file_content, "utf8"))

    modified_nodes = []
    target_node_types = ["function_definition", "class_definition", "method_definition", "arrow_function"]

    def walk_tree(node):
        if node.type in target_node_types:
            start_line = node.start_point[0] + 1
            end_line = node.end_point[0] + 1

            for line_info in added_lines:
                lineno = line_info["line_num"]
                if start_line <= lineno <= end_line:
                    node_name = "unknown"
                    for child in node.children:
                        if child.type == "identifier":
                            node_name = file_content[child.start_byte:child.end_byte]
                            break

                    dependencies = extract_dependencies(node, file_content)

                    modified_nodes.append({
                        "node_type": node.type,
                        "node_name": node_name,
                        "content": file_content[node.start_byte:node.end_byte],
                        "start_line": start_line,
                        "end_line": end_line,
                        "dependencies": dependencies
                    })
                    break

        for child in node.children:
            walk_tree(child)

    walk_tree(tree.root_node)
    return modified_nodes
