"""Validation rules shared by Apple Music account and catalog boundaries."""

import re

_STOREFRONT_RE = re.compile(r"^[a-z]{2}$")


def is_valid_storefront(storefront: str) -> bool:
    """Return whether a storefront is exactly two lowercase ASCII letters."""
    return _STOREFRONT_RE.fullmatch(storefront) is not None
