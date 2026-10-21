"""Shared value types for planned-versus-played set history."""

from typing import Literal

SlotOutcome = Literal["played", "skipped", "out_of_order", "substituted"]
