"""Minimal AWS Signature Version 4 (SigV4) signing — dependency-free.

We deliberately avoid ``boto3``/``botocore`` (per the CLAUDE.md CVE/dependency
rule) and implement just enough of SigV4 to sign a single ``POST`` request to
the Bedrock runtime ``InvokeModel`` endpoint over the existing ``httpx`` client.

Reference: https://docs.aws.amazon.com/general/latest/gr/sigv4-create-canonical-request.html

This module is pure stdlib (``hashlib`` / ``hmac`` / ``datetime`` / ``urllib``)
so it adds no new third-party surface area. It only signs the request shape the
Bedrock adapter produces — it is not a general-purpose AWS signer.
"""

from __future__ import annotations

import hashlib
import hmac
from datetime import datetime
from urllib.parse import quote

_ALGORITHM = "AWS4-HMAC-SHA256"
_SERVICE = "bedrock"


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _hmac_sha256(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def _signing_key(secret_key: str, date_stamp: str, region: str, service: str) -> bytes:
    """Derive the SigV4 signing key (the chained-HMAC ``kSigning``)."""
    k_date = _hmac_sha256(("AWS4" + secret_key).encode("utf-8"), date_stamp)
    k_region = _hmac_sha256(k_date, region)
    k_service = _hmac_sha256(k_region, service)
    return _hmac_sha256(k_service, "aws4_request")


def sign_request(
    *,
    access_key_id: str,
    secret_access_key: str,
    region: str,
    host: str,
    canonical_uri: str,
    body: bytes,
    now: datetime,
    service: str = _SERVICE,
    content_type: str = "application/json",
    session_token: str | None = None,
) -> dict[str, str]:
    """Return the headers required to authenticate a signed ``POST`` request.

    ``canonical_uri`` is the request path (already percent-encoded as needed,
    e.g. ``/model/anthropic.claude-3-5-sonnet-20241022-v2:0/invoke``). The
    caller supplies the request ``body`` bytes; we hash and sign them.

    The returned dict includes ``Authorization``, ``X-Amz-Date``,
    ``X-Amz-Content-Sha256`` (and ``X-Amz-Security-Token`` when a session token
    is provided). Callers merge these with ``Content-Type``/``Accept``.
    """
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = now.strftime("%Y%m%d")

    payload_hash = _sha256_hex(body)

    # --- Canonical request -------------------------------------------------
    # Headers must be sorted by lowercased name and trimmed. We sign the
    # minimal set: host, content-type, x-amz-content-sha256, x-amz-date
    # (+ x-amz-security-token when present).
    canonical_headers_map = {
        "content-type": content_type,
        "host": host,
        "x-amz-content-sha256": payload_hash,
        "x-amz-date": amz_date,
    }
    if session_token:
        canonical_headers_map["x-amz-security-token"] = session_token

    signed_headers = ";".join(sorted(canonical_headers_map))
    canonical_headers = "".join(
        f"{name}:{canonical_headers_map[name]}\n" for name in sorted(canonical_headers_map)
    )

    canonical_request = "\n".join(
        [
            "POST",
            _canonicalize_uri(canonical_uri),
            "",  # no query string
            canonical_headers,
            signed_headers,
            payload_hash,
        ]
    )

    # --- String to sign ----------------------------------------------------
    credential_scope = f"{date_stamp}/{region}/{service}/aws4_request"
    string_to_sign = "\n".join(
        [
            _ALGORITHM,
            amz_date,
            credential_scope,
            _sha256_hex(canonical_request.encode("utf-8")),
        ]
    )

    # --- Signature ---------------------------------------------------------
    signing_key = _signing_key(secret_access_key, date_stamp, region, service)
    signature = hmac.new(signing_key, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()

    authorization = (
        f"{_ALGORITHM} "
        f"Credential={access_key_id}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, "
        f"Signature={signature}"
    )

    headers = {
        "Authorization": authorization,
        "X-Amz-Date": amz_date,
        "X-Amz-Content-Sha256": payload_hash,
    }
    if session_token:
        headers["X-Amz-Security-Token"] = session_token
    return headers


def _canonicalize_uri(path: str) -> str:
    """Percent-encode each path segment per SigV4 rules (keeps ``/`` separators).

    Bedrock model ids contain characters like ``:`` (e.g. ``...-v2:0``) which
    must be encoded in the canonical URI even though they are valid in the URL.
    """
    if not path:
        return "/"
    segments = path.split("/")
    # quote() leaves unreserved chars + nothing in safe=""; encode ':' too.
    encoded = [quote(seg, safe="") for seg in segments]
    return "/".join(encoded)
