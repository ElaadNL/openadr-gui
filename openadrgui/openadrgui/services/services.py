# SPDX-FileCopyrightText: Contributors to openadr-gui<https://github.com/ElaadNL/openadr-gui>
#
# SPDX-License-Identifier: Apache-2.0

import io
import logging
from collections.abc import Hashable, Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from typing import IO, Any, TypedDict

import chardet
import numpy as np
import numpy.typing as npt
import pandas as pd
from django.utils import timezone
from openadr3_client.models.common.interval import Interval as VtnInterval
from openadr3_client.models.common.interval_period import IntervalPeriod as VtnIntervalPeriod
from openadr3_client.models.event.event_payload import EventPayload, EventPayloadDescriptor, EventPayloadType
from pydantic import ValidationError

from openadrgui.models.models import IntervalCSV, IntervalPeriod, NormalizedInterval, SinglePayloadInterval, Target
from openadrgui.types import CopyableInterval, IntervalModel, IntervalPeriodLike
from openadrgui.utils import dt_to_local_tz

logger = logging.getLogger(__name__)


class GraphIntervals(TypedDict):
    """Graph data returned by `intervals_to_graph`."""

    data: list[dict[str, Any]]
    is_decimated: bool


def normalize_intervals(
    event_interval: IntervalPeriodLike | None,
    intervals: Sequence[IntervalModel],
) -> tuple[NormalizedInterval, ...]:
    """Normalize intervals from continuous and seperated formats to a seperated format."""
    if event_interval is None:
        # Seperated format
        def _to_normalized_interval(interval: IntervalModel) -> NormalizedInterval:
            period = interval.interval_period
            if period is None:
                msg = "Separated-format interval missing interval_period"
                raise ValueError(msg)
            return NormalizedInterval(
                id=interval.id,
                interval_period=IntervalPeriod(
                    start=period.start,
                    duration=period.duration,
                    randomize_start=period.randomize_start,
                ),
                payloads=interval.payloads,
            )

        return tuple(_to_normalized_interval(interval) for interval in intervals)

    normalized = []
    if event_interval is not None:
        # Continuous format
        start_time = dt_to_local_tz(event_interval.start)
        duration = event_interval.duration
        current_time = start_time

        for interval in intervals:
            normalized.append(
                NormalizedInterval(
                    id=interval.id,
                    interval_period=IntervalPeriod(start=current_time, duration=duration),
                    payloads=interval.payloads,
                )
            )
            current_time = current_time + duration

    return tuple(normalized)


def to_single_payload_intervals(
    intervals: tuple[NormalizedInterval, ...], payload_filter: EventPayloadType
) -> tuple[SinglePayloadInterval, ...]:
    """Convert an interval to a single payload interval."""

    def get_single_payload_interval(interval: NormalizedInterval) -> SinglePayloadInterval:
        matching_payloads = [p for p in interval.payloads if p.type == payload_filter]

        if len(matching_payloads) > 1:
            msg = (
                f"Payloads may not contain multiple payloads with the same type of {payload_filter.value}, "
                f"got {len(matching_payloads)}"
            )
            raise ValueError(msg)

        return SinglePayloadInterval(
            interval_period=interval.interval_period,
            payload=EventPayload(type=payload_filter, values=matching_payloads[0].values),
        )

    result = tuple(
        get_single_payload_interval(interval)
        for interval in intervals
        if any(p.type == payload_filter for p in interval.payloads)
    )

    if not result:
        logger.warning("No intervals found with payload type %s", payload_filter)

    return result


def to_normalized_intervals(intervals: tuple[SinglePayloadInterval, ...]) -> tuple[NormalizedInterval, ...]:
    """Convert single payload intervals to normalized intervals."""
    return tuple(
        NormalizedInterval(
            interval_period=interval.interval_period,
            payloads=(interval.payload,),
        )
        for interval in intervals
    )


def intervals_to_graph(intervals: tuple[SinglePayloadInterval, ...]) -> GraphIntervals:
    """
    Convert interval periods to graph data points with smart decimation.

    Args:
        event_interval: The event interval to be used for the graph. Only for continuous format.
        intervals: the intervals to be converted to graph data.

    Returns:
        A dictionary with 'data' (list of time/value points) and 'was_decimated' (bool)

    Throws:
         a ValidationError if the intervals are not valid

    """
    formatted_data = []

    for interval in intervals:
        start_time = dt_to_local_tz(interval.interval_period.start)

        # GraphJS expects the x value to be ms since Unix epoch (parsing: false)
        time_label = start_time.timestamp() * 1000

        formatted_data.append({"x": time_label, "y": interval.payload.values[0]})  # noqa: PD011

    # Apply server-side decimation for large datasets
    original_length = len(formatted_data)
    decimated_data = _decimate_graph_intervals(formatted_data)
    is_decimated = len(decimated_data) < original_length

    return {"data": decimated_data, "is_decimated": is_decimated}


ONE_HOUR_MS = 60 * 60 * 1000
THIRTY_MINUTES_MS = 30 * 60 * 1000


def _decimate_graph_intervals(
    data: list[dict[str, Any]],
    small_dataset_limit: int = 2000,
    large_dataset_limit: int = 8000,
) -> list[dict[str, Any]]:
    """
    Reduce data points for large datasets using time-based sampling.

    Small datasets: No changes
    Medium datasets: Keep one point every 30 minutes
    Large datasets: Keep one point every hour

    Args:
        data: Time series data with 'x' (timestamp) and 'y' (value)
        small_dataset_limit: The limit for small datasets. Defaults to 2000.
        large_dataset_limit: The limit for large datasets. Defaults to 8000.

    Returns:
        Filtered data preserving first and last points

    """
    # No decimation needed for small datasets
    if len(data) <= small_dataset_limit:
        return data

    # Determine sampling interval based on data size
    sampling_interval_ms = ONE_HOUR_MS if len(data) > large_dataset_limit else THIRTY_MINUTES_MS

    decimated_points = []

    # Filter points that align with the sampling interval in absolute time
    for current_point in data:
        current_timestamp = current_point["x"]

        # Check if timestamp aligns with sampling interval boundaries
        # Use tolerance for floating point precision
        if abs(current_timestamp % sampling_interval_ms) < 1:
            decimated_points.append(current_point)

    # Always keep the last data point to preserve time range
    if len(data) > 1 and (not decimated_points or decimated_points[-1] != data[-1]):
        decimated_points.append(data[-1])

    return decimated_points


def curve_to_intervals(
    start_time: date, event_payload_type: EventPayloadType, curve_data: npt.NDArray[np.int_]
) -> tuple[SinglePayloadInterval, ...]:
    """Get intervals from curve data."""
    start_datetime = timezone.make_aware(datetime.combine(start_time, datetime.min.time())).astimezone(UTC)

    def interval_from_data(index: int, value: np.int64) -> SinglePayloadInterval:
        interval_start = start_datetime + timedelta(minutes=(index * 15))
        # Convert NumPy scalar types to native Python primitives to avoid
        # unintended coercions (e.g. large int64 -> float) when validating.
        python_value = int(value)
        return SinglePayloadInterval(
            interval_period=IntervalPeriod(start=interval_start, duration=timedelta(minutes=15)),
            payload=EventPayload(type=event_payload_type, values=(python_value,)),
        )

    intervals = [interval_from_data(idx, value) for idx, value in enumerate(curve_data)]

    return tuple(intervals)


def intervals_to_vtn_intervals(intervals: tuple[NormalizedInterval, ...]) -> tuple[VtnInterval[EventPayload[Any]], ...]:
    """
    Convert intervals to VTN intervals.

    Uses existing IDs if present, otherwise assigns sequential IDs starting from 0.
    """
    return tuple(
        VtnInterval(
            id=interval.id or i,
            interval_period=VtnIntervalPeriod(
                start=interval.interval_period.start,
                duration=interval.interval_period.duration,
                randomize_start=interval.interval_period.randomize_start,
            ),
            payloads=interval.payloads,
        )
        for i, interval in enumerate(intervals)
    )


def intervals_from_csv(
    file_input: IO[bytes], event_payload_type: EventPayloadType
) -> tuple[SinglePayloadInterval, ...]:
    """
    Get intervals from a CSV file.

    The CSV file should contain a single column of numeric values.
    Each value represents a 15-minute interval starting from midnight of the current day.

    Args:
        file_input: A CSV file in IO format
        event_payload_type: The type of event payload

    Returns:
        A tuple of SinglePayloadInterval objects

    """

    def to_single_payload_interval(row: Mapping[Hashable, object]) -> SinglePayloadInterval:
        """Convert a parsed CSV row into a SinglePayloadInterval."""
        try:
            interval = IntervalCSV.model_validate(row)
        except ValidationError as e:
            msg = "Invalid CSV row"
            raise ValueError(msg) from e
        return SinglePayloadInterval(
            interval_period=IntervalPeriod(
                start=interval.interval_start, duration=interval.interval_end - interval.interval_start
            ),
            payload=EventPayload(type=event_payload_type, values=(float(interval.payload_value),)),
        )

    try:
        file_input.seek(0)
        content: bytes = file_input.read()

        if content is None or content == b"":
            return ()

        encoding = chardet.detect(content[0:100])["encoding"]

        # Use pandas with the detected encoding for CSV parsing
        data_frame = pd.read_csv(
            io.BytesIO(content),
            sep=None,
            engine="python",
            header=None,
            names=["interval_start", "interval_end", "payload_value"],
            encoding=encoding,
            dtype=str,  # Keep all columns as strings to leave validation to pydantic
        )

        if data_frame.empty:
            return ()

        # Drop rows with NaN values
        data_frame = data_frame.dropna()

        if data_frame.empty:
            return ()

        rows = data_frame.to_dict("records")
        single_payload_intervals = [to_single_payload_interval(row) for row in rows]

    except (pd.errors.EmptyDataError, pd.errors.ParserError) as e:
        logger.exception("Error reading CSV file")
        msg = "Please use a valid CSV file with comma, semicolon, or pipe delimiter."
        raise ValueError(msg) from e
    return tuple(single_payload_intervals)


def aggregate_targets(data: list[dict[str, Any]]) -> tuple[Target[Any], ...]:
    """
    Get the targets from a formset.

    Args:
        data: List of dictionaries containing target data with 'type' and 'value' keys

    Returns:
        A tuple of Target objects where values are merged by type

    """
    type_to_values: dict[str, list[str]] = {}

    for item in data:
        if not item or not item.get("type") or not item.get("value"):
            continue
        type_name = item["type"]
        if type_name not in type_to_values:
            type_to_values[type_name] = []
        type_to_values[type_name].append(item["value"])

    # Create targets maintaining input order
    targets = [Target(type=t, values=tuple(v)) for t, v in type_to_values.items()]
    return tuple(targets)


def split_targets(targets: tuple[Target[Any], ...] | None) -> list[dict[str, Any]]:
    """
    Split the targets into a list of dictionaries.

    Args:
        targets: A tuple of Target objects where each Target has a type and list of values

    Returns:
        A list of dictionaries, each containing a single type and value pair

    """
    if targets is None:
        return []
    return [{"type": target.type, "value": value} for target in targets for value in target.values]  # noqa: PD011 false positive


def get_min_max_local_date(
    intervals: tuple[SinglePayloadInterval, ...],
) -> tuple[date, date] | tuple[None, None]:
    """Get the min and max date for the event. Output: (min_date, max_date)."""
    if len(intervals) == 0:
        return (None, None)
    min_date = min(interval.interval_period.start for interval in intervals)
    max_date = max(interval.interval_period.start + interval.interval_period.duration for interval in intervals)
    return (dt_to_local_tz(min_date).date(), dt_to_local_tz(max_date).date())


def update_payload_descriptors_list(
    payload_descriptors: tuple[EventPayloadDescriptor, ...],
    current_payload_type: EventPayloadType,
    descriptor: EventPayloadDescriptor,
) -> tuple[EventPayloadDescriptor, ...]:
    """Common logic to update payload descriptors list."""
    # Prevents errors when payload_descriptors is None despite being required
    existing_descriptors = payload_descriptors or ()

    if len(existing_descriptors) == 0:
        logger.debug("Existing descriptors are empty, returning existing descriptors")
        return existing_descriptors

    if current_payload_type is None:
        logger.warning("Current payload type is None, returning existing descriptors")
        return existing_descriptors

    # Check if there's a descriptor with the current_payload_type to replace
    if not any(payload_descriptor.payload_type == current_payload_type for payload_descriptor in existing_descriptors):
        logger.warning("Payload descriptor not found for payload type %s", current_payload_type)
        return existing_descriptors

    return tuple(
        descriptor if payload_descriptor.payload_type == current_payload_type else payload_descriptor
        for payload_descriptor in existing_descriptors
    )


def update_intervals_list[TInterval: CopyableInterval](
    intervals: tuple[TInterval, ...] | None,
    old_payload_type: EventPayloadType,
    payload_type: EventPayloadType,
) -> tuple[TInterval, ...]:
    """Common logic to update intervals list."""
    # Prevents errors when intervals is None despite being required
    existing_intervals = intervals or ()

    if len(existing_intervals) == 0:
        logger.debug("Existing intervals are empty, returning existing intervals")
        return existing_intervals

    return tuple(
        interval.model_copy(
            update={
                "payloads": tuple(
                    payload.model_copy(update={"type": payload_type}) if payload.type == old_payload_type else payload
                    for payload in interval.payloads
                )
            }
        )
        for interval in existing_intervals
    )
