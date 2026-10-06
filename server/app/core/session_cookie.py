"""Dashboard session cookie: the DJ JWT carried in an HttpOnly cookie (issue #754).

The dashboard used to keep its JWT in localStorage, where any script running on
the dashboard origin could read it for the token's whole 24-hour life. The same
JWT now travels in an HttpOnly cookie, so page scripts cannot read it, while the
bridge-app keeps sending it as a bearer header.

CSRF: a cookie is attached by the browser automatically, so cookie-authenticated
requests must also carry a custom header. Browsers only send custom headers after
a CORS preflight the origin passes, which a cross-site page cannot do. Together
with SameSite=Lax this is the whole CSRF defence; bearer requests need none.
"""

from fastapi import Request, Response

from app.core.config import get_settings

SESSION_COOKIE_NAME = "wrzdj_session"
SESSION_COOKIE_PATH = "/api/"
CSRF_HEADER_NAME = "X-Requested-With"
CSRF_HEADER_VALUE = "WrzDJ"


def set_session_cookie(response: Response, token: str) -> None:
    """Attach the session cookie; lifetime matches the JWT so both expire together."""
    settings = get_settings()
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        httponly=True,
        secure=settings.is_production,
        samesite="lax",
        max_age=settings.jwt_expire_minutes * 60,
        path=SESSION_COOKIE_PATH,
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(key=SESSION_COOKIE_NAME, path=SESSION_COOKIE_PATH)


def has_csrf_header(request: Request) -> bool:
    return request.headers.get(CSRF_HEADER_NAME) == CSRF_HEADER_VALUE


def session_token_from_cookie(request: Request) -> str | None:
    """The cookie token, but only when the CSRF header proves a same-origin script sent it."""
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token or not has_csrf_header(request):
        return None
    return token
