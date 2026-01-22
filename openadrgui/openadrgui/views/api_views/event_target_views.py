# SPDX-FileCopyrightText: Contributors to openadr-gui<https://github.com/ElaadNL/openadr-gui>
#
# SPDX-License-Identifier: Apache-2.0

"""Views backed by the VTN API."""

import logging
from functools import cached_property
from typing import Any

from django.http import HttpResponse
from django.urls import reverse
from openadr3_client.bl._client import BusinessLogicClient
from openadr3_client.models.event.event import EventUpdate

from openadrgui.models.djangomodels import LogEntry, ProgramDeploymentsModel
from openadrgui.models.models import Target
from openadrgui.request_utils import RequestType, get_bl_client, request_succeeded, request_to_messages
from openadrgui.types import HtmxHttpRequest
from openadrgui.views.api_views.event_views import get_program_breadcrumb_base
from openadrgui.views.base_views import APITargetsView, TargetsConfig
from openadrgui.views.utils import targets_form

logger = logging.getLogger(__name__)


class EventTargetsView(APITargetsView):
    """Targets view for API Event models."""

    config = TargetsConfig(
        entity_name="event",
        log_entry_type=LogEntry.LogEntryType.EVENT,
    )

    @cached_property
    def client(self) -> BusinessLogicClient:
        """
        Lazily create the BL client.

        This must not run at import/class-definition time because Django imports URLconfs and view modules during
        management commands (e.g. `migrate`) as part of system checks.
        """
        return get_bl_client()

    def get_targets(self) -> tuple[Target[Any], ...] | None:
        """Get the targets for the API Event."""
        return self.client.events.get_event_by_id(self.kwargs["id"]).targets

    def update_targets(self, targets: tuple[Target[Any], ...]) -> tuple[tuple[Target[Any], ...] | None, str | None]:
        """Update the API Event's targets."""
        event = self.client.events.get_event_by_id(str(self.kwargs["id"]))
        event = event.update(EventUpdate(targets=targets))
        return (
            self.client.events.update_event_by_id(str(self.kwargs["id"]), event).targets,
            event.name,
        )

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:  # noqa: ANN401
        """Get the context for rendering."""
        context = super().get_context_data(**kwargs)

        deployed_program_names = set(
            ProgramDeploymentsModel.objects.select_related("program").values_list("program__program_name", flat=True)
        )

        program_id = self.kwargs["program_id"]
        result = request_to_messages(
            self.request,
            lambda: self.client.programs.get_program_by_id(program_id),
            request_type=RequestType.READ,
        )

        if request_succeeded(result):
            program, _ = result
            program_is_deployed = bool(program.name in deployed_program_names)
            program_name = program.name
        else:
            program_is_deployed = False
            program_name = ""

        return {
            **context,
            "program_id": self.kwargs["program_id"],
            "id": self.kwargs["id"],
            "program_is_deployed": program_is_deployed,
            "program_name": program_name,
            "targets_form_url": reverse(
                "event-targets-form",
                kwargs={"program_id": self.kwargs["program_id"], "id": self.kwargs["id"]},
            ),
        }

    @cached_property
    def crumbs(self) -> list[tuple[str, str | None]]:
        """Define breadcrumbs for intervals view."""
        program_id = str(self.kwargs["program_id"])
        base_crumbs = get_program_breadcrumb_base(self.request, program_id)
        result = request_to_messages(
            self.request,
            lambda: self.client.events.get_event_by_id(self.kwargs["id"]),
            request_type=RequestType.READ,
        )
        if not request_succeeded(result):
            return [*base_crumbs, ("Events", reverse("events", kwargs={"id": program_id})), ("Intervals", None)]
        event, _ = result
        event_name = event.name or "Unknown Event"
        return [
            *base_crumbs,
            (f"Events - {event_name}", reverse("events", kwargs={"id": program_id})),
            ("Targets", None),
        ]

    def get_success_url(self) -> str:
        """Get the success URL."""
        return reverse("events", kwargs={"id": self.kwargs["program_id"]})


def event_targets_form(request: HtmxHttpRequest, **_kwargs: Any) -> HttpResponse:  # noqa: ANN401
    """Get the targets form."""
    return targets_form(request)
