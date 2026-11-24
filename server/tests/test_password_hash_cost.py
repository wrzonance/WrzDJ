"""Bcrypt cost: production keeps the library default (12); the suite hashes at 4 (#1005).

A cost-12 hash takes ~330 ms, and test fixtures hash on every setup, so a third of the
suite's wall time went to bcrypt. ``tests/__init__.py`` lowers the cost before any app
module is imported; these tests pin both sides of that split.
"""

import bcrypt

from app.services import auth
from tests import PRODUCTION_GENSALT


def test_suite_hashes_at_cost_4():
    assert auth.get_password_hash("pw").startswith("$2b$04$")


def test_import_time_dummy_hash_is_cheap_under_test():
    # Computed when app.services.auth is imported, so this proves the patch lands first.
    assert auth._DUMMY_HASH.startswith("$2b$04$")


def test_production_hashes_at_library_default_cost_12(monkeypatch):
    monkeypatch.setattr(bcrypt, "gensalt", PRODUCTION_GENSALT)

    hashed = auth.get_password_hash("pw")

    assert hashed.startswith("$2b$12$")
    assert auth.verify_password("pw", hashed)
