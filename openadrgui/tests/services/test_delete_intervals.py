# SPDX-FileCopyrightText: Contributors to openadr-gui<https://github.com/ElaadNL/openadr-gui>
#
# SPDX-License-Identifier: Apache-2.0

import uuid
from datetime import datetime, timedelta, tzinfo

import pytest
from django.utils import timezone
from openadr3_client.models.common.unit import Unit
from openadr3_client.models.event.event_payload import EventPayload, EventPayloadDescriptor, EventPayloadType
from openadrgui.models.models import Interval, IntervalPeriod, ValidatedEvent
from openadrgui.services.delete_intervals import delete_intervals, delete_payload_descriptor

# Fixtures for testing


def _tz() -> tzinfo:
    return timezone.get_current_timezone()


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
def intervals_with_mixed_payloads() -> tuple[Interval, ...]:
    """Create intervals with mixed payload types in each interval for testing."""
    return (
        Interval(
            interval_period=IntervalPeriod(
                start=datetime(2023, 1, 1, 10, 0, tzinfo=_tz()), duration=timedelta(hours=1)
            ),
            payloads=(
                EventPayload(type=EventPayloadType.IMPORT_CAPACITY_LIMIT, values=(10,)),
                EventPayload(type=EventPayloadType.EXPORT_CAPACITY_LIMIT, values=(5,)),
            ),
        ),
        Interval(
            interval_period=IntervalPeriod(
                start=datetime(2023, 1, 1, 11, 0, tzinfo=_tz()), duration=timedelta(hours=1)
            ),
            payloads=(
                EventPayload(type=EventPayloadType.IMPORT_CAPACITY_LIMIT, values=(20,)),
                EventPayload(type=EventPayloadType.EXPORT_CAPACITY_LIMIT, values=(30,)),
            ),
        ),
    )


@pytest.fixture
def intervals_single_payload_type() -> tuple[Interval, ...]:
    """Create intervals where all payloads have the same type."""
    return (
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


# Tests for delete_payload_descriptor function


def test_delete_payload_descriptor_removes_matching_descriptor(
    import_export_event: ValidatedEvent,
) -> None:
    """Test deleting an existing payload descriptor."""
    result = delete_payload_descriptor(import_export_event.payload_descriptors, EventPayloadType.IMPORT_CAPACITY_LIMIT)

    # Should have one less descriptor
    assert len(result) == 1

    # Should only contain the EXPORT_CAPACITY_LIMIT descriptor
    assert result[0].payload_type == EventPayloadType.EXPORT_CAPACITY_LIMIT
    assert result[0].units == Unit.KW


def test_delete_payload_descriptor_removes_second_descriptor(
    import_export_event: ValidatedEvent,
) -> None:
    """Test deleting the second payload descriptor in the list."""
    result = delete_payload_descriptor(import_export_event.payload_descriptors, EventPayloadType.EXPORT_CAPACITY_LIMIT)

    # Should have one less descriptor
    assert len(result) == 1

    # Should only contain the IMPORT_CAPACITY_LIMIT descriptor
    assert result[0].payload_type == EventPayloadType.IMPORT_CAPACITY_LIMIT
    assert result[0].units == Unit.KW


def test_delete_payload_descriptor_returns_original_when_not_found(
    import_export_event: ValidatedEvent,
) -> None:
    """Test that original descriptors are returned when payload type is not found."""
    result = delete_payload_descriptor(import_export_event.payload_descriptors, EventPayloadType.PRICE)

    # Should return original descriptors unchanged
    assert len(result) == 2
    assert result[0].payload_type == EventPayloadType.IMPORT_CAPACITY_LIMIT
    assert result[1].payload_type == EventPayloadType.EXPORT_CAPACITY_LIMIT


def test_delete_payload_descriptor_raises_error_on_empty_list(
    mock_event_empty_descriptors: ValidatedEvent,
) -> None:
    """Test that ValueError is raised when trying to delete from empty list."""
    with pytest.raises(ValueError, match="Cannot delete a payload descriptor from an empty list"):
        delete_payload_descriptor(
            mock_event_empty_descriptors.payload_descriptors, EventPayloadType.IMPORT_CAPACITY_LIMIT
        )


def test_delete_payload_descriptor_handles_none_input() -> None:
    """Test that function handles None input gracefully."""
    with pytest.raises(ValueError, match="Cannot delete a payload descriptor from an empty list"):
        delete_payload_descriptor(None, EventPayloadType.IMPORT_CAPACITY_LIMIT)


def test_delete_payload_descriptor_preserves_original_list(
    import_export_event: ValidatedEvent,
) -> None:
    """Test that the original payload_descriptors list is not modified."""
    original_descriptors = import_export_event.payload_descriptors or ()

    result = delete_payload_descriptor(import_export_event.payload_descriptors, EventPayloadType.IMPORT_CAPACITY_LIMIT)

    # Original event should be unchanged
    assert import_export_event.payload_descriptors == original_descriptors
    assert len(original_descriptors) == 2

    # Result should be different
    assert result != original_descriptors
    assert len(result) == 1


def test_delete_payload_descriptor_removes_all_matching_descriptors() -> None:
    """Test deleting when multiple descriptors have the same payload type."""
    descriptors = (
        EventPayloadDescriptor(payload_type=EventPayloadType.IMPORT_CAPACITY_LIMIT, units=Unit.KW),
        EventPayloadDescriptor(payload_type=EventPayloadType.IMPORT_CAPACITY_LIMIT, units=Unit.KWH),
        EventPayloadDescriptor(payload_type=EventPayloadType.EXPORT_CAPACITY_LIMIT, units=Unit.KW),
    )

    result = delete_payload_descriptor(descriptors, EventPayloadType.IMPORT_CAPACITY_LIMIT)

    # Should remove both IMPORT_CAPACITY_LIMIT descriptors
    assert len(result) == 1
    assert result[0].payload_type == EventPayloadType.EXPORT_CAPACITY_LIMIT


# Tests for delete_intervals function


def test_delete_intervals_removes_matching_payloads(
    intervals_with_mixed_payloads: tuple[Interval, ...],
) -> None:
    """Test deleting payloads with matching payload type from intervals."""
    result = delete_intervals(intervals_with_mixed_payloads, EventPayloadType.IMPORT_CAPACITY_LIMIT)

    # Should have same number of intervals
    assert len(result) == 2

    # Each interval should only have EXPORT_CAPACITY_LIMIT payloads
    assert len(result[0].payloads) == 1
    assert result[0].payloads[0].type == EventPayloadType.EXPORT_CAPACITY_LIMIT
    assert result[0].payloads[0].values == (5,)

    assert len(result[1].payloads) == 1
    assert result[1].payloads[0].type == EventPayloadType.EXPORT_CAPACITY_LIMIT
    assert result[1].payloads[0].values == (30,)


def test_delete_intervals_removes_intervals_with_no_remaining_payloads(
    intervals_single_payload_type: tuple[Interval, ...],
) -> None:
    """Test that intervals are removed when all payloads are deleted."""
    result = delete_intervals(intervals_single_payload_type, EventPayloadType.IMPORT_CAPACITY_LIMIT)

    # Should have no intervals left since all payloads were removed
    assert len(result) == 0
    assert result == ()


def test_delete_intervals_returns_original_when_payload_type_not_found(
    intervals_with_mixed_payloads: tuple[Interval, ...],
) -> None:
    """Test that intervals are unchanged when payload type is not found."""
    result = delete_intervals(intervals_with_mixed_payloads, EventPayloadType.PRICE)

    # Should return original intervals unchanged
    assert len(result) == 2
    assert result[0].payloads[0].type == EventPayloadType.IMPORT_CAPACITY_LIMIT
    assert result[0].payloads[1].type == EventPayloadType.EXPORT_CAPACITY_LIMIT
    assert result[1].payloads[0].type == EventPayloadType.IMPORT_CAPACITY_LIMIT
    assert result[1].payloads[1].type == EventPayloadType.EXPORT_CAPACITY_LIMIT


def test_delete_intervals_raises_error_on_empty_list() -> None:
    """Test that ValueError is raised when trying to delete from empty intervals."""
    with pytest.raises(ValueError, match="Cannot delete intervals from an empty list"):
        delete_intervals((), EventPayloadType.IMPORT_CAPACITY_LIMIT)


def test_delete_intervals_handles_none_input() -> None:
    """Test that function handles None input gracefully."""
    with pytest.raises(ValueError, match="Cannot delete intervals from an empty list"):
        delete_intervals(None, EventPayloadType.IMPORT_CAPACITY_LIMIT)


def test_delete_intervals_preserves_original_intervals(
    intervals_with_mixed_payloads: tuple[Interval, ...],
) -> None:
    """Test that the original intervals tuple is not modified."""
    original_intervals = intervals_with_mixed_payloads

    result = delete_intervals(intervals_with_mixed_payloads, EventPayloadType.IMPORT_CAPACITY_LIMIT)

    # Original intervals should be unchanged
    assert original_intervals[0].payloads[0].type == EventPayloadType.IMPORT_CAPACITY_LIMIT
    assert original_intervals[0].payloads[1].type == EventPayloadType.EXPORT_CAPACITY_LIMIT
    assert original_intervals[1].payloads[0].type == EventPayloadType.IMPORT_CAPACITY_LIMIT
    assert original_intervals[1].payloads[1].type == EventPayloadType.EXPORT_CAPACITY_LIMIT

    # Result should be different
    assert result != original_intervals
    assert len(result[0].payloads) == 1  # One payload removed


def test_delete_intervals_preserves_interval_metadata() -> None:
    """Test that interval metadata (period, etc.) is preserved during deletion."""
    start_time = datetime(2023, 1, 1, 10, 0, tzinfo=_tz())
    duration = timedelta(hours=2)
    intervals = (
        Interval(
            interval_period=IntervalPeriod(start=start_time, duration=duration),
            payloads=(
                EventPayload(type=EventPayloadType.IMPORT_CAPACITY_LIMIT, values=(10,)),
                EventPayload(type=EventPayloadType.EXPORT_CAPACITY_LIMIT, values=(5,)),
            ),
        ),
    )

    result = delete_intervals(intervals, EventPayloadType.IMPORT_CAPACITY_LIMIT)

    # Interval metadata should be preserved
    assert len(result) == 1
    period = result[0].interval_period
    assert period is not None
    assert period.start == start_time
    assert period.duration == duration
    assert len(result[0].payloads) == 1
    assert result[0].payloads[0].type == EventPayloadType.EXPORT_CAPACITY_LIMIT


def test_delete_intervals_handles_multiple_matching_payloads() -> None:
    """Test deleting intervals where multiple payloads match the type to delete."""
    intervals = (
        Interval(
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

    result = delete_intervals(intervals, EventPayloadType.IMPORT_CAPACITY_LIMIT)

    # Should have same number of intervals
    assert len(result) == 1

    # All IMPORT_CAPACITY_LIMIT payloads should be removed
    assert len(result[0].payloads) == 1
    assert result[0].payloads[0].type == EventPayloadType.EXPORT_CAPACITY_LIMIT
    assert result[0].payloads[0].values == (5,)


def test_delete_intervals_mixed_intervals_some_completely_removed() -> None:
    """Test scenario where some intervals are completely removed and others are partially filtered."""
    intervals = (
        # This interval will be completely removed (only has IMPORT_CAPACITY_LIMIT)
        Interval(
            interval_period=IntervalPeriod(
                start=datetime(2023, 1, 1, 10, 0, tzinfo=_tz()), duration=timedelta(hours=1)
            ),
            payloads=(EventPayload(type=EventPayloadType.IMPORT_CAPACITY_LIMIT, values=(10,)),),
        ),
        # This interval will be partially filtered (has both types)
        Interval(
            interval_period=IntervalPeriod(
                start=datetime(2023, 1, 1, 11, 0, tzinfo=_tz()), duration=timedelta(hours=1)
            ),
            payloads=(
                EventPayload(type=EventPayloadType.IMPORT_CAPACITY_LIMIT, values=(20,)),
                EventPayload(type=EventPayloadType.EXPORT_CAPACITY_LIMIT, values=(30,)),
            ),
        ),
    )

    result = delete_intervals(intervals, EventPayloadType.IMPORT_CAPACITY_LIMIT)

    # Should have only one interval left (the second one, partially filtered)
    assert len(result) == 1
    assert len(result[0].payloads) == 1
    assert result[0].payloads[0].type == EventPayloadType.EXPORT_CAPACITY_LIMIT
    assert result[0].payloads[0].values == (30,)
