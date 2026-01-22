# SPDX-FileCopyrightText: Contributors to openadr-gui<https://github.com/ElaadNL/openadr-gui>
#
# SPDX-License-Identifier: Apache-2.0

"""
Improved Event views for Django package interactions using the new base architecture.

This replaces the existing dp_views/event_views.py with a cleaner implementation
that uses the same patterns as the API views but works with Django models.
"""

import logging
import uuid
from functools import cached_property
from typing import Any, cast

from django.db.models import QuerySet
from django.forms import BaseForm
from django.http import HttpResponse
from django.urls import reverse

from openadrgui.forms.forms import DjangoEventForm
from openadrgui.models.djangomodels import DjangoEventModel, DjangoProgramModel, LogEntry
from openadrgui.views.base_views import (
    DjangoCreateView,
    DjangoDeleteView,
    DjangoEntityConfig,
    DjangoListView,
    DjangoUpdateView,
)
from openadrgui.views.types import Crumbs

logger = logging.getLogger(__name__)

# Event configuration for Django package views
EVENT_DP_CONFIG = DjangoEntityConfig(
    entity_name="event",
    entity_name_plural="events",
    log_entry_type=LogEntry.LogEntryType.EVENT,
    list_template="openadrgui/events.html",
    form_template="openadrgui/event_form.html",
    delete_partial_template="partials/events-delete-partial.html",
    form_class=DjangoEventForm,
)


def get_program_breadcrumb_base(program_id: uuid.UUID) -> list[tuple[str, str]]:
    """Helper function to get the base breadcrumb hierarchy for a program."""
    try:
        program = DjangoProgramModel.objects.get(id=program_id)
        program_name = program.program_name or "Unknown Program"
    except DjangoProgramModel.DoesNotExist:
        program_name = "Unknown Program"

    return [
        (f"Deployment Packages - {program_name}", reverse("programs")),
    ]


class EventDPListView(DjangoListView):
    """List events for a specific program from deployment package."""

    config = EVENT_DP_CONFIG

    def get_queryset(self, *args: Any, **kwargs: Any) -> QuerySet[DjangoEventModel]:  # noqa: ANN401
        """Filter events by program with optimizations."""
        program_id = self.kwargs["id"]
        qs = cast("QuerySet[DjangoEventModel]", super().get_queryset(*args, **kwargs))
        return qs.filter(program_id=program_id).select_related("program_id").order_by("id", "event_name")

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:  # noqa: ANN401
        """Add program-specific context."""
        return {
            **super().get_context_data(**kwargs),
            "program_events": False,
        }

    @cached_property
    def crumbs(self) -> Crumbs:
        """Override breadcrumbs to show hierarchy."""
        program_id = self.kwargs["id"]
        base_crumbs = get_program_breadcrumb_base(program_id)
        return [*base_crumbs, ("Events", None)]


class EventDPCreateView(DjangoCreateView):
    """Create a new event for deployment package."""

    config = EVENT_DP_CONFIG

    def get_success_url(self) -> str:
        """Return to events list for this program."""
        return reverse("dp-events", kwargs={"id": self.kwargs["id"]})

    def form_valid(self, form: BaseForm) -> HttpResponse:
        """Handle valid form submission."""
        form.cleaned_data["program_id"] = self.kwargs["id"]
        return super().form_valid(form)

    @cached_property
    def crumbs(self) -> Crumbs:
        """Override breadcrumbs to show hierarchy."""
        program_id = self.kwargs["id"]
        base_crumbs = get_program_breadcrumb_base(program_id)
        return [*base_crumbs, ("Events", reverse("dp-events", kwargs={"id": program_id})), ("Create Event", None)]


class EventDPUpdateView(DjangoUpdateView):
    """Update an event for deployment package."""

    config = EVENT_DP_CONFIG

    def get_success_url(self) -> str:
        """Return to events list for this program."""
        return reverse("dp-events", kwargs={"id": self.kwargs["dp_id"]})

    @cached_property
    def crumbs(self) -> Crumbs:
        """Override breadcrumbs to show hierarchy."""
        program_id = self.kwargs["dp_id"]
        base_crumbs = get_program_breadcrumb_base(program_id)
        try:
            program = DjangoEventModel.objects.get(id=self.kwargs["id"])
            program_name = program.event_name or "Unknown Event"
        except DjangoProgramModel.DoesNotExist:
            program_name = "Unknown Program"

        return [
            *base_crumbs,
            ("Events", reverse("dp-events", kwargs={"id": program_id})),
            (f"Edit Event - {program_name}", None),
        ]


class EventDPDeleteView(DjangoDeleteView):
    """Delete an event for deployment package."""

    config = EVENT_DP_CONFIG
    list_view = EventDPListView()

    def get_success_url(self) -> str:
        """Return to events list."""
        return reverse("dp-events", kwargs={"id": self.kwargs["dp_id"]})

    def get_list_context_data(self, **kwargs: Any) -> dict[str, Any]:  # noqa: ANN401
        """Override to mutate list context data."""
        return {**super().get_list_context_data(**kwargs), "id": self.kwargs["dp_id"]}
