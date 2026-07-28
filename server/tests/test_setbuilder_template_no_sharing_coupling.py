"""Cross-module invariant for the SetBuilder template feature (issue #407).

Pins, over every module #407 introduced (model, schemas, service, API
router), that no code path touches ``SetCollaborator`` or sharing/role
logic. Templates are private to their owner and are never shared — this is
broader than (and a superset of) the single-file router check already in
``test_setbuilder_template_api.py``.
"""

import ast
import inspect
from types import ModuleType

from app.api import setbuilder_templates as template_api
from app.models import set_template as template_model
from app.schemas import setbuilder_templates as template_schemas
from app.services.setbuilder import set_templates as template_service

_FORBIDDEN_TOKENS = (
    "SetCollaborator",
    "share_service",
    "setbuilder_share",
    "share_token",
    ".collaborators",
)

_TEMPLATE_MODULES: tuple[ModuleType, ...] = (
    template_model,
    template_schemas,
    template_service,
    template_api,
)


def _source_without_docstrings(module: ModuleType) -> str:
    """Module source with its docstrings/comments stripped, so prose that
    merely *describes* the no-sharing invariant (as several of these
    modules' own module docstrings do) can't produce a false pass."""
    tree = ast.parse(inspect.getsource(module))
    body_nodes = [node for node in tree.body if not isinstance(node, ast.Expr)]
    return "\n".join(ast.unparse(node) for node in body_nodes)


def test_no_template_module_references_sharing_or_collaborator_logic():
    for module in _TEMPLATE_MODULES:
        code = _source_without_docstrings(module)
        for token in _FORBIDDEN_TOKENS:
            assert token not in code, f"{module.__name__} unexpectedly references {token!r}"


def test_no_template_module_imports_sharing_modules():
    forbidden_imports = {"app.services.setbuilder.share_service", "app.api.setbuilder_share"}
    for module in _TEMPLATE_MODULES:
        tree = ast.parse(inspect.getsource(module))
        imported = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        } | {
            f"{node.module}.{alias.name}" if node.module else alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
            for alias in node.names
        }
        assert not (imported & forbidden_imports), (
            f"{module.__name__} imports a sharing module: {imported & forbidden_imports}"
        )
