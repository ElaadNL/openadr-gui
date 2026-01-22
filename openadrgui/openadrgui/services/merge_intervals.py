# SPDX-FileCopyrightText: Contributors to openadr-gui<https://github.com/ElaadNL/openadr-gui>
#
# SPDX-License-Identifier: Apache-2.0

"""Merge intervals."""

from itertools import groupby

from openadr3_client.models.event.event_payload import EventPayloadType

from openadrgui.models.models import NormalizedInterval, SinglePayloadInterval


class IntervalPeriodConflictError(ValueError):
    """Raised when intervals overlap but have different intervalPeriod specifications."""


def _intervals_conflict(interval1: NormalizedInterval, interval2: NormalizedInterval | SinglePayloadInterval) -> bool:
    """Check if two intervals overlap but have different intervalPeriod specifications."""
    if interval1.interval_period == interval2.interval_period:
        return False

    end1 = interval1.interval_period.start + interval1.interval_period.duration
    end2 = interval2.interval_period.start + interval2.interval_period.duration

    return interval1.interval_period.start < end2 and interval2.interval_period.start < end1


def _override_intervals(
    existing_intervals: tuple[NormalizedInterval, ...],
    new_intervals: tuple[NormalizedInterval, ...],
) -> tuple[NormalizedInterval, ...]:
    """Override the intervals of the same type as the new intervals with new intervals."""

    def _get_common_payload_type(intervals: tuple[NormalizedInterval, ...]) -> EventPayloadType:
        """Get the common payload type of the intervals."""
        unique_payload_types = {payload.type for p in intervals for payload in p.payloads}
        if len(unique_payload_types) != 1:
            msg = "All new intervals must have the same payload type."
            raise ValueError(msg)
        return unique_payload_types.pop()

    if not new_intervals:
        return existing_intervals

    common_payload_type = _get_common_payload_type(new_intervals)

    existing_intervals = tuple(
        interval
        for interval in existing_intervals
        for payload in interval.payloads
        if payload.type != common_payload_type
    )

    return existing_intervals + new_intervals


def merge_intervals(
    existing_intervals: tuple[NormalizedInterval, ...],
    new_intervals: tuple[SinglePayloadInterval, ...],
    *,
    override: bool = True,
) -> tuple[NormalizedInterval, ...]:
    """
    Merge existing intervals with new intervals.

    When intervals have the same intervalPeriod, their payloads are combined into a single interval.
    When intervals overlap but have different intervalPeriods, an error is raised.

    Args:
        existing_intervals: Tuple of existing normalized intervals
        new_intervals: Tuple of new single payload intervals to merge
        override: Whether to override the intervals of the same type as the new intervals with new intervals

    Returns:
        Merged tuple of all intervals with combined payloads where appropriate, sorted by start time

    Raises:
        IntervalPeriodConflictError: If overlapping intervals have different intervalPeriod specifications

    """
    normalized_new_intervals: tuple[NormalizedInterval, ...] = tuple(
        NormalizedInterval(
            interval_period=interval.interval_period,
            payloads=(interval.payload,),
        )
        for interval in new_intervals
    )

    conflicts = tuple(
        (existing, new)
        for new in normalized_new_intervals
        for existing in existing_intervals
        if _intervals_conflict(existing, new)
    )

    if conflicts:
        error_messages = tuple(
            f"Overlapping intervals may not have different intervalPeriod durations."
            f"Existing: start={existing.interval_period.start},"
            f"duration={existing.interval_period.duration},"
            f"randomize_start={existing.interval_period.randomize_start},"
            f"New: start={new.interval_period.start},"
            f"duration={new.interval_period.duration},"
            f"randomize_start={new.interval_period.randomize_start}."
            for existing, new in conflicts
        )
        raise IntervalPeriodConflictError("\n".join(error_messages))

    # Creates new dictionary with periods as keys and lists of intervals with the same period as values
    if override:
        all_intervals = _override_intervals(existing_intervals, normalized_new_intervals)
    else:
        all_intervals = existing_intervals + normalized_new_intervals

    interval_groups = {
        period: list(intervals)
        for period, intervals in groupby(
            # Groupby requires sorted input - sort by start time to group consecutive periods
            sorted(
                all_intervals,
                key=lambda x: (x.interval_period.start, x.interval_period.duration, x.interval_period.randomize_start),
            ),
            key=lambda x: x.interval_period,
        )
    }

    def _merge_group(group_intervals: list[NormalizedInterval]) -> NormalizedInterval:
        """Merge intervals in a group - return original if single, combine payloads if multiple."""
        if len(group_intervals) == 1:
            return group_intervals[0]

        return NormalizedInterval(
            id=None,
            interval_period=group_intervals[0].interval_period,
            payloads=tuple(payload for interval in group_intervals for payload in interval.payloads),
        )

    merged_intervals = [_merge_group(group) for group in interval_groups.values()]

    return tuple(sorted(merged_intervals, key=lambda interval: interval.interval_period.start))
