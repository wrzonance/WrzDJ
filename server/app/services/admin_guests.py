"""Admin-side guest management: listing, editing, and deleting guest identities (#862).

Spec: docs/superpowers/specs/2026-10-21-admin-guest-management-design.md
"""


def mask_email(email: str) -> str:
    """`alice@example.com` → `a***@example.com`.

    The plaintext is encrypted at rest; the admin page only ever needs enough to
    recognise the address.
    """
    local, _, domain = email.partition("@")
    first = local[:1]
    return f"{first}***@{domain}"
