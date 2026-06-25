import logging
import sys
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

# Look for .env in project root (parent of server/)
_env_file = Path(__file__).resolve().parent.parent.parent.parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_env_file, extra="ignore")

    # Environment
    env: Literal["development", "production"] = "development"

    # Server
    port: int = 8000  # PaaS platforms set PORT env var

    # Database - supports postgres://, postgresql://, or postgresql+psycopg://
    database_url: str = "postgresql+psycopg://wrzdj:wrzdj@localhost:5432/wrzdj"

    @property
    def database_url_sync(self) -> str:
        """Return database URL with psycopg driver for SQLAlchemy."""
        url = self.database_url
        # Convert postgres:// or postgresql:// to postgresql+psycopg://
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql+psycopg://", 1)
        elif url.startswith("postgresql://") and "+psycopg" not in url:
            url = url.replace("postgresql://", "postgresql+psycopg://", 1)
        return url

    # Auth
    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24  # 24 hours

    # Spotify API
    spotify_client_id: str = ""
    spotify_client_secret: str = ""

    # Tidal API (for playlist sync to SC6000)
    tidal_client_id: str = ""
    tidal_client_secret: str = ""
    tidal_redirect_uri: str = ""

    # Beatport API v4 (OAuth2 authorization code flow with PKCE)
    beatport_client_id: str = ""
    beatport_client_secret: str = ""
    beatport_redirect_uri: str = ""
    # Override auth base URL for testing with the public Swagger client_id
    # Default (Partner Portal): https://account.beatport.com
    # Public client: https://api.beatport.com/v4/auth
    beatport_auth_base_url: str = "https://account.beatport.com"

    # StageLinQ Bridge
    bridge_api_key: str = ""

    # Trusted proxy IPs for X-Forwarded-For (comma-separated)
    # Set to nginx/load balancer IPs in production; empty = trust direct connection only
    trusted_proxies: str = "127.0.0.1,::1"

    # CORS - comma-separated origins or "*" for all (dev only)
    # Production: https://app.wrzdj.com
    cors_origins: str = "*"

    # Public URL for QR codes/links (e.g., https://app.wrzdj.com)
    public_url: str = ""

    # Rate limiting (disabled by default in dev, enable in prod)
    rate_limit_enabled: bool | None = None  # None = auto (disabled in dev, enabled in prod)
    login_rate_limit_per_minute: int = 5
    search_rate_limit_per_minute: int = 30
    request_rate_limit_per_minute: int = 10

    # Login lockout (disabled by default in dev, enable in prod)
    lockout_enabled: bool | None = None  # None = auto (disabled in dev, enabled in prod)

    @property
    def is_rate_limit_enabled(self) -> bool:
        """Check if rate limiting is enabled (auto-detect based on env if not set)."""
        if self.rate_limit_enabled is not None:
            return self.rate_limit_enabled
        return self.is_production

    @property
    def is_lockout_enabled(self) -> bool:
        """Check if lockout is enabled (auto-detect based on env if not set)."""
        if self.lockout_enabled is not None:
            return self.lockout_enabled
        return self.is_production

    # Cloudflare Turnstile (CAPTCHA for self-registration)
    turnstile_secret_key: str = ""
    turnstile_site_key: str = ""
    registration_rate_limit_per_minute: int = 3

    # Cloudflare Turnstile session bootstrap for guest pages
    # HMAC-SHA256 key for wrzdj_human cookie signing.
    # Production: REQUIRED — startup fatal if missing.
    # Dev: auto-generates ephemeral key if empty (logs warning).
    # Generate via:
    #   python -c "import secrets, base64; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"  # noqa: E501
    human_cookie_secret: str = ""
    human_cookie_ttl_seconds: int = 3600  # 60 min sliding window

    # DEV-ONLY: bypass the guest human-verification + email-verification gates so
    # headless tests (API/Playwright) can exercise guest flows without minting a
    # wrzdj_human cookie or verifying an email. INERT in production by construction
    # (see `auth_bypass_enabled`), and `validate_settings` refuses to boot if it is
    # ever set with ENV=production. Never enable in any deployed environment.
    dev_auth_bypass: bool = False

    # OAuth token encryption (Fernet key, 44 chars base64)
    # Generate: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key()...)"
    token_encryption_key: str = ""

    # SECURITY (H-C1): MultiFernet key rotation support.
    # Comma-separated Fernet keys; first encrypts, all decrypt. Falls back
    # to token_encryption_key if empty. Rotation procedure in encryption.py.
    token_encryption_keys: str = ""

    # SECURITY (H-C3): legacy plaintext passthrough in EncryptedText.
    # Set to False once all OAuth tokens are encrypted (post-migration).
    # When False, decrypt_value raises DecryptionError on non-Fernet values.
    allow_legacy_plaintext_tokens: bool = True

    # Soundcharts API (song discovery for recommendations)
    soundcharts_app_id: str = ""
    soundcharts_api_key: str = ""
    # Audio-features enrichment (#544) — DARK BY DEFAULT. Keeps the discovery
    # key usable in prod while energy/danceability/valence lookup stays off
    # until a paid tier + caching/redistribution licensing are validated.
    soundcharts_audio_features_enabled: bool = False
    # Related-tracks candidate discovery (#556) — DARK BY DEFAULT. The paid-tier
    # GET /api/v2/song/{uuid}/related endpoint is the only spend on this path;
    # gated off until a paid plan is provisioned so it can never bill by default.
    soundcharts_related_tracks_enabled: bool = False

    # Setbuilder pool import background enrichment (#563).
    pool_enrich_concurrency: int = 6

    # ListenBrainz API (artist discovery for recommendations)
    listenbrainz_user_token: str = ""

    # Retained ONLY for migration 047_admin_ai_oauth (model_hint on the seeded
    # connector). No runtime consumer — do not reference in app code.
    anthropic_model: str = "claude-haiku-4-5-20251001"

    # Cache durations (1 hour for Spotify since popularity changes)
    search_cache_hours: int = 1

    # File uploads
    uploads_dir: str = ""  # defaults to server/uploads/ relative to project root
    max_banner_size_mb: int = 5
    banner_width: int = 1920
    banner_height: int = 480

    # Email (Resend API)
    resend_api_key: str = ""
    email_from_address: str = ""

    @property
    def resolved_uploads_dir(self) -> str:
        """Return uploads directory, defaulting to server/uploads/ if not set."""
        if self.uploads_dir:
            return self.uploads_dir
        from pathlib import Path

        return str(Path(__file__).resolve().parent.parent.parent / "uploads")

    # Bootstrap admin user (created on first startup if no users exist)
    bootstrap_admin_username: str | None = None
    bootstrap_admin_password: str | None = None

    @property
    def effective_human_cookie_secret(self) -> bytes:
        """Return the HMAC key as bytes. In dev, auto-generates an ephemeral
        key on first call and caches it on the settings instance."""
        import base64
        import secrets

        if self.human_cookie_secret:
            # Accept both padded (openssl rand -base64 32 → 44 chars) and
            # unpadded (secrets.token_urlsafe(32) → 43 chars) forms.
            s = self.human_cookie_secret
            pad = "=" * (-len(s) % 4)
            return base64.urlsafe_b64decode(s + pad)

        if self.is_production:
            msg = "HUMAN_COOKIE_SECRET is required in production"
            raise RuntimeError(msg)

        cached = getattr(self, "_dev_human_cookie_secret", None)
        if cached is None:
            cached = secrets.token_bytes(32)
            object.__setattr__(self, "_dev_human_cookie_secret", cached)
            logging.getLogger(__name__).warning(
                "HUMAN_COOKIE_SECRET not set; generated ephemeral key (dev only). "
                "wrzdj_human cookies will not survive a server restart."
            )
        return cached

    @property
    def is_production(self) -> bool:
        return self.env == "production"

    @property
    def auth_bypass_enabled(self) -> bool:
        """True only when the dev bypass is requested AND we are not in production.

        Gating on ``not is_production`` makes the flag INERT in production even if it
        leaks into the environment; `validate_settings` additionally refuses to boot
        if it is set with ENV=production, so it can never silently weaken a deployment.
        """
        return self.dev_auth_bypass and not self.is_production


_FERNET_KEY_HINT = (
    'Generate with: python -c "from cryptography.fernet import Fernet; '
    'print(Fernet.generate_key().decode())"'
)


def _fernet_key_error(key: str) -> str | None:
    """Return an error message if ``key`` is non-empty but not a valid Fernet
    key, else None. Empty input is ignored (presence is checked separately).

    Uses the same ``Fernet`` constructor as ``app.core.encryption`` so the
    accepted shape can never drift from what the runtime actually loads. This
    catches a 64-char ``openssl rand -hex 32`` value at startup instead of at
    the first OAuth token encryption (#504).
    """
    if not key:
        return None
    from cryptography.fernet import Fernet

    try:
        Fernet(key.encode())
    except (ValueError, TypeError):
        return (
            "TOKEN_ENCRYPTION_KEY is not a valid Fernet key (must be 32 url-safe "
            f"base64-encoded bytes = 44 chars; a hex string is rejected). {_FERNET_KEY_HINT}"
        )
    return None


def _fernet_key_list_error(keys: str, setting_name: str) -> str | None:
    """Validate a comma-separated Fernet key list (rotation support).

    Parses ``keys`` exactly as ``app.core.encryption._get_fernet`` does (strip
    whitespace, drop empties) so validation mirrors what the runtime loads, then
    shape-checks every remaining entry. Returns the first error (naming the
    setting + 1-based entry index) or None. Empty/blank input → "no valid keys".
    """
    key_list = [key.strip() for key in keys.split(",") if key.strip()]
    if not key_list:
        return f"{setting_name} contains no valid keys. {_FERNET_KEY_HINT}"

    # For a single key, keep the plain setting name; only a rotation list (>1
    # entry) gets the "entry N" qualifier so operators can spot which key is bad.
    for index, key in enumerate(key_list, start=1):
        if error := _fernet_key_error(key):
            target = setting_name if len(key_list) == 1 else f"{setting_name} entry {index}"
            return error.replace("TOKEN_ENCRYPTION_KEY", target, 1)
    return None


def validate_settings(settings: Settings) -> None:
    """Validate required settings and print helpful error messages."""
    errors = []

    if settings.is_production:
        # nosec B105 - We're checking if the default value is still set (a security check)
        if settings.jwt_secret == "change-me-in-production":  # nosec B105
            errors.append("JWT_SECRET must be set to a secure value in production")
        if settings.cors_origins == "*":
            errors.append(
                "CORS_ORIGINS should not be '*' in production - "
                "set to your frontend domain (e.g., https://app.wrzdj.com)"
            )
        # Mirror app.core.encryption: prefer the rotation list, fall back to the
        # single legacy key. Validate whichever source the runtime will load so a
        # malformed rotation list fails at startup and a valid rotation-only
        # config is not rejected as "missing".
        token_keys = settings.token_encryption_keys or settings.token_encryption_key
        token_keys_name = (
            "TOKEN_ENCRYPTION_KEYS" if settings.token_encryption_keys else "TOKEN_ENCRYPTION_KEY"
        )
        if not token_keys:
            errors.append(
                "TOKEN_ENCRYPTION_KEY or TOKEN_ENCRYPTION_KEYS must be set in production. "
                f"{_FERNET_KEY_HINT}"
            )
        elif fernet_error := _fernet_key_list_error(token_keys, token_keys_name):
            errors.append(fernet_error)
        if not settings.human_cookie_secret:
            errors.append(
                "HUMAN_COOKIE_SECRET must be set in production. "
                'Generate with: python -c "import secrets, base64; '
                'print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"'
            )
        if settings.dev_auth_bypass:
            errors.append(
                "DEV_AUTH_BYPASS must NOT be set in production — it disables the guest "
                "human-verification and email-verification gates. Unset it before deploying."
            )

    if not settings.is_production:
        if settings.jwt_secret == "change-me-in-production":  # nosec B105
            logging.warning(
                "JWT_SECRET is using the default value. Set a unique secret for security."
            )
        if settings.dev_auth_bypass:
            logging.warning(
                "DEV_AUTH_BYPASS is ACTIVE: guest human-verification and email-verification "
                "gates are DISABLED for headless testing. This must never be used in a "
                "deployed environment."
            )

    if not settings.bridge_api_key:
        logging.warning("BRIDGE_API_KEY not set - bridge service will not be able to authenticate")

    if not settings.spotify_client_id or not settings.spotify_client_secret:
        logging.warning(
            "SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET not set - song search will not work"
        )

    if errors:
        for error in errors:
            logging.error("Configuration error: %s", error)
        sys.exit(1)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    validate_settings(settings)
    return settings
