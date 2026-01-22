# SPDX-FileCopyrightText: Contributors to openadr-gui<https://github.com/ElaadNL/openadr-gui>
#
# SPDX-License-Identifier: Apache-2.0

"""
Central typing aliases / protocols.

These exist to keep "boundary" types (API models vs GUI models) readable
without repeating unions/casts across the codebase.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, Self

from django.http import HttpRequest
from openadr3_client.models.common.interval import Interval as VtnInterval
from openadr3_client.models.event.event_payload import EventPayload

from openadrgui.models.models import Interval as GuiInterval

if TYPE_CHECKING:
    from datetime import datetime, timedelta


class IntervalPeriodLike(Protocol):
    """An interface for interval periods."""

    start: datetime
    duration: timedelta
    randomize_start: timedelta | None


# Use when you only need the *shape* of an interval (duck typing).
# Prefer this for helpers/utilities that should accept any interval-like object
# (including adapters/mocks), without coupling to our concrete models.
class IntervalLike(Protocol):
    """An interface for intervals."""

    id: int | None
    interval_period: IntervalPeriodLike | None
    payloads: tuple[EventPayload[Any], ...]


# Use when you explicitly mean “one of our two concrete interval models”.
# Prefer this at GUI↔VTN boundaries where the only real inputs are these models.
# (Note: mypy can be picky about Protocols inside `tuple[...]` due to invariance.)
type IntervalModel = VtnInterval[EventPayload[Any]] | GuiInterval


class CopyableInterval(Protocol):
    """An interface for IntervalLikes that can be copied."""

    payloads: tuple[EventPayload[Any], ...]

    def model_copy(self, *, update: dict[str, Any]) -> Self:
        """Copy the interval with the given update."""
        ...


class HtmxHttpRequest(HttpRequest):
    """Htmx request object."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        """Initialize the HtmxHttpRequest object."""
        super().__init__(*args, **kwargs)
        self.htmx: bool = False


class RepeatedProgramError(Exception):
    """Error deploying program task."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("Error deploying program task: " + ", ".join(errors))


class DeploymentSkippedError(Exception):
    """Deployment skipped: VTN program already contains intervals for the coming week."""

    def __init__(self, event_id: str) -> None:
        super().__init__(f"VTN event '{event_id}' already has intervals for the coming week.")


class BLClientLockError(RuntimeError):
    """Raised when BL client operations are attempted without an active lock."""
