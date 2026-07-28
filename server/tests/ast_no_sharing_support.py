"""Shared static-analysis helpers for the #407 "templates never touch
sharing/collaborator logic" invariant.

Used by both ``test_setbuilder_template_no_sharing_coupling.py`` (scans all
four template modules) and ``test_setbuilder_template_api.py`` (scans the
router alone). Kept as a single source of truth so a toughened token list or
a docstring-stripping fix lands for every caller at once, instead of
drifting between hand-copied implementations.

Not a test module itself (no ``test_`` prefix) — pytest never collects it.
"""

import ast
import inspect
from types import ModuleType

# Case-sensitive substrings that must never appear in a template module's
# source (docstrings/comments excluded). Includes both the ORM class name
# (SetCollaborator) and the literal table name (set_collaborators) so raw
# SQL against the table -- which never mentions the class -- is caught too.
FORBIDDEN_TOKENS: tuple[str, ...] = (
    "SetCollaborator",
    "set_collaborators",
    "share_service",
    "setbuilder_share",
    "share_token",
    ".collaborators",
)

_DOCSTRING_HOLDERS = (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


def assert_no_sharing_references(module: ModuleType) -> None:
    """Fail if ``module``'s source (docstrings/comments stripped) mentions
    any sharing/collaborator token."""
    code = source_without_docstrings(module)
    for token in FORBIDDEN_TOKENS:
        assert token not in code, f"{module.__name__} unexpectedly references {token!r}"


def source_without_docstrings(module: ModuleType) -> str:
    """``module``'s source with every docstring stripped."""
    return code_without_docstrings(inspect.getsource(module))


def code_without_docstrings(source: str) -> str:
    """Source text with every docstring -- module-, class-, and
    function-level, not just the module's own top-level one -- stripped, so
    prose describing the no-sharing invariant can never produce a false
    pass, and a nested function's unrelated docstring can never produce a
    false failure.
    """
    tree = ast.parse(source)
    _strip_docstrings(tree)
    return ast.unparse(tree)


def _strip_docstrings(node: ast.AST) -> None:
    """Recursively drop the leading string-literal Expr (docstring) from
    every Module/FunctionDef/AsyncFunctionDef/ClassDef body, in place."""
    if isinstance(node, _DOCSTRING_HOLDERS) and _is_docstring_expr(_first_stmt(node)):
        node.body = node.body[1:]
    for child in ast.iter_child_nodes(node):
        _strip_docstrings(child)


def _first_stmt(node: ast.AST) -> ast.stmt | None:
    return node.body[0] if node.body else None


def _is_docstring_expr(node: ast.stmt | None) -> bool:
    return (
        isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    )
