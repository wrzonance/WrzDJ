"""Tests for the dependency-free AWS SigV4 signer (``services/llm/sigv4.py``).

The signing-key derivation is pinned against AWS's published test vector, and
a full request signature is pinned to a deterministic fixture so any change to
the canonicalization or signing logic is caught.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.services.llm.sigv4 import _canonicalize_uri, _signing_key, sign_request


def test_signing_key_matches_aws_published_vector():
    # https://docs.aws.amazon.com/general/latest/gr/signature-v4-examples.html
    key = _signing_key("wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY", "20150830", "us-east-1", "iam")
    assert key.hex() == "c4afb1cc5771d871763a393e44b703571b55cc28424d1a5e86da6ed3c154a4b9"


def test_sign_request_is_deterministic_fixture():
    body = b'{"prompt": "hi"}'
    headers = sign_request(
        access_key_id="AKIDEXAMPLE",
        secret_access_key="wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY",
        region="us-east-1",
        host="bedrock-runtime.us-east-1.amazonaws.com",
        canonical_uri="/model/anthropic.claude-3-5-sonnet-20241022-v2:0/invoke",
        body=body,
        now=datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC),
    )
    assert headers["X-Amz-Date"] == "20250101T000000Z"
    assert headers["X-Amz-Content-Sha256"] == (
        "bbab304eadd046fe16c34bcfe99be2e82011d02a07dfb1974414bd13c0e34720"
    )
    assert headers["Authorization"] == (
        "AWS4-HMAC-SHA256 "
        "Credential=AKIDEXAMPLE/20250101/us-east-1/bedrock/aws4_request, "
        "SignedHeaders=content-type;host;x-amz-content-sha256;x-amz-date, "
        "Signature=8941eee088c2d5ff883e65e9aba29f3b653bea15791a13874201fccefe768fa9"
    )


def test_sign_request_includes_security_token_when_present():
    headers = sign_request(
        access_key_id="AKIDEXAMPLE",
        secret_access_key="secret",
        region="us-west-2",
        host="bedrock-runtime.us-west-2.amazonaws.com",
        canonical_uri="/model/meta.llama3-70b-instruct-v1:0/invoke",
        body=b"{}",
        now=datetime(2025, 1, 1, tzinfo=UTC),
        session_token="FwoGZXIvYXdz",
    )
    assert headers["X-Amz-Security-Token"] == "FwoGZXIvYXdz"
    assert "x-amz-security-token" in headers["Authorization"]


def test_signature_changes_when_body_changes():
    common = dict(
        access_key_id="AKIDEXAMPLE",
        secret_access_key="secret",
        region="us-east-1",
        host="bedrock-runtime.us-east-1.amazonaws.com",
        canonical_uri="/model/anthropic.claude-3-5-sonnet-20241022-v2:0/invoke",
        now=datetime(2025, 1, 1, tzinfo=UTC),
    )
    a = sign_request(body=b'{"a":1}', **common)["Authorization"]
    b = sign_request(body=b'{"a":2}', **common)["Authorization"]
    assert a != b


def test_canonicalize_uri_encodes_colon_in_model_id():
    # The ':' in "...-v2:0" must be percent-encoded in the canonical URI.
    encoded = _canonicalize_uri("/model/anthropic.claude-3-5-sonnet-v2:0/invoke")
    assert "%3A0" in encoded
    assert encoded.startswith("/model/")
    assert encoded.endswith("/invoke")
