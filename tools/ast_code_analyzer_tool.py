"""Noryka Advanced AST Code Analyzer, Dependency Graph & Syntax Verifier Tool."""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

from tools.registry import registry
from tools.path_security import has_unsafe_path_chars


def analyze_python_code(
    file_path: str = "",
    code_snippet: str = "",
    source_code: str = "",
    action: str = "full_audit",
    task_id: str | None = None,
) -> str:
    if source_code and not code_snippet:
        code_snippet = source_code
    """Analyze Python source code via AST: syntax verification, symbol inventory, and dependency graph."""
    source = ""
    target_label = "<inline_snippet>"
    if file_path:
        if has_unsafe_path_chars(file_path):
            return json.dumps({"success": False, "error": "Unsafe characters in file_path"}, ensure_ascii=False)
        p = Path(file_path).expanduser().resolve()
        if not p.is_file():
            return json.dumps({"success": False, "error": f"File not found: {file_path}"}, ensure_ascii=False)
        try:
            source = p.read_text(encoding="utf-8", errors="replace")
            target_label = str(p)
        except OSError as exc:
            return json.dumps({"success": False, "error": str(exc)}, ensure_ascii=False)
    elif code_snippet:
        source = code_snippet
    else:
        return json.dumps({"success": False, "error": "Provide either file_path or code_snippet"}, ensure_ascii=False)

    try:
        tree = ast.parse(source, filename=target_label)
    except SyntaxError as syn:
        return json.dumps({
            "success": False,
            "syntax_valid": False,
            "error": f"SyntaxError at line {syn.lineno}, col {syn.offset}: {syn.msg}",
            "text": (syn.text or "").strip(),
        }, ensure_ascii=False)

    if action == "syntax_check":
        return json.dumps({"success": True, "syntax_valid": True, "lines": len(source.splitlines())}, ensure_ascii=False)

    classes: list[dict[str, Any]] = []
    functions: list[dict[str, Any]] = []
    imports: list[dict[str, Any]] = []

    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            methods = [n.name for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
            classes.append({"name": node.name, "lineno": node.lineno, "methods": methods})
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = [a.arg for a in node.args.args]
            functions.append({"name": node.name, "lineno": node.lineno, "async": isinstance(node, ast.AsyncFunctionDef), "args": args})

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append({"lineno": node.lineno, "module": alias.name, "top_level": node in tree.body})
        elif isinstance(node, ast.ImportFrom):
            mod = "." * node.level + (node.module or "")
            names = [a.name for a in node.names]
            imports.append({"lineno": node.lineno, "module": mod, "names": names, "top_level": node in tree.body})

    return json.dumps({
        "success": True,
        "syntax_valid": True,
        "target": target_label,
        "lines": len(source.splitlines()),
        "classes": classes,
        "functions": functions,
        "imports": imports,
    }, ensure_ascii=False)


AST_ANALYZER_SCHEMA = {
    "name": "ast_code_analyzer",
    "description": (
        "Analyze Python files or code snippets using Python AST: verify syntax after edits, "
        "extract class/method/function signatures with line numbers, and inspect top-level vs lazy imports."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "Path to the Python file to inspect or syntax-check.",
            },
            "code_snippet": {
                "type": "string",
                "description": "Optional inline Python code snippet if checking code before writing.",
            },
            "action": {
                "type": "string",
                "enum": ["full_audit", "syntax_check"],
                "description": "Select 'full_audit' for full AST symbol/import extraction or 'syntax_check' for fast verification.",
            },
        },
        "required": [],
    },
}

registry.register(
    name="ast_code_analyzer",
    toolset="file",
    schema=AST_ANALYZER_SCHEMA,
    handler=lambda args, **kw: analyze_python_code(
        file_path=args.get("file_path", ""),
        code_snippet=args.get("code_snippet", ""),
        action=args.get("action", "full_audit"),
        task_id=kw.get("task_id"),
    ),
)

ast_code_analyzer = analyze_python_code
