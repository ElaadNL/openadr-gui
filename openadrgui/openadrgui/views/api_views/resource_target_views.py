# SPDX-FileCopyrightText: Contributors to openadr-gui<https://github.com/ElaadNL/openadr-gui>
#
# SPDX-License-Identifier: Apache-2.0

import logging
from functools import cached_property
from typing import Any

from django.http import HttpResponse
from django.urls import reverse
from openadr3_client.bl._client import BusinessLogicClient
from openadr3_client.models.ven.resource import ResourceUpdate

from openadrgui.models.djangomodels import LogEntry
from openadrgui.models.models import Target
from openadrgui.request_utils import RequestType, get_bl_client, request_succeeded, request_to_messages
from openadrgui.types import HtmxHttpRequest
from openadrgui.views.api_views.resource_views import get_ven_breadcrumb_base
from openadrgui.views.base_views import APITargetsView, TargetsConfig
from openadrgui.views.utils import targets_form

logger = logging.getLogger(__name__)


class ResourceTargetsView(APITargetsView):
    """Targets view for API Resource models."""

    config = TargetsConfig(
        entity_name="resource",
        log_entry_type=LogEntry.LogEntryType.RESOURCE,
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
        """Get the targets for the API Resource."""
        resource = self.client.vens.get_ven_resource_by_id(self.kwargs["ven_id"], self.kwargs["id"])
        return resource.targets if resource.targets else ()

    def update_targets(self, targets: tuple[Target[Any], ...]) -> tuple[tuple[Target[Any], ...] | None, str | None]:
        """Update the API Resource's targets."""
        resource = self.client.vens.get_ven_resource_by_id(str(self.kwargs["ven_id"]), str(self.kwargs["id"]))
        resource = resource.update(ResourceUpdate(targets=targets))
        return (
            self.client.vens.update_ven_resource_by_id(
                str(self.kwargs["ven_id"]),
                str(self.kwargs["id"]),
                resource,
            ).targets,
            resource.name,
        )

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:  # noqa: ANN401
        """Get the context for rendering."""
        context = super().get_context_data(**kwargs)
        return {
            **context,
            "ven_id": kwargs["ven_id"],
            "id": kwargs["id"],
            "targets_form_url": reverse(
                "resource-targets-form",
                kwargs={"ven_id": kwargs["ven_id"], "id": kwargs["id"]},
            ),
        }

    def get_success_url(self) -> str:
        """Get the success URL."""
        return reverse("vens-resources", kwargs={"id": self.kwargs["ven_id"]})

    @cached_property
    def crumbs(self) -> list[tuple[str, str | None]]:
        """Override breadcrumbs to show hierarchy."""
        base_crumbs = get_ven_breadcrumb_base(self.request, self.kwargs["ven_id"])
        result = request_to_messages(
            self.request,
            lambda: self.client.vens.get_ven_resource_by_id(self.kwargs["ven_id"], self.kwargs["id"]),
            request_type=RequestType.READ,
        )
        if not request_succeeded(result):
            return [
                *base_crumbs,
                ("Resources", reverse("vens-resources", kwargs={"id": self.kwargs["ven_id"]})),
                ("Targets", None),
            ]
        model, _ = result
        return [
            *base_crumbs,
            (f"Resources - {model.name}", reverse("vens-resources", kwargs={"id": self.kwargs["ven_id"]})),
            ("Targets", None),
        ]


def resource_targets_form(request: HtmxHttpRequest, **_kwargs: Any) -> HttpResponse:  # noqa: ANN401
    """Get the targets form."""
    return targets_form(request)
