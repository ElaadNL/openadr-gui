# SPDX-FileCopyrightText: Contributors to openadr-gui<https://github.com/ElaadNL/openadr-gui>
#
# SPDX-License-Identifier: Apache-2.0

import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.utils import timezone
from openadr3_client.models.common.interval import Interval as VtnInterval
from openadr3_client.models.common.interval_period import IntervalPeriod as VtnIntervalPeriod
from openadr3_client.models.common.unit import Unit
from openadr3_client.models.event.event import ExistingEvent
from openadr3_client.models.event.event_payload import EventPayload, EventPayloadDescriptor, EventPayloadType
from openadrgui.models.models import Interval, IntervalPeriod, ValidatedEvent
from openadrgui.services.repeat_program import (
    _shift_datetime_by_days,
    get_next_monday_midnight,
    repeat_intervals_for_coming_week,
)
from openadrgui.types import DeploymentSkippedError, RepeatedProgramError

TIMEZONE = timezone.get_current_timezone()


def _find_day_before_utc_offset_change(tz: ZoneInfo, year: int) -> datetime | None:
    """
    Find a day in `year` where the UTC offset at local midnight differs from the next day.

    Returns the local-midnight datetime for the day before the change, or None if none exists.
    """
    start = datetime(year, 1, 1, 0, 0, 0, tzinfo=tz)
    for i in range(370):  # safe upper bound
        d0 = start + timedelta(days=i)
        d1 = d0 + timedelta(days=1)
        if d0.utcoffset() != d1.utcoffset():
            return d0
    return None


@pytest.fixture
def correct_vtn_event() -> ExistingEvent:
    """Test the deploy program task entrypoint."""
    intervals = tuple(
        # Generate 7 intervals starting from next monday at midnight, each lasting 24 hours
        VtnInterval(
            id=index,
            interval_period=VtnIntervalPeriod(
                # Starting at the 6th of January 2025 (Monday), midnight
                start=datetime(2025, 1, index + 6, 0, 0, 0, tzinfo=TIMEZONE).astimezone(UTC),
                duration=timedelta(hours=24),
                randomize_start=None,
            ),
            payloads=(EventPayload(type=EventPayloadType.IMPORT_CAPACITY_LIMIT, values=(10,)),),
        )
        for index in range(7)
    )
    return ExistingEvent(
        id=str(uuid.uuid4()),
        created_date_time=datetime(2025, 1, 1, 0, 0, 0, tzinfo=TIMEZONE),
        modification_date_time=datetime(2025, 1, 1, 0, 0, 0, tzinfo=TIMEZONE),
        programID=str(uuid.uuid4()),
        event_name="event-1",
        priority=None,
        targets=None,
        payload_descriptors=(
            EventPayloadDescriptor(payload_type=EventPayloadType.IMPORT_CAPACITY_LIMIT, units=Unit.KW, currency=None),
        ),
        intervals=intervals,
    )


@pytest.fixture
def correct_dp_event() -> ValidatedEvent:
    """Create a mock ValidatedEvent with existing payload descriptors."""
    intervals = tuple(
        Interval(
            interval_period=IntervalPeriod(
                # Starting at the 6th of January 2025 (Monday), midnight. The same as the VTN event.
                start=datetime(2025, 1, index + 6, 0, 0, 0, tzinfo=TIMEZONE).astimezone(UTC),
                duration=timedelta(hours=24),
                randomize_start=None,
            ),
            payloads=(EventPayload(type=EventPayloadType.IMPORT_CAPACITY_LIMIT, values=(10,)),),
        )
        for index in range(7)
    )
    return ValidatedEvent(
        id=uuid.uuid4(),
        program_id=uuid.uuid4(),
        event_name="event-1",
        payload_descriptors=(
            EventPayloadDescriptor(payload_type=EventPayloadType.IMPORT_CAPACITY_LIMIT, units=Unit.KW, currency=None),
        ),
        intervals=intervals,
        targets=(),
        interval_period=None,
        priority=None,
    )


def test_intervals_should_add_one_week(correct_vtn_event: ExistingEvent, correct_dp_event: ValidatedEvent) -> None:
    """Test the happy path is as expected."""
    sunday_night_before_next_repeat = datetime(2025, 1, 12, 11, 0, 0, tzinfo=TIMEZONE)
    result = repeat_intervals_for_coming_week(
        vtn_events=(correct_vtn_event,),
        dp_events=(correct_dp_event,),
        current_datetime=sunday_night_before_next_repeat,
    )

    assert len(result) == 1
    event = result[0]

    assert len(event.intervals) == 7

    first_period = event.intervals[0].interval_period
    last_period = event.intervals[-1].interval_period

    assert first_period is not None
    assert last_period is not None

    assert first_period.start == datetime(2025, 1, 13, 0, 0, 0, tzinfo=TIMEZONE)
    assert first_period.duration == timedelta(hours=24)

    assert (last_period.start + last_period.duration) == datetime(2025, 1, 20, 0, 0, 0, tzinfo=TIMEZONE)
    assert last_period.duration == timedelta(hours=24)


def test_intervals_accross_dst_transition_should_be_correct(
    correct_vtn_event: ExistingEvent, correct_dp_event: ValidatedEvent
) -> None:
    """Test that intervals across DST transitions are correct."""
    day_before_change = _find_day_before_utc_offset_change(TIMEZONE, 2025)
    if day_before_change is None:
        pytest.fail("Current timezone has no DST/UTC-offset transitions in 2025")

    monday = day_before_change - timedelta(days=day_before_change.isoweekday() - 1)
    sunday_night_before_next_repeat = (monday + timedelta(days=6)).replace(hour=0, minute=0, second=0, microsecond=0)
    before_dst_transition_intervals = tuple(
        Interval(
            interval_period=IntervalPeriod(
                # Week starting Monday midnight in the current timezone (chosen to include an offset change).
                start=(monday + timedelta(days=index))
                .replace(hour=0, minute=0, second=0, microsecond=0)
                .astimezone(UTC),
                duration=timedelta(hours=24),
                randomize_start=None,
            ),
            payloads=(EventPayload(type=EventPayloadType.IMPORT_CAPACITY_LIMIT, values=(10,)),),
        )
        for index in range(7)
    )
    before_dst_transition_dp_event = correct_dp_event.model_copy(update={"intervals": before_dst_transition_intervals})

    correct_vtn_event = correct_vtn_event.model_copy(update={"intervals": before_dst_transition_intervals})

    sut = repeat_intervals_for_coming_week(
        vtn_events=(correct_vtn_event,),
        dp_events=(before_dst_transition_dp_event,),
        current_datetime=sunday_night_before_next_repeat,
    )

    assert len(sut) == 1
    sut_event = sut[0]

    assert len(sut_event.intervals) == 7

    expected_first = (monday + timedelta(days=7)).replace(hour=0, minute=0, second=0, microsecond=0)
    expected_last = (monday + timedelta(days=13)).replace(hour=0, minute=0, second=0, microsecond=0)

    first_period = sut_event.intervals[0].interval_period
    last_period = sut_event.intervals[-1].interval_period

    assert first_period is not None
    assert last_period is not None

    assert first_period.start == expected_first
    assert first_period.duration == timedelta(hours=24)

    assert last_period.start == expected_last
    assert last_period.duration == timedelta(hours=24)


def test_future_intervals_should_add_one_week(
    correct_vtn_event: ExistingEvent, correct_dp_event: ValidatedEvent
) -> None:
    """
    Test that DP events scheduled for future weeks are repeated correctly.

    Scenario: User creates DP events for week of Jan 20-26 (a future week).
    VTN already has events for Jan 6-12. When repeating on Sunday Jan 12,
    the function should take the future DP events (Jan 20-26) and repeat them
    for the next week relative to the next_monday input parameter (Jan 13).
    """
    sunday_night_before_next_repeat = datetime(2025, 1, 12, 11, 0, 0, tzinfo=TIMEZONE)

    # Create DP event scheduled for the FUTURE week (Jan 20-26, 2025)
    future_dp_intervals = tuple(
        Interval(
            interval_period=IntervalPeriod(
                # Starting at the 20th of January 2025 (Monday), midnight
                start=datetime(2025, 1, index + 20, 0, 0, 0, tzinfo=TIMEZONE).astimezone(UTC),
                duration=timedelta(hours=24),
                randomize_start=None,
            ),
            payloads=(EventPayload(type=EventPayloadType.IMPORT_CAPACITY_LIMIT, values=(10,)),),
        )
        for index in range(7)
    )
    future_dp_event = correct_dp_event.model_copy(update={"intervals": future_dp_intervals})

    result = repeat_intervals_for_coming_week(
        vtn_events=(correct_vtn_event,),
        dp_events=(future_dp_event,),
        current_datetime=sunday_night_before_next_repeat,
    )

    assert len(result) == 1
    event = result[0]

    assert len(event.intervals) == 7
    first_period = event.intervals[0].interval_period
    last_period = event.intervals[-1].interval_period
    assert first_period is not None
    assert last_period is not None

    assert first_period.start == datetime(2025, 1, 13, 0, 0, 0, tzinfo=TIMEZONE)
    assert first_period.duration == timedelta(hours=24)

    assert (last_period.start + last_period.duration) == datetime(2025, 1, 20, 0, 0, 0, tzinfo=TIMEZONE)
    assert last_period.duration == timedelta(hours=24)


def test_gap_in_dp_intervals_should_raise_error(
    correct_vtn_event: ExistingEvent, correct_dp_event: ValidatedEvent
) -> None:
    """Test that an error is raised if the DP event has a gap in intervals."""
    sunday_night_before_next_repeat = datetime(2025, 1, 12, 11, 0, 0, tzinfo=TIMEZONE)
    # Create a gap by removing interval 3 from the middle
    dp_intervals = (correct_dp_event.intervals or ())[:3] + (correct_dp_event.intervals or ())[4:]
    dp_event = correct_dp_event.model_copy(update={"intervals": dp_intervals})
    with pytest.raises(RepeatedProgramError) as e:
        repeat_intervals_for_coming_week(
            vtn_events=(correct_vtn_event,),
            dp_events=(dp_event,),
            current_datetime=sunday_night_before_next_repeat,
        )

    assert "DP event 'event-1' does not have continuous intervals" in str(e.value.errors)


def test_overlapping_intervals_should_raise_error(
    correct_vtn_event: ExistingEvent, correct_dp_event: ValidatedEvent
) -> None:
    """Test that an error is raised if the DP event has overlapping intervals."""
    sunday_night_before_next_repeat = datetime(2025, 1, 12, 11, 0, 0, tzinfo=TIMEZONE)
    dp_intervals = correct_dp_event.intervals or ()
    # Create a overlap by adding 2 hours to interval 3
    period = dp_intervals[3].interval_period
    assert period is not None
    overlapping_interval = dp_intervals[3].model_copy(
        update={"interval_period": period.model_copy(update={"duration": period.duration + timedelta(hours=2)})}
    )
    dp_intervals = (*dp_intervals[:3], overlapping_interval, *dp_intervals[4:])
    dp_event = correct_dp_event.model_copy(update={"intervals": dp_intervals})
    with pytest.raises(RepeatedProgramError) as e:
        repeat_intervals_for_coming_week(
            vtn_events=(correct_vtn_event,),
            dp_events=(dp_event,),
            current_datetime=sunday_night_before_next_repeat,
        )
    assert "DP event 'event-1' does not have continuous intervals" in str(e.value.errors)


def test_missing_final_vtn_intervals_should_raise_error(
    correct_vtn_event: ExistingEvent,
    correct_dp_event: ValidatedEvent,
) -> None:
    """Test that an error is raised if the VTN event is missing intervals."""
    sunday_night_before_next_repeat = datetime(2025, 1, 12, 11, 0, 0, tzinfo=TIMEZONE)
    vtn_intervals = correct_vtn_event.intervals[:-1]
    vtn_event = correct_vtn_event.model_copy(update={"intervals": vtn_intervals})
    with pytest.raises(RepeatedProgramError) as e:
        repeat_intervals_for_coming_week(
            vtn_events=(vtn_event,),
            dp_events=(correct_dp_event,),
            current_datetime=sunday_night_before_next_repeat,
        )
    assert "VTN event 'event-1' should last up to and including the next Monday midnight." in str(e.value.errors)


def test_already_filled_vtn_intervals_should_raise_error(
    correct_vtn_event: ExistingEvent,
    correct_dp_event: ValidatedEvent,
) -> None:
    """Test that an error is raised if the VTN event is already fully schedule for next week."""
    sunday_night_before_next_repeat = datetime(2025, 1, 12, 11, 0, 0, tzinfo=TIMEZONE)
    vtn_intervals = (
        *tuple(correct_vtn_event.intervals),
        VtnInterval(
            id=8,
            interval_period=VtnIntervalPeriod(
                start=datetime(2025, 1, 14, 0, 0, 0, tzinfo=TIMEZONE).astimezone(UTC),
                duration=timedelta(hours=24),
                randomize_start=None,
            ),
            payloads=(EventPayload(type=EventPayloadType.IMPORT_CAPACITY_LIMIT, values=(10,)),),
        ),
    )
    vtn_event = correct_vtn_event.model_copy(update={"intervals": vtn_intervals})
    with pytest.raises(DeploymentSkippedError) as e:
        repeat_intervals_for_coming_week(
            vtn_events=(vtn_event,),
            dp_events=(correct_dp_event,),
            current_datetime=sunday_night_before_next_repeat,
        )
    assert "VTN event 'event-1' already has intervals for the coming week." in str(e.value)


def test_next_monday_midnight_is_correct(correct_vtn_event: ExistingEvent) -> None:
    """Test that the next monday midnight is correct."""
    result = get_next_monday_midnight(datetime(2025, 1, 1, 0, 0, 0, tzinfo=TIMEZONE))
    assert result == datetime(2025, 1, 6, 0, 0, 0, tzinfo=TIMEZONE)


def test_next_monday_midnight_is_correct_when_already_monday(correct_vtn_event: ExistingEvent) -> None:
    """Test that the next monday midnight is correct."""
    result = get_next_monday_midnight(datetime(2025, 1, 6, 0, 0, 0, tzinfo=TIMEZONE))
    assert result == datetime(2025, 1, 13, 0, 0, 0, tzinfo=TIMEZONE)


def test_shift_datetime_by_days_is_correct(correct_vtn_event: ExistingEvent) -> None:
    """Test that the shift datetime by days is correct."""
    result = _shift_datetime_by_days(datetime(2025, 1, 1, 0, 0, 0, tzinfo=TIMEZONE).astimezone(UTC), 1)
    assert result.astimezone(TIMEZONE) == datetime(2025, 1, 2, 0, 0, 0, tzinfo=TIMEZONE)


def test_shift_datetime_by_days_is_correct_across_dst_transition(correct_vtn_event: ExistingEvent) -> None:
    """Test that the shift datetime by days is correct across DST transition."""
    day_before_change = _find_day_before_utc_offset_change(TIMEZONE, 2025)
    if day_before_change is None:
        pytest.fail("Current timezone has no DST/UTC-offset transitions in 2025")

    dt_local = day_before_change.replace(hour=0, minute=0, second=0, microsecond=0)
    result = _shift_datetime_by_days(dt_local.astimezone(UTC), 1)
    assert result.astimezone(TIMEZONE) == (dt_local + timedelta(days=1))
