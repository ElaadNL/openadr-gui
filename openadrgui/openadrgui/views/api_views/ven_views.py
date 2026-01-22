# SPDX-FileCopyrightText: Contributors to openadr-gui<https://github.com/ElaadNL/openadr-gui>
#
# SPDX-License-Identifier: Apache-2.0

"""Views backed by the VTN API."""

import logging
from functools import cached_property
from typing import Any

from django.urls import reverse
from openadr3_client.models.ven.ven import DeletedVen, ExistingVen, NewVen, VenUpdate

from openadrgui.forms.forms import VenForm
from openadrgui.models.djangomodels import LogEntry
from openadrgui.views.base_views import (
    APICreateView,
    APIDeleteView,
    APIListView,
    APIUpdateView,
    EntityConfig,
)
from openadrgui.views.types import Crumbs

logger = logging.getLogger(__name__)

# VEN configuration for API views
VEN_API_CONFIG = EntityConfig(
    entity_name="ven",
    entity_name_plural="vens",
    log_entry_type=LogEntry.LogEntryType.VEN,
    # Templates
    list_template="index.html",
    form_template="openadrgui/ven_form.html",
    delete_partial_template="partials/vens-delete-partial.html",
    form_class=VenForm,
)


class VenAPIListView(APIListView[ExistingVen]):
    """List VENs from API."""

    config = VEN_API_CONFIG

    def get_api_objects(self, **kwargs: Any) -> tuple[ExistingVen, ...]:  # noqa: ARG002, ANN401
        """Get all VENs from API."""
        return self.client.vens.get_vens(None, None, None)

    @cached_property
    def crumbs(self) -> Crumbs:
        """Override breadcrumbs to show hierarchy."""
        return []


class VenAPICreateView(APICreateView[ExistingVen]):
    """Create a new VEN via API."""

    config = VEN_API_CONFIG

    def create_api_object(self, form_data: dict[str, Any]) -> ExistingVen:
        """Create VEN via API."""
        return self.client.vens.create_ven(NewVen(**form_data))

    def get_success_url(self) -> str:
        """Return to VENs list."""
        return reverse("index")


class VenAPIUpdateView(APIUpdateView[ExistingVen]):
    """Update VEN via API."""

    config = VEN_API_CONFIG

    def get_api_object(self, object_id: str) -> ExistingVen:
        """Get VEN by ID from API."""
        return self.client.vens.get_ven_by_id(object_id)

    def update_api_object(self, object_id: str, form_data: dict[str, Any]) -> ExistingVen:
        """Update VEN via API."""
        # Get existing VEN and update it
        model = self.get_api_object(object_id)
        updated_model = model.update(VenUpdate(**form_data))
        return self.client.vens.update_ven_by_id(object_id, updated_model)

    def get_success_url(self) -> str:
        """Return to VENs list."""
        return reverse("index")


class VenAPIDeleteView(APIDeleteView[DeletedVen]):
    """Delete VEN via API."""

    config = VEN_API_CONFIG
    list_view = VenAPIListView()

    def delete_api_object(self, object_id: str) -> DeletedVen:
        """Delete VEN via API."""
        return self.client.vens.delete_ven_by_id(object_id)

    def get_success_url(self) -> str:
        """Return to VENs list."""
        return reverse("index")
