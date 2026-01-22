# SPDX-FileCopyrightText: Contributors to openadr-gui<https://github.com/ElaadNL/openadr-gui>
#
# SPDX-License-Identifier: Apache-2.0

import logging
from functools import cache, cached_property
from typing import Any

from django.http import HttpRequest
from django.urls import reverse
from openadr3_client.bl._client import BusinessLogicClient
from openadr3_client.models.ven.resource import DeletedResource, ExistingResource, NewResource, ResourceUpdate

from openadrgui.forms.forms import ResourceForm
from openadrgui.models.djangomodels import LogEntry
from openadrgui.request_utils import RequestType, get_bl_client, request_succeeded, request_to_messages
from openadrgui.types import HtmxHttpRequest
from openadrgui.views.base_views import (
    APICreateView,
    APIDeleteView,
    APIListView,
    APIUpdateView,
    EntityConfig,
)
from openadrgui.views.types import Crumbs

logger = logging.getLogger(__name__)

# Resource configuration for API views
RESOURCE_API_CONFIG = EntityConfig(
    entity_name="resource",
    entity_name_plural="resources",
    log_entry_type=LogEntry.LogEntryType.RESOURCE,
    # Templates
    list_template="openadrgui/resources.html",
    form_template="openadrgui/resource_form.html",
    delete_partial_template="partials/resources-delete-partial.html",
    form_class=ResourceForm,
)


@cache
def bl_client() -> BusinessLogicClient:
    """
    Lazily create and cache the BL client.\

    This makes sure that the client is created at runtime, not at import time.
    """
    return get_bl_client()


def get_ven_breadcrumb_base(request: HtmxHttpRequest | HttpRequest, ven_id: str) -> list[tuple[str, str]]:
    """Helper function to get the base breadcrumb hierarchy for a VEN."""
    result = request_to_messages(
        request,
        lambda: bl_client().vens.get_ven_by_id(ven_id),
        request_type=RequestType.READ,
    )
    if not request_succeeded(result):
        return [("VENs", reverse("index"))]
    ven, _ = result
    ven_name = ven.name or "Unknown Ven"
    return [(f"VENs - {ven_name}", reverse("index"))]


class ResourceAPIListView(APIListView[ExistingResource]):
    """List resources for a VEN from API."""

    config = RESOURCE_API_CONFIG

    def get_api_objects(self, **kwargs: Any) -> tuple[ExistingResource, ...]:  # noqa: ANN401
        """Get all resources for a VEN from API."""
        ven_id = kwargs.get("id")
        return self.client.vens.get_ven_resources(str(ven_id), None, None, None)

    @cached_property
    def crumbs(self) -> Crumbs:
        """Override breadcrumbs to show hierarchy."""
        ven_id = str(self.kwargs["id"])
        base_crumbs = get_ven_breadcrumb_base(self.request, ven_id)
        return [*base_crumbs, ("Resources", None)]


class ResourceAPICreateView(APICreateView[ExistingResource]):
    """Create a new resource for a VEN via API."""

    config = RESOURCE_API_CONFIG

    def create_api_object(self, form_data: dict[str, Any]) -> ExistingResource:
        """Create resource via API."""
        ven_id = str(self.kwargs["id"])
        resource = NewResource(**form_data, venID=ven_id)
        return self.client.vens.create_ven_resource(ven_id, resource)

    def get_success_url(self) -> str:
        """Return to resources list for this VEN."""
        return reverse("vens-resources", kwargs={"id": self.kwargs["id"]})

    @cached_property
    def crumbs(self) -> Crumbs:
        """Override breadcrumbs to show hierarchy."""
        ven_id = str(self.kwargs["id"])
        base_crumbs = get_ven_breadcrumb_base(self.request, ven_id)
        return [
            *base_crumbs,
            ("Resources", reverse("vens-resources", kwargs={"id": ven_id})),
            ("Create Resource", None),
        ]


class ResourceAPIUpdateView(APIUpdateView[ExistingResource]):
    """Update resource via API."""

    config = RESOURCE_API_CONFIG

    def get_api_object(self, object_id: str) -> ExistingResource:
        """Get resource by ID from API - overridden for VEN-resource relationship."""
        # Use ven_id from kwargs since resources are scoped to VENs
        ven_id = str(self.kwargs["ven_id"])
        return self.client.vens.get_ven_resource_by_id(ven_id, object_id)

    def update_api_object(self, object_id: str, form_data: dict[str, Any]) -> ExistingResource:
        """Update resource via API."""
        ven_id = str(self.kwargs["ven_id"])

        # Get existing resource and update it
        model = self.get_api_object(object_id)
        updated_model = model.update(ResourceUpdate(**form_data))
        return self.client.vens.update_ven_resource_by_id(ven_id, object_id, updated_model)

    def get_success_url(self) -> str:
        """Return to resources list for this VEN."""
        return reverse("vens-resources", kwargs={"id": self.kwargs["ven_id"]})

    @cached_property
    def crumbs(self) -> Crumbs:
        """Override breadcrumbs to show hierarchy."""
        ven_id = str(self.kwargs["ven_id"])
        base_crumbs = get_ven_breadcrumb_base(self.request, ven_id)
        result = request_to_messages(
            self.request,
            lambda: self.get_api_object(self.kwargs["id"]),
            request_type=RequestType.READ,
        )
        if not request_succeeded(result):
            return [
                *base_crumbs,
                ("Resources", reverse("vens-resources", kwargs={"id": ven_id})),
                ("Edit Resource", None),
            ]
        model, _ = result
        return [
            *base_crumbs,
            (f"Resources - {model.name}", reverse("vens-resources", kwargs={"id": ven_id})),
            ("Edit Resource", None),
        ]


class ResourceAPIDeleteView(APIDeleteView[DeletedResource]):
    """Delete resource via API."""

    config = RESOURCE_API_CONFIG
    list_view = ResourceAPIListView()

    def delete_api_object(self, object_id: str) -> DeletedResource:
        """Delete resource via API - overridden for VEN-resource relationship."""
        ven_id = str(self.kwargs["ven_id"])
        return self.client.vens.delete_ven_resource_by_id(ven_id, object_id)

    def get_success_url(self) -> str:
        """Return to resources list for this VEN."""
        return reverse("vens-resources", kwargs={"id": self.kwargs["ven_id"]})

    def get_list_context_data(self, **kwargs: Any) -> dict[str, Any]:  # noqa: ANN401
        """Override to mutate list context data."""
        return {**super().get_list_context_data(**kwargs), "id": self.kwargs["ven_id"]}
