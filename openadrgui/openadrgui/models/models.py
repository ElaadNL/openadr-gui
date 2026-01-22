# SPDX-FileCopyrightText: Contributors to openadr-gui<https://github.com/ElaadNL/openadr-gui>
#
# SPDX-License-Identifier: Apache-2.0

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Any

from openadr3_client.models.common.target import Target
from openadr3_client.models.event.event_payload import EventPayload, EventPayloadDescriptor
from pydantic import BaseModel as PydanticBaseModel
from pydantic import field_validator
from pydantic.alias_generators import to_camel
from pydantic.config import ConfigDict
from pydantic.types import AwareDatetime

from openadrgui.models.djangomodels import DjangoEventModel

__all__ = [
    "BaseModel",
    "EventPayload",
    "EventPayloadDescriptor",
    "Interval",
    "IntervalCSV",
    "IntervalPeriod",
    "NormalizedInterval",
    "SinglePayloadInterval",
    "Target",
    "TargetType",
    "ValidatedEvent",
]


class BaseModel(PydanticBaseModel):
    """Base model for all API models."""

    @field_validator("*")
    @classmethod
    def empty_str_to_none(cls, v: str) -> str | None:
        """Pydantic validator that converts empty strings to None."""
        if v == "":
            return None
        return v


class IntervalPeriod(BaseModel):
    """
    Defines temporal aspects of intervals.

    A duration of PT0S indicates instantaneous or infinity, depending on payloadType.

    Attributes:
        start (datetime): The start time of the interval.
        duration (timedelta): The duration of the interval.
            PT0S indicates instantaneous or infinity, depending on payloadType.
        randomize_start (timedelta | None): Optional randomization window for the start time.
            None indicates no randomization. Defaults to None.

    """

    start: datetime
    duration: timedelta
    randomize_start: timedelta | None = None

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
        frozen=True,  # Makes the model immutable and hashable
    )


class Interval(BaseModel):
    """Defines temporal aspects of intervals."""

    id: int | None = None
    interval_period: IntervalPeriod | None = None
    payloads: tuple[EventPayload[Any], ...]

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
    )


class SinglePayloadInterval(BaseModel):
    """Defines temporal aspects of intervals normalized to a single payload."""

    interval_period: IntervalPeriod
    payload: EventPayload[Any]

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
    )


class NormalizedInterval(BaseModel):
    """Defines temporal aspects of intervals normalized to the seperated format."""

    id: int | None = None
    interval_period: IntervalPeriod
    payloads: tuple[EventPayload[Any], ...]

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
    )


class ValidatedEvent(BaseModel):
    """Validated event."""

    id: uuid.UUID
    program_id: uuid.UUID
    event_name: str | None = None
    interval_period: IntervalPeriod | None = None
    intervals: tuple[Interval, ...] | None = None
    payload_descriptors: tuple[EventPayloadDescriptor, ...] | None = None
    priority: int | None = None
    targets: tuple[Target[Any], ...] | None = None

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
    )

    # reportDescriptors is not yet implemented.

    @classmethod
    def from_django_event_model(cls, event: DjangoEventModel) -> "ValidatedEvent":
        """
        Initialize the event from a Django model instance.

        Throws ValidationError if the event is not valid.
        """
        return cls.model_validate(
            {
                "id": event.id,
                "program_id": event.program_id.id,
                "event_name": event.event_name,
                "payload_descriptors": event.payload_descriptors,
                "interval_period": event.interval_period,
                "intervals": event.intervals,
                "targets": event.targets,
            }
        )


@dataclass
class IntervalCSV(BaseModel):
    """Interval CSV."""

    interval_start: AwareDatetime
    interval_end: AwareDatetime
    payload_value: float


class TargetType(Enum):
    """Target."""

    POWER_SERVICE_LOCATION = "POWER_SERVICE_LOCATION"
    SERVICE_AREA = "SERVICE_AREA"
    GROUP = "GROUP"
    RESOURCE_NAME = "RESOURCE_NAME"
    VEN_NAME = "VEN_NAME"
    EVENT_NAME = "EVENT_NAME"
    PROGRAM_NAME = "PROGRAM_NAME"
