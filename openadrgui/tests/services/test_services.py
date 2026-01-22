# SPDX-FileCopyrightText: Contributors to openadr-gui<https://github.com/ElaadNL/openadr-gui>
#
# SPDX-License-Identifier: Apache-2.0

import io
import uuid
from datetime import UTC, date, datetime, timedelta, tzinfo
from typing import Any

import numpy as np
import numpy.typing as npt
import pytest
from django.utils import timezone
from openadr3_client.models.common.interval import Interval as OpenADRInterval
from openadr3_client.models.common.unit import Unit
from openadr3_client.models.event.event import ExistingEvent
from openadr3_client.models.event.event_payload import EventPayload, EventPayloadDescriptor, EventPayloadType
from openadrgui.models.models import (
    Interval,
    IntervalPeriod,
    NormalizedInterval,
    SinglePayloadInterval,
    Target,
    ValidatedEvent,
)
from openadrgui.services.services import (
    _decimate_graph_intervals,
    aggregate_targets,
    curve_to_intervals,
    get_min_max_local_date,
    intervals_from_csv,
    intervals_to_graph,
    normalize_intervals,
    split_targets,
    to_single_payload_intervals,
    update_intervals_list,
    update_payload_descriptors_list,
)
from pydantic_extra_types.currency_code import ISO4217

MONTH_TRANSITION_TEST_CASES = [
    (date(2024, 1, 31), "31->1"),  # 31 days
    (date(2024, 2, 29), "29->1"),  # Leap year February
    (date(2024, 4, 30), "30->1"),  # 30 days
]


def _tz() -> tzinfo:
    return timezone.get_current_timezone()


def _local_midnight_utc(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, 0, 0, tzinfo=_tz()).astimezone(UTC)


@pytest.fixture
def normalize_intervals_expected() -> tuple[NormalizedInterval, ...]:
    """Fixture for normalize_intervals test data."""
    return (
        NormalizedInterval(
            interval_period=IntervalPeriod(
                start=datetime(2023, 1, 1, 10, 0, tzinfo=_tz()), duration=timedelta(hours=1)
            ),
            payloads=(EventPayload(type=EventPayloadType.IMPORT_CAPACITY_LIMIT, values=(10,)),),
        ),
        NormalizedInterval(
            interval_period=IntervalPeriod(
                start=datetime(2023, 1, 1, 11, 0, tzinfo=_tz()), duration=timedelta(hours=1)
            ),
            payloads=(EventPayload(type=EventPayloadType.IMPORT_CAPACITY_LIMIT, values=(20,)),),
        ),
    )


def test_normalize_intervals_handles_seperated_format(
    normalize_intervals_expected: tuple[NormalizedInterval, ...],
) -> None:
    """Test that normalize_intervals correctly handles seperated format."""
    # Create a sample event_interval
    event_interval = None
    sut = (
        Interval(
            interval_period=IntervalPeriod(
                start=datetime(2023, 1, 1, 10, 0, tzinfo=_tz()), duration=timedelta(hours=1)
            ),
            payloads=(EventPayload(type=EventPayloadType.IMPORT_CAPACITY_LIMIT, values=(10,)),),
        ),
        Interval(
            interval_period=IntervalPeriod(
                start=datetime(2023, 1, 1, 11, 0, tzinfo=_tz()), duration=timedelta(hours=1)
            ),
            payloads=(EventPayload(type=EventPayloadType.IMPORT_CAPACITY_LIMIT, values=(20,)),),
        ),
    )

    result = normalize_intervals(event_interval, sut)

    assert result == normalize_intervals_expected


def test_normalize_intervals_handles_continuous_format(
    normalize_intervals_expected: tuple[NormalizedInterval, ...],
) -> None:
    """Test that normalize_intervals correctly handles continuous format."""
    # Create a sample event_interval
    event_interval = IntervalPeriod(start=datetime(2023, 1, 1, 10, 0, tzinfo=_tz()), duration=timedelta(hours=1))

    # Create sample intervals
    sut = (
        Interval(
            interval_period=None,
            payloads=(EventPayload(type=EventPayloadType.IMPORT_CAPACITY_LIMIT, values=(10,)),),
        ),
        Interval(
            interval_period=None,
            payloads=(EventPayload(type=EventPayloadType.IMPORT_CAPACITY_LIMIT, values=(20,)),),
        ),
    )

    result = normalize_intervals(event_interval, sut)

    assert result == normalize_intervals_expected


def test_to_single_payload_intervals_handles_multiple_payloads() -> None:
    """Test that to_single_payload_intervals correctly handles multiple payloads."""
    period = IntervalPeriod(
        start=datetime(2023, 1, 1, 10, 0, tzinfo=_tz()),
        duration=timedelta(hours=1),
    )
    period2 = IntervalPeriod(
        start=period.start + timedelta(hours=1),
        duration=timedelta(hours=1),
    )
    sut = (
        NormalizedInterval(
            interval_period=period,
            payloads=(EventPayload(type=EventPayloadType.IMPORT_CAPACITY_LIMIT, values=(10,)),),
        ),
        NormalizedInterval(
            interval_period=period2,
            payloads=(EventPayload(type=EventPayloadType.IMPORT_CAPACITY_LIMIT, values=(20,)),),
        ),
    )

    result = to_single_payload_intervals(sut, EventPayloadType.IMPORT_CAPACITY_LIMIT)
    assert result == (
        SinglePayloadInterval(
            interval_period=period,
            payload=EventPayload(type=EventPayloadType.IMPORT_CAPACITY_LIMIT, values=(10,)),
        ),
        SinglePayloadInterval(
            interval_period=period2,
            payload=EventPayload(type=EventPayloadType.IMPORT_CAPACITY_LIMIT, values=(20,)),
        ),
    )


def test_to_single_payload_intervals_handles_no_payloads() -> None:
    """Test that to_single_payload_intervals correctly handles no payloads."""
    period = IntervalPeriod(
        start=datetime(2023, 1, 1, 10, 0, tzinfo=_tz()),
        duration=timedelta(hours=1),
    )
    sut = (
        NormalizedInterval(
            interval_period=period,
            payloads=(EventPayload(type=EventPayloadType.IMPORT_CAPACITY_LIMIT, values=(10,)),),
        ),
    )
    result = to_single_payload_intervals(sut, EventPayloadType.EXPORT_CAPACITY_LIMIT)
    assert result == ()


def test_to_single_payload_intervals_handles_multiple_payloads_of_different_types() -> None:
    """Test that to_single_payload_intervals correctly handles multiple payloads of different types."""
    period = IntervalPeriod(
        start=datetime(2023, 1, 1, 10, 0, tzinfo=_tz()),
        duration=timedelta(hours=1),
    )
    period2 = IntervalPeriod(
        start=period.start + timedelta(hours=1),
        duration=timedelta(hours=1),
    )
    sut = (
        NormalizedInterval(
            interval_period=period,
            payloads=(EventPayload(type=EventPayloadType.IMPORT_CAPACITY_LIMIT, values=(10,)),),
        ),
        NormalizedInterval(
            interval_period=period2,
            payloads=(EventPayload(type=EventPayloadType.EXPORT_CAPACITY_LIMIT, values=(20,)),),
        ),
    )
    result = to_single_payload_intervals(sut, EventPayloadType.IMPORT_CAPACITY_LIMIT)
    assert result == (
        SinglePayloadInterval(
            interval_period=period,
            payload=EventPayload(type=EventPayloadType.IMPORT_CAPACITY_LIMIT, values=(10,)),
        ),
    )


def test_to_single_payload_intervals_throws_error_when_multiple_payloads_of_same_type() -> None:
    """Test that to_single_payload_intervals throws an error when multiple payloads of the same type are provided."""
    period = IntervalPeriod(
        start=datetime(2023, 1, 1, 10, 0, tzinfo=_tz()),
        duration=timedelta(hours=1),
    )
    period2 = IntervalPeriod(
        start=period.start + timedelta(hours=1),
        duration=timedelta(hours=1),
    )
    sut = (
        NormalizedInterval(
            interval_period=period,
            payloads=(
                EventPayload(type=EventPayloadType.IMPORT_CAPACITY_LIMIT, values=(10,)),
                EventPayload(type=EventPayloadType.IMPORT_CAPACITY_LIMIT, values=(10,)),
            ),
        ),
        NormalizedInterval(
            interval_period=period2,
            payloads=(EventPayload(type=EventPayloadType.IMPORT_CAPACITY_LIMIT, values=(20,)),),
        ),
    )
    with pytest.raises(
        ValueError,
        match="Payloads may not contain multiple payloads with the same type of IMPORT_CAPACITY_LIMIT, got 2",
    ):
        to_single_payload_intervals(sut, EventPayloadType.IMPORT_CAPACITY_LIMIT)


def test_curve_to_intervals_creates_correct_number_of_intervals() -> None:
    """Test that curve_to_intervals correctly formats data."""
    # Setup mock to return a simple array of values
    mock_curve_data = np.array([10, 20, 30, 40, 50], dtype=np.int64)
    start_time = date(2023, 1, 1)

    # Call the function
    result = curve_to_intervals(
        start_time=start_time, event_payload_type=EventPayloadType.IMPORT_CAPACITY_LIMIT, curve_data=mock_curve_data
    )

    # Check the result
    assert len(result) == 5

    # Check first entry - should be local midnight converted to UTC
    expected_start = _local_midnight_utc(date(2023, 1, 1))
    assert result[0].interval_period.start == expected_start
    assert result[0].payload.values == (10,)

    # Check last entry
    assert result[4].interval_period.start == expected_start + timedelta(minutes=60)
    assert result[4].payload.values == (50,)


def test_curve_to_intervals_handles_multi_day_data() -> None:
    """Test that time is correctly formatted in the intervals."""
    # Create a sample array where we'll have more than 24 hours of data
    mock_curve_data = np.ones(100, dtype=np.int64)  # 100 data points (25 hours worth)
    start_time = date(2023, 1, 1)

    result = curve_to_intervals(
        start_time=start_time, event_payload_type=EventPayloadType.IMPORT_CAPACITY_LIMIT, curve_data=mock_curve_data
    )

    # Check a few specific time points - should be local midnight converted to UTC
    expected_start = _local_midnight_utc(date(2023, 1, 1))
    assert result[0].interval_period.start == expected_start
    assert result[4].interval_period.start == expected_start + timedelta(minutes=60)
    assert result[96].interval_period.start == expected_start + timedelta(days=1)  # Wraps around after 24 hours


def test_curve_to_intervals_handles_empty_input() -> None:
    """Test curve_to_intervals with empty data."""
    mock_curve_data = np.array([], dtype=np.int64)
    start_time = date(2023, 1, 1)

    result = curve_to_intervals(
        start_time=start_time, event_payload_type=EventPayloadType.IMPORT_CAPACITY_LIMIT, curve_data=mock_curve_data
    )

    # Check that we get an empty tuple when no data is returned
    assert len(result) == 0
    assert isinstance(result, tuple)


def test_curve_to_intervals_preserves_extreme_values() -> None:
    """Test curve_to_intervals with boundary values."""
    # Test with extreme values
    mock_curve_data = np.array(
        [
            np.iinfo(np.int64).max,
            np.iinfo(np.int64).min + 1,
            0,
            10,
            -10,
        ],
        dtype=np.int64,
    )
    start_time = date(2023, 1, 1)

    result = curve_to_intervals(
        start_time=start_time, event_payload_type=EventPayloadType.IMPORT_CAPACITY_LIMIT, curve_data=mock_curve_data
    )

    # Check that all values are preserved correctly
    assert result[0].payload.values == (np.iinfo(np.int64).max,)
    assert result[1].payload.values == (np.iinfo(np.int64).min + 1,)
    assert result[2].payload.values == (0,)
    assert result[3].payload.values == (10,)
    assert result[4].payload.values == (-10,)


@pytest.fixture
def interval_data() -> dict[str, Any]:
    """Fixture for interval test data."""
    # Create a sample event_interval
    event_interval = IntervalPeriod(start=datetime(2023, 1, 1, 10, 0, tzinfo=_tz()), duration=timedelta(hours=1))

    # Create sample payloads
    payload1 = EventPayload(type=EventPayloadType.IMPORT_CAPACITY_LIMIT, values=(10,))

    payload2 = EventPayload(type=EventPayloadType.IMPORT_CAPACITY_LIMIT, values=(20,))

    # Create sample intervals
    interval1 = NormalizedInterval(
        interval_period=IntervalPeriod(start=datetime(2023, 1, 1, 10, 0, tzinfo=_tz()), duration=timedelta(hours=1)),
        payloads=(payload1,),
    )

    interval2 = NormalizedInterval(
        interval_period=IntervalPeriod(start=datetime(2023, 1, 1, 11, 0, tzinfo=_tz()), duration=timedelta(hours=1)),
        payloads=(payload2,),
    )

    intervals = (interval1, interval2)

    return {
        "event_interval": event_interval,
        "payload1": payload1,
        "payload2": payload2,
        "interval1": interval1,
        "interval2": interval2,
        "intervals": intervals,
    }


def test_intervals_to_graph_formats_separated_intervals(interval_data: dict[str, Any]) -> None:
    """Test intervals_to_graph with normalized intervals in separated format."""
    normalized = to_single_payload_intervals(
        normalize_intervals(None, interval_data["intervals"]),
        EventPayloadType.IMPORT_CAPACITY_LIMIT,
    )
    result = intervals_to_graph(intervals=tuple(normalized))
    data = result["data"]
    is_decimated = result["is_decimated"]

    # Check the result
    assert len(result["data"]) == 2

    # Check first entry - times are in UTC as per fixture
    assert data[0]["x"] == datetime(2023, 1, 1, 10, 0, tzinfo=_tz()).timestamp() * 1000
    assert data[0]["y"] == 10

    # Check second entry
    assert data[1]["x"] == datetime(2023, 1, 1, 11, 0, tzinfo=_tz()).timestamp() * 1000
    assert data[1]["y"] == 20

    assert is_decimated is False


def test_intervals_to_graph_formats_continuous_intervals(interval_data: dict[str, Any]) -> None:
    """Test intervals_to_graph with normalized intervals in continuous format."""
    normalized = to_single_payload_intervals(
        normalize_intervals(interval_data["event_interval"], interval_data["intervals"]),
        EventPayloadType.IMPORT_CAPACITY_LIMIT,
    )
    result = intervals_to_graph(intervals=normalized)
    data = result["data"]
    is_decimated = result["is_decimated"]

    # Check the result
    assert len(data) == 2

    # Check entries - in continuous format, times are calculated from event_interval
    # First interval is at event_interval.start + event_interval.duration
    # Times are converted to local timezone twice (once in normalize_intervals, once in intervals_to_graph)
    assert data[0]["x"] == datetime(2023, 1, 1, 10, 0, tzinfo=_tz()).timestamp() * 1000
    assert data[0]["y"] == 10

    # Second interval is at previous time + event_interval.duration
    assert data[1]["x"] == datetime(2023, 1, 1, 11, 0, tzinfo=_tz()).timestamp() * 1000
    assert data[1]["y"] == 20

    assert is_decimated is False


def test_intervals_to_graph_handles_empty_input() -> None:
    """Test intervals_to_graph with empty intervals."""
    result = intervals_to_graph(intervals=())
    data = result["data"]
    is_decimated = result["is_decimated"]

    # Check that we get an empty list when no intervals are provided
    assert data == []
    assert is_decimated is False


def test_decimate_time_series_small_dataset() -> None:
    """Test decimate_time_series with a small dataset."""
    start_date = datetime(2023, 1, 1, 0, 0, 0, tzinfo=_tz())
    data = [
        {"x": (start_date + timedelta(minutes=15)).timestamp() * 1000, "y": 1},
        {"x": (start_date + timedelta(minutes=30)).timestamp() * 1000, "y": 2},
        {"x": (start_date + timedelta(minutes=45)).timestamp() * 1000, "y": 3},
        {"x": (start_date + timedelta(minutes=60)).timestamp() * 1000, "y": 4},
    ]
    result = _decimate_graph_intervals(data, small_dataset_limit=4, large_dataset_limit=8)
    assert result == data


def test_decimate_time_series_medium_dataset() -> None:
    """Test decimate_time_series with a small dataset."""
    start_date = datetime(2023, 1, 1, 0, 0, 0, tzinfo=_tz())
    data = [
        {"x": (start_date + timedelta(minutes=15)).timestamp() * 1000, "y": 1},
        {"x": (start_date + timedelta(minutes=30)).timestamp() * 1000, "y": 2},
        {"x": (start_date + timedelta(minutes=45)).timestamp() * 1000, "y": 3},
        {"x": (start_date + timedelta(hours=1)).timestamp() * 1000, "y": 4},
        {"x": (start_date + timedelta(hours=1, minutes=15)).timestamp() * 1000, "y": 5},
        {"x": (start_date + timedelta(hours=1, minutes=30)).timestamp() * 1000, "y": 6},
        {"x": (start_date + timedelta(hours=1, minutes=45)).timestamp() * 1000, "y": 7},
        {"x": (start_date + timedelta(hours=2)).timestamp() * 1000, "y": 8},
    ]
    result = _decimate_graph_intervals(data, small_dataset_limit=4, large_dataset_limit=8)

    assert result[0]["x"] == (start_date + timedelta(minutes=30)).timestamp() * 1000
    assert result[1]["x"] == (start_date + timedelta(hours=1)).timestamp() * 1000
    assert result[2]["x"] == (start_date + timedelta(hours=1, minutes=30)).timestamp() * 1000
    assert result[3]["x"] == (start_date + timedelta(hours=2)).timestamp() * 1000

    assert len(data) == 8
    assert len(result) == 4


def test_decimate_time_series_large_dataset() -> None:
    """Test decimate_time_series with a small dataset."""
    start_date = datetime(2023, 1, 1, 0, 0, 0, tzinfo=_tz())
    data = [
        {"x": (start_date + timedelta(minutes=15)).timestamp() * 1000, "y": 1},
        {"x": (start_date + timedelta(minutes=30)).timestamp() * 1000, "y": 2},
        {"x": (start_date + timedelta(minutes=45)).timestamp() * 1000, "y": 3},
        {"x": (start_date + timedelta(hours=1)).timestamp() * 1000, "y": 4},
        {"x": (start_date + timedelta(hours=1, minutes=15)).timestamp() * 1000, "y": 5},
        {"x": (start_date + timedelta(hours=1, minutes=30)).timestamp() * 1000, "y": 6},
        {"x": (start_date + timedelta(hours=1, minutes=45)).timestamp() * 1000, "y": 7},
        {"x": (start_date + timedelta(hours=2)).timestamp() * 1000, "y": 8},
        {"x": (start_date + timedelta(hours=2, minutes=15)).timestamp() * 1000, "y": 9},
        {"x": (start_date + timedelta(hours=2, minutes=30)).timestamp() * 1000, "y": 10},
        {"x": (start_date + timedelta(hours=2, minutes=45)).timestamp() * 1000, "y": 11},
        {"x": (start_date + timedelta(hours=3)).timestamp() * 1000, "y": 12},
    ]
    result = _decimate_graph_intervals(data, small_dataset_limit=4, large_dataset_limit=8)

    assert result[0]["x"] == (start_date + timedelta(hours=1)).timestamp() * 1000
    assert result[1]["x"] == (start_date + timedelta(hours=2)).timestamp() * 1000
    assert result[2]["x"] == (start_date + timedelta(hours=3)).timestamp() * 1000

    assert len(data) == 12
    assert len(result) == 3


def test_curve_to_intervals_creates_correct_interval_structure() -> None:
    """Test basic functionality of curve_to_intervals."""
    start_time = date(2023, 1, 1)
    event_payload_type = EventPayloadType.IMPORT_CAPACITY_LIMIT
    curve_data = np.array([10, 20, 30], dtype=np.int64)  # 3 intervals with different values

    result = curve_to_intervals(start_time=start_time, event_payload_type=event_payload_type, curve_data=curve_data)

    assert len(result) == 3

    # Check first interval - should be local midnight converted to UTC
    expected_start = _local_midnight_utc(date(2023, 1, 1))
    assert result[0].interval_period.start == expected_start
    assert result[0].interval_period.duration == timedelta(minutes=15)
    assert result[0].payload.type == event_payload_type
    assert result[0].payload.values == (10,)

    # Check second interval (should be 15 minutes after start)
    assert result[1].interval_period.start == expected_start + timedelta(minutes=15)
    assert result[1].payload.values == (20,)


def test_curve_to_intervals_supports_all_payload_types() -> None:
    """Test curve_to_intervals with different payload types."""
    start_time = date(2023, 1, 1)
    curve_data = np.array([10], dtype=np.int64)

    # Test with different payload types
    for payload_type in [
        EventPayloadType.IMPORT_CAPACITY_LIMIT,
        EventPayloadType.EXPORT_CAPACITY_LIMIT,
        EventPayloadType.PRICE,
    ]:
        result = curve_to_intervals(start_time=start_time, event_payload_type=payload_type, curve_data=curve_data)

        assert result[0].payload.type == payload_type


def test_curve_to_intervals_handles_leap_year_transition() -> None:
    """Test that intervals are correctly generated over leap day boundary."""
    # Start on February 28th of a leap year
    start_time = date(2024, 2, 28)

    # Generate 2 days worth of data (192 intervals)
    curve_data = np.full(192, 100, dtype=np.int64)

    intervals = curve_to_intervals(
        start_time=start_time, event_payload_type=EventPayloadType.IMPORT_CAPACITY_LIMIT, curve_data=curve_data
    )

    # Check intervals around midnight and leap day - all times should be local-midnight converted to UTC
    feb_28_0000 = _local_midnight_utc(date(2024, 2, 28))
    feb_29_0000 = _local_midnight_utc(date(2024, 2, 29))
    mar_1_0000 = _local_midnight_utc(date(2024, 3, 1))

    assert intervals[0].interval_period.start == feb_28_0000
    assert intervals[96].interval_period.start == feb_29_0000
    # Last interval starts 15 min before midnight
    assert intervals[191].interval_period.start == mar_1_0000 - timedelta(minutes=15)


def test_curve_to_intervals_handles_non_leap_year_transition() -> None:
    """Test that intervals are correctly generated over February in non-leap year."""
    # Start on February 28th of a non-leap year
    start_time = date(2023, 2, 28)

    # Generate 2 days worth of data (192 intervals)
    curve_data = np.full(192, 100, dtype=np.int64)

    intervals = curve_to_intervals(
        start_time=start_time, event_payload_type=EventPayloadType.IMPORT_CAPACITY_LIMIT, curve_data=curve_data
    )

    # Check intervals around midnight - all times should be local-midnight converted to UTC
    feb_28_0000 = _local_midnight_utc(date(2023, 2, 28))
    mar_1_0000 = _local_midnight_utc(date(2023, 3, 1))

    assert intervals[0].interval_period.start == feb_28_0000
    assert intervals[96].interval_period.start == mar_1_0000


@pytest.fixture
def month_transition_test_data() -> list[tuple[date, str]]:
    """Fixture providing test data for month transitions."""
    return MONTH_TRANSITION_TEST_CASES


@pytest.fixture
def curve_data_two_days() -> npt.NDArray[np.int_]:
    """Fixture providing 2 days worth of curve data (192 intervals)."""
    return np.full(192, 100, dtype=np.int64)


@pytest.mark.parametrize(("start_time", "case"), MONTH_TRANSITION_TEST_CASES)
def test_curve_to_intervals_handles_month_transitions(
    start_time: date, case: str, curve_data_two_days: npt.NDArray[np.int_]
) -> None:
    """Test that intervals are correctly generated over various month boundaries."""
    intervals = curve_to_intervals(
        start_time=start_time, event_payload_type=EventPayloadType.IMPORT_CAPACITY_LIMIT, curve_data=curve_data_two_days
    )

    # Check the transition over midnight - all times should be local-midnight converted to UTC
    first_day = _local_midnight_utc(start_time)
    next_date = date(
        start_time.year,
        start_time.month + 1 if start_time.month < 12 else 1,
        1,
    )
    next_day = _local_midnight_utc(next_date)

    assert intervals[0].interval_period.start == first_day, f"Failed for case {case}"
    assert intervals[96].interval_period.start == next_day, f"Failed for case {case}"


def test_min_max_date_returns_correct_values() -> None:
    """Test that min_max_date returns the correct values."""
    sut = (
        SinglePayloadInterval(
            interval_period=IntervalPeriod(start=datetime(2023, 1, 1, 0, 0, tzinfo=_tz()), duration=timedelta(hours=1)),
            payload=EventPayload(type=EventPayloadType.IMPORT_CAPACITY_LIMIT, values=(10,)),
        ),
        SinglePayloadInterval(
            interval_period=IntervalPeriod(
                start=datetime(2023, 1, 1, 23, 0, tzinfo=_tz()), duration=timedelta(hours=1)
            ),
            payload=EventPayload(type=EventPayloadType.IMPORT_CAPACITY_LIMIT, values=(20,)),
        ),
    )
    expected = (
        # starts on 1st of January
        date(2023, 1, 1),
        # 23:00 + 1 hour is until the 2nd of January
        date(2023, 1, 2),
    )
    assert get_min_max_local_date(tuple(sut)) == expected


def test_intervals_from_csv_basic_functionality() -> None:
    """Test basic functionality of intervals_from_csv with comma-separated values."""
    csv_content = (
        "2023-01-01T10:00:00+01:00,2023-01-01T11:00:00+01:00,10\n2023-01-01T11:00:00+01:00,2023-01-01T12:00:00+01:00,20"
    )
    file_input = io.BytesIO(csv_content.encode("utf-8"))

    result = intervals_from_csv(file_input, EventPayloadType.IMPORT_CAPACITY_LIMIT)

    assert len(result) == 2
    # Check first interval
    assert result[0].interval_period.start == datetime.fromisoformat("2023-01-01T10:00:00+01:00")
    assert result[0].interval_period.duration == timedelta(hours=1)
    assert result[0].payload.type == EventPayloadType.IMPORT_CAPACITY_LIMIT
    assert result[0].payload.values == (10.0,)
    # Check second interval
    assert result[1].interval_period.start == datetime.fromisoformat("2023-01-01T11:00:00+01:00")
    assert result[1].payload.type == EventPayloadType.IMPORT_CAPACITY_LIMIT
    assert result[1].payload.values == (20.0,)


def test_intervals_from_csv_different_delimiters() -> None:
    """Test intervals_from_csv with different CSV delimiters."""
    # Test with semicolon delimiter
    csv_content = (
        "2023-01-01T10:00:00+01:00;2023-01-01T11:00:00+01:00;10\n2023-01-01T11:00:00+01:00;2023-01-01T12:00:00+01:00;20"
    )
    file_input = io.BytesIO(csv_content.encode("utf-8"))

    result = intervals_from_csv(file_input, EventPayloadType.IMPORT_CAPACITY_LIMIT)

    assert len(result) == 2
    assert result[0].payload.values == (10.0,)
    assert result[1].payload.values == (20.0,)


def test_intervals_from_csv_with_quotes() -> None:
    """Test intervals_from_csv with quoted values."""
    csv_content = (
        '"2023-01-01T10:00:00+01:00","2023-01-01T11:00:00+01:00","10"\n'
        '"2023-01-01T11:00:00+01:00","2023-01-01T12:00:00+01:00","20"'
    )
    file_input = io.BytesIO(csv_content.encode("utf-8"))

    result = intervals_from_csv(file_input, EventPayloadType.IMPORT_CAPACITY_LIMIT)

    assert len(result) == 2
    assert result[0].payload.values == (10.0,)
    assert result[1].payload.values == (20.0,)


def test_intervals_from_csv_different_payload_types() -> None:
    """Test intervals_from_csv with different payload types."""
    csv_content = "2023-01-01T10:00:00+01:00,2023-01-01T11:00:00+01:00,10"
    file_input = io.BytesIO(csv_content.encode("utf-8"))

    # Test with different payload types
    for payload_type in [
        EventPayloadType.IMPORT_CAPACITY_LIMIT,
        EventPayloadType.EXPORT_CAPACITY_LIMIT,
        EventPayloadType.PRICE,
    ]:
        result = intervals_from_csv(file_input, payload_type)
        assert result[0].payload.type == payload_type
        file_input.seek(0)  # Reset file pointer for next iteration


def test_intervals_from_csv_handles_empty_input() -> None:
    """Test intervals_from_csv with empty input."""
    csv_content = ""
    file_input = io.BytesIO(csv_content.encode("utf-8"))

    result = intervals_from_csv(file_input, EventPayloadType.IMPORT_CAPACITY_LIMIT)

    assert len(result) == 0
    assert isinstance(result, tuple)


def test_aggregate_targets_with_strings() -> None:
    """Test aggregate_targets."""
    data = [
        {"type": "IMPORT_CAPACITY_LIMIT", "value": "10"},
        {"type": "IMPORT_CAPACITY_LIMIT", "value": "20"},
        {"type": "EXPORT_CAPACITY_LIMIT", "value": "30"},
    ]
    result = aggregate_targets(data)
    assert result == (
        Target(type="IMPORT_CAPACITY_LIMIT", values=("10", "20")),
        Target(type="EXPORT_CAPACITY_LIMIT", values=("30",)),
    )


def test_aggregate_targets_with_integers() -> None:
    """Test aggregate_targets."""
    data = [
        {"type": "IMPORT_CAPACITY_LIMIT", "value": 10},
        {"type": "IMPORT_CAPACITY_LIMIT", "value": 20},
        {"type": "EXPORT_CAPACITY_LIMIT", "value": 30},
    ]
    result = aggregate_targets(data)
    assert result == (
        Target(type=EventPayloadType.IMPORT_CAPACITY_LIMIT, values=(10, 20)),
        Target(type=EventPayloadType.EXPORT_CAPACITY_LIMIT, values=(30,)),
    )


def test_split_targets() -> None:
    """Test split_targets."""
    targets = (
        Target(type="IMPORT_CAPACITY_LIMIT", values=("10", "20")),
        Target(type="EXPORT_CAPACITY_LIMIT", values=("30",)),
    )
    result = split_targets(targets)
    assert result == [
        {"type": "IMPORT_CAPACITY_LIMIT", "value": "10"},
        {"type": "IMPORT_CAPACITY_LIMIT", "value": "20"},
        {"type": "EXPORT_CAPACITY_LIMIT", "value": "30"},
    ]


def test_split_targets_with_integers() -> None:
    """Test split_targets."""
    targets = (
        Target(type="IMPORT_CAPACITY_LIMIT", values=(10, 20)),
        Target(type="EXPORT_CAPACITY_LIMIT", values=(30,)),
    )
    result = split_targets(targets)
    assert result == [
        {"type": "IMPORT_CAPACITY_LIMIT", "value": 10},
        {"type": "IMPORT_CAPACITY_LIMIT", "value": 20},
        {"type": "EXPORT_CAPACITY_LIMIT", "value": 30},
    ]


# Tests for update_payload_descriptors_list function


@pytest.fixture
def import_export_event() -> ValidatedEvent:
    """Create a mock ValidatedEvent with existing payload descriptors."""
    return ValidatedEvent(
        id=uuid.uuid4(),
        program_id=uuid.uuid4(),
        event_name="event-name",
        payload_descriptors=(
            EventPayloadDescriptor(payload_type=EventPayloadType.IMPORT_CAPACITY_LIMIT, units=Unit.KW),
            EventPayloadDescriptor(payload_type=EventPayloadType.EXPORT_CAPACITY_LIMIT, units=Unit.KW),
        ),
        intervals=(),
        targets=(),
        interval_period=None,
        priority=None,
    )


@pytest.fixture
def mock_event_empty_descriptors() -> ValidatedEvent:
    """Create a mock ValidatedEvent with no payload descriptors."""
    return ValidatedEvent(
        id=uuid.uuid4(),
        program_id=uuid.uuid4(),
        event_name="event-name",
        payload_descriptors=(),
        intervals=(),
        targets=(),
        interval_period=None,
        priority=None,
    )


@pytest.fixture
def price_descriptor() -> EventPayloadDescriptor:
    """Create a sample EventPayloadDescriptor for testing."""
    return EventPayloadDescriptor(
        payload_type=EventPayloadType.PRICE,
        units=Unit.KW,
        currency=ISO4217("EUR"),
    )


def test_update_payload_descriptors_list_updates_existing_descriptor(
    import_export_event: ValidatedEvent, price_descriptor: EventPayloadDescriptor
) -> None:
    """Test updating an existing payload descriptor."""
    result = update_payload_descriptors_list(
        import_export_event.payload_descriptors or (), EventPayloadType.IMPORT_CAPACITY_LIMIT, price_descriptor
    )

    # Should have same number of descriptors
    assert len(result) == 2

    # First descriptor should be updated with new descriptor data
    assert result[0].payload_type == EventPayloadType.PRICE
    assert result[0].units == Unit.KW
    assert result[0].currency == ISO4217("EUR")

    # Second descriptor should remain unchanged
    assert result[1].payload_type == EventPayloadType.EXPORT_CAPACITY_LIMIT
    assert result[1].units == Unit.KW


def test_update_payload_descriptors_list_returns_original_descriptors(
    import_export_event: ValidatedEvent, price_descriptor: EventPayloadDescriptor
) -> None:
    """Test fallback behavior when payload type is not found."""
    result = update_payload_descriptors_list(
        import_export_event.payload_descriptors or (), EventPayloadType.PRICE, price_descriptor
    )

    # Should return original descriptors
    assert len(result) == 2
    assert result[0].payload_type == EventPayloadType.IMPORT_CAPACITY_LIMIT
    assert result[0].units == Unit.KW
    assert result[1].payload_type == EventPayloadType.EXPORT_CAPACITY_LIMIT
    assert result[1].units == Unit.KW


def test_update_payload_descriptors_list_fallback_when_current_payload_type_is_none(
    import_export_event: ValidatedEvent, price_descriptor: EventPayloadDescriptor
) -> None:
    """Test fallback behavior when current_payload_type is None."""
    result = update_payload_descriptors_list(import_export_event.payload_descriptors or (), None, price_descriptor)  # type: ignore [arg-type]

    # Should return original descriptors
    assert len(result) == 2
    assert result[0].payload_type == EventPayloadType.IMPORT_CAPACITY_LIMIT
    assert result[0].units == Unit.KW
    assert result[1].payload_type == EventPayloadType.EXPORT_CAPACITY_LIMIT
    assert result[1].units == Unit.KW


def test_update_payload_descriptors_list_handles_empty_descriptors(
    mock_event_empty_descriptors: ValidatedEvent, price_descriptor: EventPayloadDescriptor
) -> None:
    """Test handling of events with no existing payload descriptors."""
    result = update_payload_descriptors_list(
        mock_event_empty_descriptors.payload_descriptors or (), EventPayloadType.IMPORT_CAPACITY_LIMIT, price_descriptor
    )

    # Should return original descriptors
    assert len(result) == 0


def test_update_payload_descriptors_list_preserves_original_list(
    import_export_event: ValidatedEvent, price_descriptor: EventPayloadDescriptor
) -> None:
    """Test that the original event's payload_descriptors list is not modified."""
    descriptors = import_export_event.payload_descriptors or ()
    original_descriptors = descriptors

    result = update_payload_descriptors_list(descriptors, EventPayloadType.IMPORT_CAPACITY_LIMIT, price_descriptor)

    # Original event should be unchanged
    assert import_export_event.payload_descriptors == original_descriptors

    # Result should be different
    assert result != original_descriptors
    assert result[0].payload_type == EventPayloadType.PRICE


def test_update_payload_descriptors_list_updates_second_descriptor(
    import_export_event: ValidatedEvent, price_descriptor: EventPayloadDescriptor
) -> None:
    """Test updating the second payload descriptor in the list."""
    descriptors = import_export_event.payload_descriptors or ()
    result = update_payload_descriptors_list(descriptors, EventPayloadType.EXPORT_CAPACITY_LIMIT, price_descriptor)

    # Should have same number of descriptors
    assert len(result) == 2

    # First descriptor should remain unchanged
    assert result[0].payload_type == EventPayloadType.IMPORT_CAPACITY_LIMIT
    assert result[0].units == Unit.KW

    # Second descriptor should be updated
    assert result[1].payload_type == EventPayloadType.PRICE
    assert result[1].units == Unit.KW
    assert result[1].currency == ISO4217("EUR")


def test_update_payload_descriptors_list_works_with_existing_event() -> None:
    """Test that the function works with ExistingEvent type as well."""
    # Create a mock ExistingEvent
    existing_event = ExistingEvent(
        id=str(uuid.uuid4()),
        programID=str(uuid.uuid4()),
        created_date_time=datetime(2023, 1, 1, 12, 0, 0, tzinfo=UTC),
        modification_date_time=datetime(2023, 1, 1, 12, 0, 0, tzinfo=UTC),
        event_name="test-existing-event",
        payload_descriptors=(
            EventPayloadDescriptor(payload_type=EventPayloadType.IMPORT_CAPACITY_LIMIT, units=Unit.KW),
        ),
        intervals=(
            OpenADRInterval(
                id=1,
                interval_period=None,
                payloads=(EventPayload(type=EventPayloadType.IMPORT_CAPACITY_LIMIT, values=(10,)),),
            ),
        ),
        targets=(),
        interval_period=None,
        priority=None,
    )

    descriptor = EventPayloadDescriptor(payload_type=EventPayloadType.PRICE, units=Unit.KW, currency=ISO4217("EUR"))

    current_payload_type = EventPayloadType.IMPORT_CAPACITY_LIMIT

    existing_descriptors = existing_event.payload_descriptors or ()
    result = update_payload_descriptors_list(existing_descriptors, current_payload_type, descriptor)

    # Should update the existing descriptor
    assert len(result) == 1
    assert result[0].payload_type == EventPayloadType.PRICE
    assert result[0].units == Unit.KW
    assert result[0].currency == ISO4217("EUR")


@pytest.fixture
def intervals_with_mixed_payloads() -> tuple[NormalizedInterval, ...]:
    """Create intervals with different payload types for testing."""
    return (
        NormalizedInterval(
            interval_period=IntervalPeriod(
                start=datetime(2023, 1, 1, 10, 0, tzinfo=_tz()), duration=timedelta(hours=1)
            ),
            payloads=(
                EventPayload(type=EventPayloadType.IMPORT_CAPACITY_LIMIT, values=(10,)),
                EventPayload(type=EventPayloadType.EXPORT_CAPACITY_LIMIT, values=(5,)),
            ),
        ),
        NormalizedInterval(
            interval_period=IntervalPeriod(
                start=datetime(2023, 1, 1, 11, 0, tzinfo=_tz()), duration=timedelta(hours=1)
            ),
            payloads=(
                EventPayload(type=EventPayloadType.IMPORT_CAPACITY_LIMIT, values=(20,)),
                EventPayload(type=EventPayloadType.EXPORT_CAPACITY_LIMIT, values=(30,)),
            ),
        ),
    )


def test_update_intervals_list_updates_matching_payload_type(
    intervals_with_mixed_payloads: tuple[NormalizedInterval, ...],
) -> None:
    """Test updating intervals with matching payload type."""
    result = update_intervals_list(
        intervals_with_mixed_payloads, EventPayloadType.IMPORT_CAPACITY_LIMIT, EventPayloadType.PRICE
    )

    # Should have same number of intervals
    assert len(result) == 2

    # First interval should have IMPORT_CAPACITY_LIMIT changed to PRICE
    assert len(result[0].payloads) == 2
    assert result[0].payloads[0].type == EventPayloadType.PRICE
    assert result[0].payloads[0].values == (10,)
    assert result[0].payloads[1].type == EventPayloadType.EXPORT_CAPACITY_LIMIT
    assert result[0].payloads[1].values == (5,)

    # Second interval should have IMPORT_CAPACITY_LIMIT changed to PRICE
    assert len(result[1].payloads) == 2
    assert result[1].payloads[0].type == EventPayloadType.PRICE
    assert result[1].payloads[0].values == (20,)
    assert result[1].payloads[1].type == EventPayloadType.EXPORT_CAPACITY_LIMIT
    assert result[1].payloads[1].values == (30,)


def test_update_intervals_list_returns_original_when_no_match(
    intervals_with_mixed_payloads: tuple[NormalizedInterval, ...],
) -> None:
    """Test that intervals are unchanged when payload type is not found."""
    result = update_intervals_list(intervals_with_mixed_payloads, EventPayloadType.SIMPLE, EventPayloadType.PRICE)

    # Should have same number of intervals
    assert len(result) == 2

    # All payloads should remain unchanged
    assert result[0].payloads[0].type == EventPayloadType.IMPORT_CAPACITY_LIMIT
    assert result[0].payloads[1].type == EventPayloadType.EXPORT_CAPACITY_LIMIT
    assert result[1].payloads[0].type == EventPayloadType.IMPORT_CAPACITY_LIMIT
    assert result[1].payloads[1].type == EventPayloadType.EXPORT_CAPACITY_LIMIT


def test_update_intervals_list_handles_empty_intervals() -> None:
    """Test handling of empty intervals tuple."""
    result: tuple[NormalizedInterval, ...] = update_intervals_list(
        (), EventPayloadType.IMPORT_CAPACITY_LIMIT, EventPayloadType.PRICE
    )

    # Should return empty tuple
    assert len(result) == 0
    assert result == ()


def test_update_intervals_list_handles_none_intervals() -> None:
    """Test handling of None intervals (converted to empty tuple)."""
    result: tuple[NormalizedInterval, ...] = update_intervals_list(
        None, EventPayloadType.IMPORT_CAPACITY_LIMIT, EventPayloadType.PRICE
    )

    # Should return empty tuple
    assert len(result) == 0
    assert result == ()


def test_update_intervals_list_preserves_original_intervals(
    intervals_with_mixed_payloads: tuple[Interval, ...],
) -> None:
    """Test that the original intervals tuple is not modified."""
    original_intervals = intervals_with_mixed_payloads

    result = update_intervals_list(
        intervals_with_mixed_payloads, EventPayloadType.IMPORT_CAPACITY_LIMIT, EventPayloadType.PRICE
    )

    # Original intervals should be unchanged
    assert original_intervals[0].payloads[0].type == EventPayloadType.IMPORT_CAPACITY_LIMIT
    assert original_intervals[0].payloads[1].type == EventPayloadType.EXPORT_CAPACITY_LIMIT
    assert original_intervals[1].payloads[0].type == EventPayloadType.IMPORT_CAPACITY_LIMIT
    assert original_intervals[1].payloads[1].type == EventPayloadType.EXPORT_CAPACITY_LIMIT

    # Result should be different
    assert result != original_intervals
    assert result[0].payloads[0].type == EventPayloadType.PRICE


def test_update_intervals_list_updates_multiple_matching_payloads() -> None:
    """Test updating intervals where multiple payloads match the old type."""
    intervals = (
        NormalizedInterval(
            interval_period=IntervalPeriod(
                start=datetime(2023, 1, 1, 10, 0, tzinfo=_tz()), duration=timedelta(hours=1)
            ),
            payloads=(
                EventPayload(type=EventPayloadType.IMPORT_CAPACITY_LIMIT, values=(10,)),
                EventPayload(type=EventPayloadType.IMPORT_CAPACITY_LIMIT, values=(15,)),
                EventPayload(type=EventPayloadType.EXPORT_CAPACITY_LIMIT, values=(5,)),
            ),
        ),
    )

    result = update_intervals_list(intervals, EventPayloadType.IMPORT_CAPACITY_LIMIT, EventPayloadType.PRICE)

    # Should have same number of intervals
    assert len(result) == 1

    # All IMPORT_CAPACITY_LIMIT payloads should be changed to PRICE
    assert len(result[0].payloads) == 3
    assert result[0].payloads[0].type == EventPayloadType.PRICE
    assert result[0].payloads[0].values == (10,)
    assert result[0].payloads[1].type == EventPayloadType.PRICE  # Changed
    assert result[0].payloads[1].values == (15,)
    assert result[0].payloads[2].type == EventPayloadType.EXPORT_CAPACITY_LIMIT
    assert result[0].payloads[2].values == (5,)


def test_update_intervals_list_preserves_interval_metadata() -> None:
    """Test that interval metadata (period, etc.) is preserved during update."""
    start_time = datetime(2023, 1, 1, 10, 0, tzinfo=_tz())
    duration = timedelta(hours=2)
    intervals = (
        NormalizedInterval(
            interval_period=IntervalPeriod(start=start_time, duration=duration),
            payloads=(EventPayload(type=EventPayloadType.IMPORT_CAPACITY_LIMIT, values=(10,)),),
        ),
    )

    result = update_intervals_list(intervals, EventPayloadType.IMPORT_CAPACITY_LIMIT, EventPayloadType.PRICE)

    # Interval metadata should be preserved
    assert result[0].interval_period.start == start_time
    assert result[0].interval_period.duration == duration
    assert result[0].payloads[0].type == EventPayloadType.PRICE
    assert result[0].payloads[0].values == (10,)
