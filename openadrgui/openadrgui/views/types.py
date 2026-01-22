# SPDX-FileCopyrightText: Contributors to openadr-gui<https://github.com/ElaadNL/openadr-gui>
#
# SPDX-License-Identifier: Apache-2.0

import uuid
from enum import StrEnum
from typing import TypedDict

from openadr3_client.models.event.event_payload import EventPayloadType

Crumb = tuple[str, str | None]
Crumbs = list[Crumb]


class NewEmptyTabs(StrEnum):
    """Information about a payload tab."""

    EMPTY = "Empty"
    ADD = "Add"


PayloadTab = NewEmptyTabs | EventPayloadType


class TabInfo(TypedDict):
    """Information about a payload tab."""

    type: PayloadTab
    active: bool
    display_name: str


class IdRequest(TypedDict):
    """Type for request kwargs containing an ID."""

    id: uuid.UUID


class EventIdRequest(TypedDict):
    """Type for request kwargs containing an event ID."""

    program_id: uuid.UUID
    event_id: uuid.UUID


class ApiEventIdRequest(TypedDict):
    """Type for request kwargs containing an API event ID."""

    program_id: uuid.UUID
    id: uuid.UUID
    payload_type: PayloadTab | None


class DpEventIdRequest(TypedDict):
    """Type for request kwargs containing an event ID."""

    dp_id: uuid.UUID
    id: uuid.UUID
    payload_type: PayloadTab | None
