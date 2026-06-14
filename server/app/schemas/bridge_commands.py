"""Schemas for bridge admin command endpoints."""

from typing import Any, Literal

from pydantic import BaseModel, Field

BridgeCommandType = Literal[
    "ping",
    "reset_decks",
    "reconnect",
    "restart",
]


class BridgeCommandRequest(BaseModel):
    """Request body for queuing a bridge command."""

    command_type: BridgeCommandType = Field(
        ..., description="The type of command to send to the bridge"
    )


class BridgeCommandResponse(BaseModel):
    """Response after queuing a bridge command."""

    command_id: str = Field(..., description="UUID of the queued command")
    command_type: str = Field(..., description="The command type that was queued")
    payload: dict[str, Any] = Field(default_factory=dict, description="Queued command payload")


class BridgeCommandsPollResponse(BaseModel):
    """Response for bridge polling pending commands."""

    commands: list[BridgeCommandResponse] = Field(
        default_factory=list, description="List of pending commands"
    )
