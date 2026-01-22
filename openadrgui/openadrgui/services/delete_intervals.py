# SPDX-FileCopyrightText: Contributors to openadr-gui<https://github.com/ElaadNL/openadr-gui>
#
# SPDX-License-Identifier: Apache-2.0

from openadr3_client.models.event.event_payload import EventPayloadDescriptor, EventPayloadType

from openadrgui.types import CopyableInterval


def delete_payload_descriptor(
    payload_descriptors: tuple[EventPayloadDescriptor, ...] | None,
    payload_type: EventPayloadType,
) -> tuple[EventPayloadDescriptor, ...]:
    """Common logic to delete a payload descriptor."""
    existing_descriptors = payload_descriptors or ()

    if len(existing_descriptors) == 0:
        msg = "Cannot delete a payload descriptor from an empty list"
        raise ValueError(msg)

    return tuple(
        payload_descriptor
        for payload_descriptor in existing_descriptors
        if payload_descriptor.payload_type != payload_type
    )


def delete_intervals[TInterval: CopyableInterval](
    intervals: tuple[TInterval, ...] | None,
    payload_type: EventPayloadType,
) -> tuple[TInterval, ...]:
    """Common logic to delete intervals with payloads matching the payload type."""
    existing_intervals = intervals or ()

    if len(existing_intervals) == 0:
        msg = "Cannot delete intervals from an empty list"
        raise ValueError(msg)

    def filter_interval_payloads(interval: TInterval) -> TInterval | None:
        """Filter out payloads matching the payload_type, return None if no payloads remain."""
        remaining_payloads = tuple(payload for payload in interval.payloads if payload.type != payload_type)

        if remaining_payloads:
            return interval.model_copy(update={"payloads": remaining_payloads})
        return None

    return tuple(
        filtered_interval
        for interval in existing_intervals
        if (filtered_interval := filter_interval_payloads(interval)) is not None
    )
