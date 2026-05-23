"""Schemas for the human-verification bootstrap endpoint."""

from pydantic import BaseModel, Field


class VerifyHumanRequest(BaseModel):
    turnstile_token: str = Field(..., min_length=1, max_length=4096)


class VerifyHumanResponse(BaseModel):
    verified: bool
    expires_in: int


class VerifyStatusResponse(BaseModel):
    """Reports whether the caller has a valid wrzdj_human cookie."""

    verified: bool
    expires_in: int = 0  # seconds until cookie expires; 0 when unverified
