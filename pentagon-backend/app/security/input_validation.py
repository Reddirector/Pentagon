"""Shared validation for user text fields."""

from __future__ import annotations


def reject_control_characters(value: str) -> str:
    """Reject C0/C1 controls except ordinary tabs and line breaks."""
    for char in value:
        codepoint = ord(char)
        if (codepoint < 32 and char not in "\t\n\r") or 0x7F <= codepoint <= 0x9F:
            raise ValueError("Text contains a control character.")
    return value
