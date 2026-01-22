# SPDX-FileCopyrightText: Contributors to openadr-gui<https://github.com/ElaadNL/openadr-gui>
#
# SPDX-License-Identifier: Apache-2.0

import logging
from functools import cached_property
from typing import Any

from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from openadr3_client.bl._client import BusinessLogicClient

from openadrgui.models.djangomodels import DjangoEventModel, DjangoProgramModel, LogEntry
from openadrgui.models.models import Target, ValidatedEvent
from openadrgui.request_utils import get_bl_client
from openadrgui.types import HtmxHttpRequest
from openadrgui.views.base_views import DbTargetsView, TargetsConfig
from openadrgui.views.dp_views.event_views import get_program_breadcrumb_base
from openadrgui.views.utils import targets_form

logger = logging.getLogger(__name__)


class TargetsView(DbTargetsView):
    """Targets view for Django Event models."""

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
        """Get the targets for the Django Event."""
        obj = get_object_or_404(DjangoEventModel, id=self.kwargs["id"])
        return ValidatedEvent.from_django_event_model(obj).targets

    def update_targets(self, targets: tuple[Target[Any], ...]) -> tuple[tuple[Target[Any], ...] | None, str | None]:
        """Update the Django Event's targets."""
        obj = get_object_or_404(DjangoEventModel, id=self.kwargs["id"])
        obj.targets = [target.model_dump() for target in targets]
        obj.save()
        return (ValidatedEvent.from_django_event_model(obj).targets, obj.name)

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:  # noqa: ANN401
        """Get the context for rendering."""
        context = super().get_context_data(**kwargs)
        return {
            **context,
            "targets_form_url": reverse(
                "dp-event-targets-form", kwargs={"dp_id": self.kwargs["dp_id"], "id": self.kwargs["id"]}
            ),
        }

    def get_success_url(self) -> str:
        """Get the success URL."""
        return reverse("dp-events", kwargs={"id": self.kwargs["dp_id"]})

    @cached_property
    def crumbs(self) -> list[tuple[str, str | None]]:
        """Override breadcrumbs to show hierarchy."""
        base_crumbs = get_program_breadcrumb_base(self.kwargs["dp_id"])
        try:
            program = DjangoEventModel.objects.get(id=self.kwargs["id"])
            program_name = program.event_name or "Unknown Event"
        except DjangoProgramModel.DoesNotExist:
            program_name = "Unknown Program"
        return [
            *base_crumbs,
            (f"Events - {program_name}", reverse("dp-events", kwargs={"id": self.kwargs["dp_id"]})),
            ("Targets", None),
        ]


def program_targets_form(request: HtmxHttpRequest, **_kwargs: Any) -> HttpResponse:  # noqa: ANN401
    """Get the targets form."""
    return targets_form(request)
