# SPDX-FileCopyrightText: Contributors to openadr-gui<https://github.com/ElaadNL/openadr-gui>
#
# SPDX-License-Identifier: Apache-2.0

from datetime import datetime, timedelta

import pytest
from openadr3_client.models.event.event_payload import EventPayload, EventPayloadType
from openadrgui.models.models import IntervalPeriod, NormalizedInterval, SinglePayloadInterval
from openadrgui.services.merge_intervals import IntervalPeriodConflictError, merge_intervals
from pytz import UTC


def test_merge_intervals_weaves_same_period_different_payloads() -> None:
    """Test that intervals with same intervalPeriod but different payloads are merged."""
    # Create two intervals with identical intervalPeriod but different payload types
    start_time = datetime(2025, 1, 15, 20, 30, 0, tzinfo=UTC)
    period = IntervalPeriod(start=start_time, duration=timedelta(hours=1))

    interval1 = NormalizedInterval(
        interval_period=period, payloads=(EventPayload(type=EventPayloadType.IMPORT_CAPACITY_LIMIT, values=(10,)),)
    )

    interval2 = SinglePayloadInterval(
        interval_period=period, payload=EventPayload(type=EventPayloadType.EXPORT_CAPACITY_LIMIT, values=(10,))
    )

    result = merge_intervals((interval1,), (interval2,))

    # Should result in one interval with both payloads
    assert len(result) == 1
    assert len(result[0].payloads) == 2
    assert result[0].interval_period == period

    # Check that both payload types are present
    payload_types = {payload.type for payload in result[0].payloads}
    assert payload_types == {EventPayloadType.IMPORT_CAPACITY_LIMIT, EventPayloadType.EXPORT_CAPACITY_LIMIT}


def test_merge_intervals_non_overlapping_different_periods() -> None:
    """Test that non-overlapping intervals with different periods are merged successfully."""
    start_time1 = datetime(2025, 1, 15, 20, 30, 0, tzinfo=UTC)
    start_time2 = datetime(2025, 1, 15, 22, 30, 0, tzinfo=UTC)  # 2 hours later, no overlap

    interval1 = NormalizedInterval(
        interval_period=IntervalPeriod(start=start_time1, duration=timedelta(hours=1)),
        payloads=(EventPayload(type=EventPayloadType.IMPORT_CAPACITY_LIMIT, values=(10,)),),
    )

    interval2 = SinglePayloadInterval(
        interval_period=IntervalPeriod(start=start_time2, duration=timedelta(minutes=30)),
        payload=EventPayload(type=EventPayloadType.EXPORT_CAPACITY_LIMIT, values=(20,)),
    )

    result = merge_intervals((interval1,), (interval2,))

    # Should result in two separate intervals, sorted by start time
    assert len(result) == 2
    assert result[0].interval_period.start == start_time1
    assert result[1].interval_period.start == start_time2


def test_merge_intervals_overlapping_different_periods_raises_error() -> None:
    """Test that overlapping intervals with different periods raise an error."""
    start_time = datetime(2025, 1, 15, 20, 30, 0, tzinfo=UTC)

    interval1 = NormalizedInterval(
        interval_period=IntervalPeriod(start=start_time, duration=timedelta(hours=1)),
        payloads=(EventPayload(type=EventPayloadType.IMPORT_CAPACITY_LIMIT, values=(10,)),),
    )

    # Overlapping interval with different duration
    interval2 = SinglePayloadInterval(
        interval_period=IntervalPeriod(start=start_time + timedelta(minutes=30), duration=timedelta(hours=1)),
        payload=EventPayload(type=EventPayloadType.EXPORT_CAPACITY_LIMIT, values=(20,)),
    )

    with pytest.raises(IntervalPeriodConflictError) as exc_info:
        merge_intervals((interval1,), (interval2,))

    assert "Overlapping intervals may not have different intervalPeriod durations" in str(exc_info.value)


def test_merge_intervals_overlapping_same_periods() -> None:
    """Test that overlapping intervals with identical periods are merged correctly."""
    start_time = datetime(2025, 1, 15, 20, 30, 0, tzinfo=UTC)
    period = IntervalPeriod(start=start_time, duration=timedelta(hours=1))

    interval1 = NormalizedInterval(
        interval_period=period, payloads=(EventPayload(type=EventPayloadType.IMPORT_CAPACITY_LIMIT, values=(10,)),)
    )

    interval2 = SinglePayloadInterval(
        interval_period=period, payload=EventPayload(type=EventPayloadType.EXPORT_CAPACITY_LIMIT, values=(20,))
    )

    result = merge_intervals((interval1,), (interval2,))

    # Should result in one merged interval
    assert len(result) == 1
    assert len(result[0].payloads) == 2
    assert result[0].interval_period == period


def test_merge_intervals_empty_inputs() -> None:
    """Test merge_intervals with empty inputs."""
    # Both empty
    result = merge_intervals((), ())
    assert result == ()

    # One empty
    normalized_interval = NormalizedInterval(
        interval_period=IntervalPeriod(start=datetime(2025, 1, 15, 20, 30, 0, tzinfo=UTC), duration=timedelta(hours=1)),
        payloads=(EventPayload(type=EventPayloadType.IMPORT_CAPACITY_LIMIT, values=(10,)),),
    )

    result = merge_intervals((normalized_interval,), ())
    assert result == (normalized_interval,)

    single_payload_interval = SinglePayloadInterval(
        interval_period=IntervalPeriod(start=datetime(2025, 1, 15, 20, 30, 0, tzinfo=UTC), duration=timedelta(hours=1)),
        payload=EventPayload(type=EventPayloadType.IMPORT_CAPACITY_LIMIT, values=(10,)),
    )

    result = merge_intervals((), (single_payload_interval,))
    expected = NormalizedInterval(
        interval_period=IntervalPeriod(start=datetime(2025, 1, 15, 20, 30, 0, tzinfo=UTC), duration=timedelta(hours=1)),
        payloads=(EventPayload(type=EventPayloadType.IMPORT_CAPACITY_LIMIT, values=(10,)),),
    )
    assert result == (expected,)


def test_merge_intervals_multiple_groups() -> None:
    """Test merging intervals with multiple different intervalPeriods."""
    start_time1 = datetime(2025, 1, 15, 20, 30, 0, tzinfo=UTC)
    start_time2 = datetime(2025, 1, 15, 22, 30, 0, tzinfo=UTC)

    period1 = IntervalPeriod(start=start_time1, duration=timedelta(hours=1))
    period2 = IntervalPeriod(start=start_time2, duration=timedelta(hours=1))

    # Two intervals with period1, one with period2
    existing_intervals = (
        NormalizedInterval(
            interval_period=period1, payloads=(EventPayload(type=EventPayloadType.IMPORT_CAPACITY_LIMIT, values=(1,)),)
        ),
        NormalizedInterval(
            interval_period=period2, payloads=(EventPayload(type=EventPayloadType.EXPORT_CAPACITY_LIMIT, values=(2,)),)
        ),
    )

    new_intervals = (
        SinglePayloadInterval(interval_period=period1, payload=EventPayload(type=EventPayloadType.PRICE, values=(3,))),
    )

    result = merge_intervals(existing_intervals, new_intervals)

    # Should result in two intervals: one merged (period1) and one unchanged (period2)
    assert len(result) == 2

    # Find the merged interval (should have 2 payloads)
    merged_interval = next(interval for interval in result if len(interval.payloads) == 2)
    single_interval = next(interval for interval in result if len(interval.payloads) == 1)

    assert merged_interval.interval_period == period1
    assert single_interval.interval_period == period2

    # Check payload types in merged interval
    merged_types = {payload.type for payload in merged_interval.payloads}
    assert merged_types == {EventPayloadType.IMPORT_CAPACITY_LIMIT, EventPayloadType.PRICE}


def test_merge_intervals_sorts_by_start_time() -> None:
    """Test that merged intervals are sorted by start time."""
    start_time1 = datetime(2025, 1, 15, 22, 30, 0, tzinfo=UTC)  # Later
    start_time2 = datetime(2025, 1, 15, 20, 30, 0, tzinfo=UTC)  # Earlier

    interval1 = NormalizedInterval(
        interval_period=IntervalPeriod(start=start_time1, duration=timedelta(hours=1)),
        payloads=(EventPayload(type=EventPayloadType.IMPORT_CAPACITY_LIMIT, values=(10,)),),
    )

    interval2 = SinglePayloadInterval(
        interval_period=IntervalPeriod(start=start_time2, duration=timedelta(hours=1)),
        payload=EventPayload(type=EventPayloadType.EXPORT_CAPACITY_LIMIT, values=(20,)),
    )

    result = merge_intervals((interval1,), (interval2,))

    # Should be sorted by start time (earlier first)
    assert len(result) == 2
    assert result[0].interval_period.start == start_time2
    assert result[1].interval_period.start == start_time1


def test_merge_intervals_touching_intervals_different_periods() -> None:
    """Test intervals that touch but don't overlap with different periods."""
    start_time1 = datetime(2025, 1, 15, 20, 30, 0, tzinfo=UTC)
    start_time2 = start_time1 + timedelta(hours=1)  # Exactly when first ends

    interval1 = NormalizedInterval(
        interval_period=IntervalPeriod(start=start_time1, duration=timedelta(hours=1)),
        payloads=(EventPayload(type=EventPayloadType.IMPORT_CAPACITY_LIMIT, values=(10,)),),
    )

    interval2 = SinglePayloadInterval(
        interval_period=IntervalPeriod(start=start_time2, duration=timedelta(minutes=30)),  # Different duration
        payload=EventPayload(type=EventPayloadType.EXPORT_CAPACITY_LIMIT, values=(20,)),
    )

    # Should not raise error since they don't overlap (touching is OK)
    result = merge_intervals((interval1,), (interval2,))

    assert len(result) == 2
    assert result[0].interval_period.start == start_time1
    assert result[1].interval_period.start == start_time2
