"""Rate limiting middleware using slowapi.

Identity is `guest_id` only (cookie + ThumbmarkJS reconciliation in
app/services/guest_identity.py). The slowapi rate-limiter is the lone
IP consumer in this codebase — IP is read ephemerally per request as
the rate-limit bucket key and is never stored, never logged.

To restore IP-based identity, see docs/RECOVERY-IP-IDENTITY.md.
"""

from __future__ import annotations

import ipaddress
from functools import lru_cache
from typing import TYPE_CHECKING

from fastapi import Request, Response
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.responses import JSONResponse

from app.core.config import get_settings

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


@lru_cache(maxsize=1)
def _get_trusted_proxies() -> tuple[
    frozenset[str],
    tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...],
]:
    """Return trusted proxy IPs and CIDR networks from settings (cached)."""
    settings = get_settings()
    exact = set()
    networks = []
    for entry in settings.trusted_proxies.split(","):
        entry = entry.strip()
        if not entry:
            continue
        if "/" in entry:
            networks.append(ipaddress.ip_network(entry, strict=False))
        else:
            exact.add(entry)
    return frozenset(exact), tuple(networks)


def _is_trusted_proxy(ip: str) -> bool:
    """Check if an IP is in the trusted proxies list (exact match or CIDR)."""
    exact, networks = _get_trusted_proxies()
    if ip in exact:
        return True
    if networks:
        try:
            addr = ipaddress.ip_address(ip)
            return any(addr in net for net in networks)
        except ValueError:
            return False
    return False


def get_client_ip(request: Request) -> str:
    """EPHEMERAL ONLY — never store or log this value.

    Used solely as the slowapi rate-limit bucket key. To restore IP-based
    identity, see docs/RECOVERY-IP-IDENTITY.md.

    Priority:
    1. X-Real-IP (nginx overwrites this with the actual connecting client IP)
    2. X-Forwarded-For first entry (only if direct connection is a trusted proxy)
    3. Direct connection IP
    """
    direct_ip = get_remote_address(request)

    real_ip = request.headers.get("X-Real-IP")
    if real_ip and _is_trusted_proxy(direct_ip):
        return real_ip.strip()

    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for and _is_trusted_proxy(direct_ip):
        return forwarded_for.split(",")[0].strip()

    return direct_ip


# Create limiter instance with IP-based key function (ephemeral, in-memory).
limiter = Limiter(key_func=get_client_ip, enabled=get_settings().is_rate_limit_enabled)


# Reserved guest token for the DEV_AUTH_BYPASS dev guest. It is honored ONLY when
# the bypass is active; a request presenting this token is rejected outright when the
# bypass is off, so even if the dev guest row leaks into another DB (staging->prod
# promotion, backup restore, dev dump) it can NEVER be a production backdoor. The dev
# guest is also deliberately NOT email-verified, so it could not pass require_email_
# verified via the normal path even if it were somehow resolved (defense in depth).
_DEV_BYPASS_GUEST_TOKEN = "dev-auth-bypass-guest"  # nosec B105 - reserved token, not a secret


def get_guest_id(request: Request, db: Session) -> int | None:
    """Read the wrzdj_guest cookie and return the Guest.id, or None.

    Under DEV_AUTH_BYPASS (dev only) a cookieless request resolves to a stable dev
    guest, so headless tests need no guest cookie on ANY guest endpoint (this is the
    single identity chokepoint the gates and the inline-resolving routes share).
    Inert in production — see Settings.auth_bypass_enabled.
    """
    from app.core.config import get_settings
    from app.models.guest import Guest

    bypass = get_settings().auth_bypass_enabled

    token = request.cookies.get("wrzdj_guest")
    if token:
        # Never resolve the reserved dev token unless the bypass is active — a leaked
        # dev guest row must not become a production backdoor.
        if token == _DEV_BYPASS_GUEST_TOKEN and not bypass:
            return None
        guest = db.query(Guest).filter(Guest.token == token).first()
        if guest:
            return guest.id

    if bypass:
        return _dev_bypass_guest_id(db)
    return None


def _dev_bypass_guest_id(db: Session) -> int:
    """Get-or-create the stable DEV_AUTH_BYPASS guest. DEV-ONLY (callers guard).

    The row is intentionally minimal and NOT email-verified: the email gate is opened
    by the explicit require_email_verified bypass, so this row never needs — and must
    not carry — a pre-verified identity that could be abused if it leaked into prod.
    """
    from sqlalchemy.exc import IntegrityError

    from app.core.time import utcnow
    from app.models.guest import Guest

    guest = db.query(Guest).filter(Guest.token == _DEV_BYPASS_GUEST_TOKEN).first()
    if guest:
        return guest.id
    guest = Guest(token=_DEV_BYPASS_GUEST_TOKEN, created_at=utcnow(), last_seen_at=utcnow())
    db.add(guest)
    try:
        db.commit()
    except IntegrityError:  # concurrent create — re-read the winner
        db.rollback()
        return db.query(Guest).filter(Guest.token == _DEV_BYPASS_GUEST_TOKEN).first().id
    db.refresh(guest)
    return guest.id


def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> Response:
    """Custom handler for rate limit exceeded errors."""
    retry_after = 60  # Default to 60 seconds

    return JSONResponse(
        status_code=429,
        content={
            "detail": "Rate limit exceeded. Please try again later.",
            "retry_after": retry_after,
        },
        headers={"Retry-After": str(retry_after)},
    )
