"""Validation for untrusted Beatport OAuth token responses."""

from typing import NotRequired, TypedDict


class BeatportTokenResponse(TypedDict):
    access_token: str
    refresh_token: NotRequired[str | None]
    expires_in: NotRequired[int]
    token_type: NotRequired[str]
    scope: NotRequired[str]


def parse_token_response(payload: object) -> BeatportTokenResponse:
    """Validate the OAuth token fields consumed by the provider adapter."""
    if not isinstance(payload, dict):
        raise ValueError("Invalid Beatport token response")

    access_token = payload.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        raise ValueError("Invalid Beatport token response")

    result: BeatportTokenResponse = {"access_token": access_token}
    refresh_token = payload.get("refresh_token")
    if "refresh_token" in payload:
        if refresh_token is not None and not isinstance(refresh_token, str):
            raise ValueError("Invalid Beatport token response")
        result["refresh_token"] = refresh_token

    expires_in = payload.get("expires_in")
    if "expires_in" in payload:
        if not isinstance(expires_in, int) or isinstance(expires_in, bool):
            raise ValueError("Invalid Beatport token response")
        result["expires_in"] = expires_in

    for field in ("token_type", "scope"):
        value = payload.get(field)
        if field in payload:
            if not isinstance(value, str):
                raise ValueError("Invalid Beatport token response")
            result[field] = value

    return result
