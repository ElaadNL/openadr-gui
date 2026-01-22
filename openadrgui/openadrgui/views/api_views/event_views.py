# SPDX-FileCopyrightText: Contributors to openadr-gui<https://github.com/ElaadNL/openadr-gui>
#
# SPDX-License-Identifier: Apache-2.0

"""Views backed by the VTN API."""

import logging
from functools import cache, cached_property
from typing import Any

from django.http import HttpRequest
from django.urls import reverse
from openadr3_client.bl._client import BusinessLogicClient
from openadr3_client.models.event.event import DeletedEvent, EventUpdate, ExistingEvent

from openadrgui.forms.forms import EventForm
from openadrgui.models.djangomodels import LogEntry, ProgramDeploymentsModel
from openadrgui.request_utils import RequestType, get_bl_client, request_succeeded, request_to_messages
from openadrgui.types import HtmxHttpRequest
from openadrgui.views.base_views import (
    APIDeleteView,
    APIListView,
    APIUpdateView,
    EntityConfig,
)
from openadrgui.views.types import Crumbs

logger = logging.getLogger(__name__)

# Event configuration - clean and simple
EVENT_API_CONFIG = EntityConfig(
    entity_name="event",
    entity_name_plural="events",
    log_entry_type=LogEntry.LogEntryType.EVENT,
    # Templates
    list_template="openadrgui/events.html",
    form_template="openadrgui/event_form.html",
    delete_partial_template="partials/events-delete-partial.html",
    form_class=EventForm,
)


@cache
def bl_client() -> BusinessLogicClient:
    """
    Lazily create and cache the BL client.\

    This makes sure that the client is created at runtime, not at import time.
    """
    return get_bl_client()


def get_program_breadcrumb_base(request: HtmxHttpRequest | HttpRequest, program_id: str) -> list[tuple[str, str]]:
    """Helper function to get the base breadcrumb hierarchy for a program."""
    result = request_to_messages(
        request,
        lambda: bl_client().programs.get_program_by_id(program_id),
        request_type=RequestType.READ,
    )
    if not request_succeeded(result):
        return [("Programs", reverse("programs"))]
    program, _ = result
    program_name = program.name or "Unknown Program"
    return [(f"Programs - {program_name}", reverse("programs"))]


class EventAPIListView(APIListView[ExistingEvent]):
    """List events from API."""

    config = EVENT_API_CONFIG

    def get_api_objects(self, **kwargs: Any) -> tuple[ExistingEvent, ...]:  # noqa: ANN401
        """Get all events from API."""
        return self.client.events.get_events(None, None, kwargs.get("id"))

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:  # noqa: ANN401
        """Add program-specific context and check if events belong to deployed programs."""
        context = super().get_context_data(**kwargs)

        deployed_program_names = set(
            ProgramDeploymentsModel.objects.select_related("program").values_list("program__program_name", flat=True)
        )

        program_id = self.kwargs["id"]
        result = request_to_messages(
            self.request,
            lambda: bl_client().programs.get_program_by_id(program_id),
            request_type=RequestType.READ,
        )
        if request_succeeded(result):
            program, _ = result
            program_is_deployed = program.name in deployed_program_names
        else:
            program_is_deployed = False

        return {
            **context,
            "program_events": True,
            "program_is_deployed": program_is_deployed,
        }

    @cached_property
    def crumbs(self) -> Crumbs:
        """Override breadcrumbs to show hierarchy: Home > Programs > [Program Name] > Events > Create Event."""
        program_id = str(self.kwargs["id"])
        base_crumbs = get_program_breadcrumb_base(self.request, program_id)
        return [*base_crumbs, ("Events", None)]


class EventAPIUpdateView(APIUpdateView[ExistingEvent]):
    """Update event via API."""

    config = EVENT_API_CONFIG

    def get_api_object(self, object_id: str) -> ExistingEvent:
        """
        Get event by ID from API.

        Must be called from within a `request_to_messages` / `LockMgr('bl_operations')` context.
        """
        return self.client.events.get_event_by_id(object_id)

    def update_api_object(self, object_id: str, form_data: dict[str, Any]) -> ExistingEvent:
        """Update event via API."""
        # Get existing event and update it
        model = self.get_api_object(object_id)
        updated_model = model.update(EventUpdate(**form_data))
        return self.client.events.update_event_by_id(str(object_id), updated_model)

    def get_success_url(self) -> str:
        """Return to events list for this program."""
        return reverse("events", kwargs={"id": self.kwargs["program_id"]})

    @cached_property
    def crumbs(self) -> Crumbs:
        """Override breadcrumbs to show hierarchy."""
        program_id = str(self.kwargs["program_id"])
        base_crumbs = get_program_breadcrumb_base(self.request, program_id)
        event = self.existing_resource or None
        if event is None:
            return [*base_crumbs, ("Events", reverse("events", kwargs={"id": program_id})), ("Edit Event", None)]
        return [
            *base_crumbs,
            ("Events", reverse("events", kwargs={"id": program_id})),
            (f"Edit Event - {event.event_name}", None),
        ]


class EventAPIDeleteView(APIDeleteView[DeletedEvent]):
    """Delete event via API."""

    config = EVENT_API_CONFIG
    list_view = EventAPIListView()

    def delete_api_object(self, object_id: str) -> DeletedEvent:
        """Delete event via API."""
        return self.client.events.delete_event_by_id(object_id)

    def get_success_url(self) -> str:
        """Return to events list."""
        return reverse("index")

    def get_list_context_data(self, **kwargs: Any) -> dict[str, Any]:  # noqa: ANN401
        """Override to mutate list context data."""
        return {**super().get_list_context_data(**kwargs), "id": self.kwargs["program_id"]}
