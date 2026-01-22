# SPDX-FileCopyrightText: Contributors to openadr-gui<https://github.com/ElaadNL/openadr-gui>
#
# SPDX-License-Identifier: Apache-2.0

import logging
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from typing import Any

from django.utils import timezone
from openadr3_client.models.common.interval import Interval as VtnInterval
from openadr3_client.models.common.interval_period import IntervalPeriod as VtnIntervalPeriod
from openadr3_client.models.event.event import EventUpdate, ExistingEvent, NewEvent
from openadr3_client.models.event.event_payload import EventPayload

from openadrgui.models.models import Interval, ValidatedEvent
from openadrgui.types import DeploymentSkippedError, RepeatedProgramError

logger = logging.getLogger(__name__)


def check_dp_event_intervals_are_continuous(dp_event: ValidatedEvent) -> None:  # noqa: C901
    """
    Check that the intervals of the DP event are continuous.

    The first interval should start on Monday at midnight, and the intervals should be continuous from start to end.

    Args:
        dp_event: The DP event to check.

    Raises:
        DeployProgramTaskError: If the intervals are not continuous.

    """
    intervals = dp_event.intervals
    if intervals is None:
        msg = "DP event has no intervals"
        raise RepeatedProgramError([msg])

    first_period = intervals[0].interval_period
    if first_period is None:
        msg = "First interval of DP event has no interval period"
        raise RepeatedProgramError([msg])

    start = first_period.start.astimezone(timezone.get_current_timezone())
    if start.isoweekday() != 1 or start.hour != 0 or start.minute != 0 or start.second != 0:
        identifier = dp_event.event_name if dp_event.event_name else dp_event.id
        raise RepeatedProgramError(
            [
                (
                    f"The first interval of the DP event '{identifier}' should start on Monday at midnight.\n"
                    f"It instead starts at {start}."
                )
            ]
        )

    def _get_interval_end(interval: Interval) -> datetime:
        """Calculate interval end time in local timezone."""
        # Perform arithmetic in UTC to avoid DST transition issues, then convert to local time
        period = interval.interval_period
        if period is None:
            msg = "Interval has no interval period"
            raise RepeatedProgramError([msg])
        end_utc = period.start + period.duration
        return end_utc.astimezone(timezone.get_current_timezone())

    def _get_interval_start(interval: Interval) -> datetime:
        """Get interval start time in local timezone."""
        period = interval.interval_period
        if period is None:
            msg = "Interval has no interval period"
            raise RepeatedProgramError([msg])
        return period.start.astimezone(timezone.get_current_timezone())

    def _check_continuity(current_interval: Interval, next_interval: Interval) -> str | None:
        """Check if two consecutive intervals are continuous. Returns error message if not."""
        current_end = _get_interval_end(current_interval)
        next_start = _get_interval_start(next_interval)

        if current_end != next_start:
            identifier = dp_event.event_name if dp_event.event_name else dp_event.id
            return (
                f"DP event '{identifier}' does not have continuous intervals: "
                "all intervals need to be continuous, including different payloads.\n"
                f"One interval ends at {current_end}, "
                f"and the next interval starts at {next_start}."
            )
        return None

    # Collect all discontinuity errors
    errors = [
        error
        for current_interval, next_interval in pairwise(intervals)
        if (error := _check_continuity(current_interval, next_interval)) is not None
    ]

    if errors:
        raise RepeatedProgramError(errors)


def repeat_intervals_for_coming_week(
    vtn_events: tuple[ExistingEvent, ...] | None,
    dp_events: tuple[ValidatedEvent, ...],
    current_datetime: datetime | None = None,
) -> tuple[ExistingEvent | NewEvent, ...]:
    """
    Repeat the intervals for the coming week.

    Args:
        vtn_events: The VTN events to repeat the intervals for.
        dp_events: The DP events to repeat the intervals for.
        current_datetime: The current datetime. If None, the current datetime is used. Mainly used for testing.

    Returns:
        A tuple of VTN events with the intervals repeated for the coming week.
        The NewEvents are for new events that need to be created and contain a dummy id.
        The ExistingEvents are for events that need to be updated.

    """
    current_datetime = (
        datetime.now(tz=timezone.get_current_timezone()) if current_datetime is None else current_datetime
    )
    next_monday_midnight = get_next_monday_midnight(current_datetime)

    updated_vtn_events: tuple[ExistingEvent | NewEvent, ...] = ()
    vtn_events = vtn_events or ()
    for vtn_event in vtn_events:
        if not vtn_event.intervals:
            identifier = vtn_event.event_name if vtn_event.event_name else vtn_event.id
            raise RepeatedProgramError([f"VTN event '{identifier}' has no intervals."])

        end_times: list[datetime] = []
        for interval in vtn_event.intervals:
            period = interval.interval_period
            if period is None:
                identifier = vtn_event.event_name if vtn_event.event_name else vtn_event.id
                raise RepeatedProgramError([f"VTN event '{identifier}' has an interval missing interval_period."])
            end_times.append(period.start.astimezone(timezone.get_current_timezone()) + period.duration)

        vtn_last_date_time = max(end_times)

        identifier = vtn_event.event_name if vtn_event.event_name else vtn_event.id

        if vtn_last_date_time > next_monday_midnight:
            raise DeploymentSkippedError(identifier)

        if vtn_last_date_time != next_monday_midnight:
            raise RepeatedProgramError(
                [
                    (
                        f"VTN event '{identifier}' should last up to and including the next Monday midnight.\n"
                        f"It is instead scheduled until {vtn_last_date_time}."
                    )
                ]
            )

    vtn_event_by_name: dict[str | None, ExistingEvent] = {vtn.event_name: vtn for vtn in vtn_events}

    for dp_event in dp_events:
        matching_vtn_event = vtn_event_by_name.get(dp_event.event_name)

        if matching_vtn_event is None:
            logger.info(
                "No matching VTN event found for DP event '%s'. Event will be created as new.", dp_event.event_name
            )

            last_id = 0
            updated_intervals = _shift_intervals(dp_event, next_monday_midnight, last_id)

            # Create new event data by copying dp_event and updating specific fields
            new_event_data = dp_event.model_copy(
                update={"program_id": "DUMMY_PROGRAM_ID", "intervals": updated_intervals}
            )

            updated_vtn_events += (NewEvent.model_validate(new_event_data),)
        else:
            logger.info("Matching VTN event found for DP event '%s'. Event will be updated.", dp_event.event_name)

            check_dp_event_intervals_are_continuous(dp_event)

            last_id = matching_vtn_event.intervals[-1].id if matching_vtn_event.intervals[-1].id else 0
            updated_intervals = _shift_intervals(dp_event, next_monday_midnight, last_id)

            event_update = EventUpdate(
                intervals=_to_vtn_intervals(updated_intervals),
            )
            updated_vtn_events += (matching_vtn_event.update(event_update),)

    return updated_vtn_events


def _shift_datetime_by_days(dt: datetime, days: int) -> datetime:
    """
    Shift a datetime by a number of days, preserving wall-clock time across DST.

    Example: When shifting from 01:00:00 CET to 02:00:00 CEST, shift to 00:00:00 CEST.

    Args:
        dt: The datetime to shift.
        days: The number of days to shift.

    Returns:
        The datetime shifted by n days with the same wall-clock time, ignoring DST transitions.

    """
    # Convert to local timezone to get the wall-clock time
    local_dt = dt.astimezone(timezone.get_current_timezone())

    # Calculate the target date
    target_date = local_dt.date() + timedelta(days=days)

    # Create a new datetime on the target date with the same wall-clock time in local timezone
    shifted_local = local_dt.replace(year=target_date.year, month=target_date.month, day=target_date.day)

    # Convert back to UTC for storage in the database
    return shifted_local.astimezone(UTC)


def _shift_intervals(
    dp_event: ValidatedEvent, next_monday_midnight: datetime, last_id: int = 0
) -> tuple[Interval, ...]:
    """Repeat intervals for the coming week."""
    check_dp_event_intervals_are_continuous(dp_event)

    intervals = dp_event.intervals
    if intervals is None:
        msg = "DP event has no intervals"
        raise RepeatedProgramError([msg])

    first_period = intervals[0].interval_period
    if first_period is None:
        msg = "First interval of DP event has no interval period"
        raise RepeatedProgramError([msg])

    original_monday = first_period.start.astimezone(timezone.get_current_timezone())
    days_to_shift = (next_monday_midnight.date() - original_monday.date()).days

    return tuple(
        _shift_interval(interval, days_to_shift, last_id + (index + 1)) for index, interval in enumerate(intervals)
    )


def _shift_interval(interval: Interval, days_to_shift: int, new_id: int) -> Interval:
    period = interval.interval_period
    if period is None:
        msg = "DP event interval missing interval_period"
        raise RepeatedProgramError([msg])

    return interval.model_copy(
        update={
            "id": new_id,
            "interval_period": period.model_copy(
                update={"start": _shift_datetime_by_days(period.start, days_to_shift)}
            ),
        }
    )


def _to_vtn_intervals(intervals: tuple[Interval, ...]) -> tuple[VtnInterval[EventPayload[Any]], ...]:
    """Convert DP intervals to VTN interval model for API updates."""
    vtn_intervals: list[VtnInterval[EventPayload[Any]]] = []
    for interval in intervals:
        period = interval.interval_period
        if period is None:
            msg = "Cannot convert interval without interval_period"
            raise RepeatedProgramError([msg])
        interval_id = interval.id
        if interval_id is None:
            msg = "Cannot convert interval without id"
            raise RepeatedProgramError([msg])
        vtn_intervals.append(
            VtnInterval(
                id=interval_id,
                interval_period=VtnIntervalPeriod(
                    start=period.start,
                    duration=period.duration,
                    randomize_start=period.randomize_start,
                ),
                payloads=interval.payloads,
            )
        )
    return tuple(vtn_intervals)


def get_next_monday_midnight(date: datetime) -> datetime:
    """Return the next Monday midnight. Should be in the local timezone."""
    days_until_monday = 8 - date.isoweekday()
    monday = date + timedelta(days=days_until_monday)
    return monday.replace(hour=0, minute=0, second=0, microsecond=0)
