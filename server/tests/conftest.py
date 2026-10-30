"""Pytest configuration and fixtures for WrzDJ tests."""

import os

# A full-length signing key for tests (HS512 wants 64 bytes); the short default caused a
# PyJWT InsecureKeyLengthWarning on every token (~1,450 per run). Set before app imports.
os.environ["JWT_SECRET"] = "wrzdj-tests-only-signing-key-" + "0123456789abcdef" * 3

from collections.abc import Generator
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.db.session as _db_session_module
from app.api import deps as _deps_module
from app.api import sse as _sse_module
from app.api.deps import get_db
from app.core.time import utcnow
from app.main import create_app, no_background_lifespan
from app.models.base import Base
from app.models.event import Event
from app.models.guest import Guest
from app.models.request import Request, RequestStatus
from app.models.user import User
from app.services.auth import create_access_token

DIRECT_SESSIONLOCAL_MODULES = (_sse_module,)
DEPENDENCY_OVERRIDE_SESSIONLOCAL_MODULES = (_deps_module,)

# Use SQLite in-memory for tests (fast, isolated)
SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

TEST_USER_PASSWORD = "testpassword123"
ADMIN_USER_PASSWORD = "adminpassword123"
PENDING_USER_PASSWORD = "pendingpassword123"

TEST_USER_PASSWORD_HASH = "$2b$04$BIUR.p93nOe8nGJXBjtYhu6QLsv7BHn22sAfR/Tpt6xMdl9tEf4tS"
ADMIN_USER_PASSWORD_HASH = "$2b$04$LaJfWm6YwkBoEVVFvnxu7unVKG7HRGM9hiSvk448HhWZK.hPijb7a"
PENDING_USER_PASSWORD_HASH = "$2b$04$BnvACwtrVGvZhu5TzYdOR.tpGyY6OQ4p5oILNEgHPmvOGWotCWWYu"


def _auth_headers_for_user(user: User) -> dict[str, str]:
    token = create_access_token(data={"sub": user.username, "tv": user.token_version})
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="session", autouse=True)
def _database_schema() -> Generator[None, None, None]:
    """Create the in-memory SQLite schema once per pytest process."""
    Base.metadata.create_all(bind=engine)
    try:
        yield
    finally:
        Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def db(monkeypatch: pytest.MonkeyPatch, _database_schema: None) -> Generator[Session, None, None]:
    """Run each test inside an externally managed transaction.

    Application code may call Session.commit(); SQLAlchemy keeps those commits
    inside a SAVEPOINT while this fixture rolls back the outer transaction.
    """
    connection = engine.connect()
    # SQLite's legacy transaction control does not always emit BEGIN before the
    # first SAVEPOINT, so start the driver transaction explicitly.
    connection.exec_driver_sql("BEGIN")
    transaction = connection.get_transaction()
    assert transaction is not None
    TestSessionLocal = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=connection,
        join_transaction_mode="create_savepoint",
    )
    AppSessionLocal = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=connection,
        # Detached app sessions can overlap with the fixture session; avoid
        # competing SAVEPOINT ownership while keeping their writes rollback-bound.
        join_transaction_mode="rollback_only",
    )
    monkeypatch.setattr(_db_session_module, "SessionLocal", AppSessionLocal)
    for module in DIRECT_SESSIONLOCAL_MODULES:
        monkeypatch.setattr(module, "SessionLocal", AppSessionLocal, raising=False)

    session = TestSessionLocal()
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture(scope="session")
def test_app():
    """FastAPI app instance for tests; lifespan runs without production loops."""
    return create_app(lifespan_context=no_background_lifespan)


@pytest.fixture(scope="function")
def client(db: Session, test_app) -> Generator[TestClient, None, None]:
    """Create a test client with database override."""

    def override_get_db():
        try:
            yield db
        finally:
            pass  # Don't close the session here, let the db fixture handle it

    test_app.dependency_overrides[get_db] = override_get_db
    with TestClient(test_app) as c:
        yield c
    test_app.dependency_overrides.clear()


@pytest.fixture
def test_user(db: Session) -> User:
    """Create a test user with DJ role."""
    user = User(
        username="testuser",
        password_hash=TEST_USER_PASSWORD_HASH,
        role="dj",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def admin_user(db: Session) -> User:
    """Create an admin test user."""
    user = User(
        username="adminuser",
        password_hash=ADMIN_USER_PASSWORD_HASH,
        role="admin",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def admin_headers(admin_user: User) -> dict[str, str]:
    """Authentication headers for the admin user without exercising login."""
    return _auth_headers_for_user(admin_user)


@pytest.fixture
def pending_user(db: Session) -> User:
    """Create a pending test user."""
    user = User(
        username="pendinguser",
        password_hash=PENDING_USER_PASSWORD_HASH,
        role="pending",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def pending_headers(pending_user: User) -> dict[str, str]:
    """Authentication headers for the pending user without exercising login."""
    return _auth_headers_for_user(pending_user)


@pytest.fixture
def auth_headers(test_user: User) -> dict[str, str]:
    """Authentication headers for the DJ user without exercising login."""
    return _auth_headers_for_user(test_user)


@pytest.fixture
def test_event(db: Session, test_user: User) -> Event:
    """Create a test event with distinct collection and join codes."""
    event = Event(
        code="TEST01",
        join_code="UG4BHD",
        name="Test Event",
        created_by_user_id=test_user.id,
        expires_at=utcnow() + timedelta(hours=6),
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


@pytest.fixture
def collection_requests(db: Session, test_event: Event) -> list[Request]:
    """Creates 3 collection-submitted NEW requests with vote counts 5, 2, 0."""
    now = utcnow()
    rows = []
    for i, votes in enumerate([5, 2, 0]):
        r = Request(
            event_id=test_event.id,
            song_title=f"Song {i}",
            artist=f"Artist {i}",
            source="spotify",
            status=RequestStatus.NEW.value,
            vote_count=votes,
            dedupe_key=f"dk_{i}",
            submitted_during_collection=True,
            created_at=now,
        )
        db.add(r)
        rows.append(r)
    db.commit()
    for r in rows:
        db.refresh(r)
    return rows


@pytest.fixture
def test_guest(db: Session) -> Guest:
    """Create a test guest with known token and fingerprint."""
    guest = Guest(
        token="a" * 64,
        fingerprint_hash="fp_test_hash_123",
        fingerprint_components='{"screen":"1170x2532","timezone":"America/Chicago"}',
        user_agent=(
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) "
            "Version/17.4 Mobile/15E148 Safari/604.1"
        ),
    )
    db.add(guest)
    db.commit()
    db.refresh(guest)
    return guest


@pytest.fixture
def test_request(db: Session, test_event: Event) -> Request:
    """Create a test song request."""
    request = Request(
        event_id=test_event.id,
        song_title="Test Song",
        artist="Test Artist",
        source="manual",
        status=RequestStatus.NEW.value,
        dedupe_key="test_dedupe_key_12345678",
    )
    db.add(request)
    db.commit()
    db.refresh(request)
    return request


@pytest.fixture(autouse=True)
def _no_network_enrichment(request, monkeypatch):
    """Request-time enrichment is a no-op in tests unless marked ``real_enrichment``.

    Submitting a request schedules ``_enrich_with_fresh_session``, which opens its own
    ``SessionLocal()`` (the configured database, not this suite's SQLite) and calls the
    metadata providers. Left real, every submit test waited 2-9 s in TestClient teardown.
    Tests that patch ``enrich_request_metadata`` themselves still win (their patch is later).
    """
    if request.node.get_closest_marker("real_enrichment"):
        return
    monkeypatch.setattr(
        "app.services.sync.orchestrator.enrich_request_metadata", lambda db, request_id: None
    )


@pytest.fixture(autouse=True)
def _block_outbound_http(request, monkeypatch):
    """Fail any test whose code reaches the real network; fake the provider instead.

    Calls matching a route registered on ``fake_http`` get that fake response (the app's own
    request and parsing code still run). Any other call raises the library's own connection
    error at once, so the app takes its real "provider unreachable" path with no timeout
    wait; provider code often swallows that as best-effort, so the attempt is also recorded
    and fails the test at teardown. TestClient uses its own in-process transport, so it is
    unaffected. Opt out with ``allow_network``.
    """
    from tests.fakes import FakeHttp

    http = FakeHttp()
    if request.node.get_closest_marker("allow_network"):
        yield http
        return

    import httpx
    import requests
    import requests.adapters

    attempts: list[str] = []
    message = "outbound HTTP blocked in tests: {}"

    def _httpx_response(route, req):
        if route.raises == "timeout":
            raise httpx.ReadTimeout(f"fake timeout: {req.url}", request=req)
        if route.raises:
            raise httpx.ConnectError(f"fake connect error: {req.url}", request=req)
        content, headers = route.payload(req.content)
        return httpx.Response(route.status, content=content, headers=headers, request=req)

    def _httpx_send(self, req):
        route = http.find(req.method, str(req.url))
        if route is not None:
            return _httpx_response(route, req)
        attempts.append(str(req.url))
        raise httpx.ConnectError(message.format(req.url), request=req)

    async def _httpx_send_async(self, req):
        route = http.find(req.method, str(req.url))
        if route is not None:
            await req.aread()
            return _httpx_response(route, req)
        attempts.append(str(req.url))
        raise httpx.ConnectError(message.format(req.url), request=req)

    def _requests_send(self, req, *args, **kwargs):
        route = http.find(req.method, req.url)
        if route is None:
            attempts.append(str(req.url))
            raise requests.exceptions.ConnectionError(message.format(req.url), request=req)
        if route.raises == "timeout":
            raise requests.exceptions.ReadTimeout(f"fake timeout: {req.url}", request=req)
        if route.raises:
            raise requests.exceptions.ConnectionError(f"fake connect error: {req.url}", request=req)
        body = req.body.encode() if isinstance(req.body, str) else (req.body or b"")
        content, headers = route.payload(body)
        resp = requests.Response()
        resp.status_code = route.status
        resp._content = content
        resp.headers = requests.structures.CaseInsensitiveDict(headers)
        resp.url = req.url
        resp.request = req
        resp.encoding = "utf-8"
        return resp

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", _httpx_send)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", _httpx_send_async)
    monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", _requests_send)
    yield http
    if attempts:
        pytest.fail(f"test made {len(attempts)} outbound HTTP call(s): {attempts[:3]}")


@pytest.fixture
def fake_http(_block_outbound_http):
    """Register fake provider responses for this test (see tests/fakes/__init__.py)."""
    return _block_outbound_http


@pytest.fixture
def tidal_connected(fake_http):
    """A Tidal account whose stored tokens are valid; no network."""
    from tests.fakes.providers import tidal_connected as register

    register(fake_http)
    return fake_http


@pytest.fixture
def tidal_down(fake_http):
    """Tidal is unreachable on purpose: the app's "Tidal unavailable" path, no network."""
    from tests.fakes.providers import tidal_down as register

    register(fake_http)
    return fake_http


@pytest.fixture
def beatport_up(fake_http):
    from tests.fakes.providers import beatport_up as register

    register(fake_http)
    return fake_http


@pytest.fixture
def listenbrainz_popular(fake_http):
    from tests.fakes.providers import listenbrainz_popular as register

    register(fake_http)
    return fake_http


@pytest.fixture
def musicbrainz_no_match(fake_http):
    from tests.fakes.providers import musicbrainz_no_match as register

    register(fake_http)
    return fake_http
