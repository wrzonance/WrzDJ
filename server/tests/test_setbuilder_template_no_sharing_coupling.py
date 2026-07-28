"""Cross-module invariant for the SetBuilder template feature (issue #407).

Pins, over every module #407 introduced (model, schemas, service, API
router), that no code path touches ``SetCollaborator`` or sharing/role
logic. Templates are private to their owner and are never shared — this is
broader than (and a superset of) the single-file router check already in
``test_setbuilder_template_api.py``.

Two complementary layers:
  - Static (``test_no_template_module_*``): source-text scan, cheap but
    inherently blind to arbitrarily-aliased references.
  - Behavioral (``test_extract_instantiate_delete_leave_set_collaborators_*``):
    actually runs the lifecycle against a set with a real collaborator row
    and asserts the ``set_collaborators`` table is untouched — catches real
    coupling however it was coded, which no source scan can guarantee.
"""

import ast
import inspect
from types import ModuleType

from app.api import setbuilder_templates as template_api
from app.models import set_template as template_model
from app.models.set import Set, SetCollaborator
from app.schemas import setbuilder_templates as template_schemas
from app.services.setbuilder import set_templates as template_service
from tests import ast_no_sharing_support

_TEMPLATE_MODULES: tuple[ModuleType, ...] = (
    template_model,
    template_schemas,
    template_service,
    template_api,
)


# ---------------------------------------------------------------------------
# Static: source-text scan
# ---------------------------------------------------------------------------


def test_no_template_module_references_sharing_or_collaborator_logic():
    for module in _TEMPLATE_MODULES:
        ast_no_sharing_support.assert_no_sharing_references(module)


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


def test_code_without_docstrings_strips_nested_function_docstrings():
    """Regression guard: the original implementation only stripped the
    module's own top-level docstring, so a nested function docstring that
    merely *mentions* a forbidden token (pure prose, no behavior change)
    would trip the static check. Stripping must recurse into every
    function/class body.
    """
    source = 'def helper():\n    """Do not touch SetCollaborator here."""\n    return 1\n'

    code = ast_no_sharing_support.code_without_docstrings(source)

    assert "SetCollaborator" not in code


def test_code_without_docstrings_still_catches_real_references():
    """Companion guard: stripping docstrings must never eat real code — an
    actual reference to a forbidden token outside a docstring must survive."""
    source = "from app.models.set import SetCollaborator\n"

    code = ast_no_sharing_support.code_without_docstrings(source)

    assert "SetCollaborator" in code


def test_forbidden_tokens_catch_raw_sql_against_set_collaborators_table():
    """Regression guard for the false negative: raw SQL against the
    lowercase ``set_collaborators`` table name (no ``SetCollaborator`` class
    reference at all) must still be caught by the token list."""
    source = 'db.execute(text("SELECT 1 FROM set_collaborators"))\n'

    code = ast_no_sharing_support.code_without_docstrings(source)

    assert any(token in code for token in ast_no_sharing_support.FORBIDDEN_TOKENS)


# ---------------------------------------------------------------------------
# Behavioral: actual DB state
# ---------------------------------------------------------------------------


def _mk_set_with_collaborator(db, owner_id, collaborator_id):
    set_obj = Set(
        owner_id=owner_id,
        name="Collab Set",
        vibe_theme="Peak Time",
        target_duration_sec=3600,
        avg_transition_overlap_sec=12,
        bpm_floor=122,
        bpm_ceiling=128,
        key_strictness=0.5,
    )
    db.add(set_obj)
    db.commit()
    db.refresh(set_obj)

    collaborator = SetCollaborator(
        set_id=set_obj.id, user_id=collaborator_id, role="editor", invited_by=owner_id
    )
    db.add(collaborator)
    db.commit()
    db.refresh(collaborator)
    return set_obj, collaborator


def test_extract_instantiate_delete_leave_set_collaborators_untouched(db, test_user, admin_user):
    """Runtime companion to the static scan above: extract_template,
    instantiate_template, and delete_template must never read or write
    ``set_collaborators`` rows, however the coupling might be coded (raw
    SQL, an aliased join, ...) — something a source-text scan can't rule out.
    """
    src, collaborator = _mk_set_with_collaborator(db, test_user.id, admin_user.id)
    before = (
        collaborator.id,
        collaborator.set_id,
        collaborator.user_id,
        collaborator.role,
        collaborator.invited_by,
    )

    tpl = template_service.extract_template(db, src, test_user.id, "Collab Template")
    new_set = template_service.instantiate_template(db, tpl, test_user.id, None, None)
    template_service.delete_template(db, tpl)

    rows = db.query(SetCollaborator).all()
    assert len(rows) == 1
    after = rows[0]
    assert (after.id, after.set_id, after.user_id, after.role, after.invited_by) == before
    assert db.query(SetCollaborator).filter(SetCollaborator.set_id == new_set.id).count() == 0
