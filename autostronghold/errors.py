"""Exceptions that carry a message meant for the player.

Every condition that stops the program raises one of these, so the window always
shows *why* it stopped and what to do next, instead of a traceback or a silent exit.
"""
from __future__ import annotations


class StopRun(Exception):
    """The run cannot continue. ``hint`` tells the player what to do about it."""

    def __init__(self, reason: str, hint: str = ""):
        super().__init__(reason)
        self.reason = reason
        self.hint = hint

    def __str__(self) -> str:
        return self.reason + (f"\n处理建议：{self.hint}" if self.hint else "")


class SetupError(StopRun):
    """Device, OCR or GPU could not be prepared."""


class ScreenTimeout(StopRun):
    """An expected game screen did not appear in time."""


class LeftGarrison(StopRun):
    """No Stronghold Protocol screen was seen for too long (disconnect, daily reset, ...)."""


class Stalled(StopRun):
    """The game made no progress for too long."""


class UserStopped(StopRun):
    """The player pressed stop."""
