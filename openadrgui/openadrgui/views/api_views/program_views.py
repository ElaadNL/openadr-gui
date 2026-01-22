# SPDX-FileCopyrightText: Contributors to openadr-gui<https://github.com/ElaadNL/openadr-gui>
#
# SPDX-License-Identifier: Apache-2.0

import logging
from functools import cached_property
from typing import Any

from django.urls import reverse
from openadr3_client.models.program.program import DeletedProgram, ExistingProgram, ProgramUpdate

from openadrgui.forms.forms import ProgramForm
from openadrgui.models.djangomodels import LogEntry, ProgramDeploymentsModel
from openadrgui.request_utils import RequestType, request_succeeded, request_to_messages
from openadrgui.utils import populate_flags
from openadrgui.views.base_views import (
    APIDeleteView,
    APIListView,
    APIUpdateView,
    EntityConfig,
)
from openadrgui.views.types import Crumbs

logger = logging.getLogger(__name__)

# Program configuration for API views
PROGRAM_API_CONFIG = EntityConfig(
    entity_name="program",
    entity_name_plural="programs",
    log_entry_type=LogEntry.LogEntryType.PROGRAM,
    # Templates
    list_template="openadrgui/programs.html",
    form_template="openadrgui/program_form.html",
    delete_partial_template="partials/programs-delete-partial.html",
    form_class=ProgramForm,
)


class ProgramListView(APIListView[ExistingProgram]):
    """List programs from API."""

    config = PROGRAM_API_CONFIG

    def get_api_objects(self, **kwargs: Any) -> tuple[ExistingProgram, ...]:  # noqa: ARG002, ANN401
        """Get all programs from API."""
        return self.client.programs.get_programs(None, None)

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:  # noqa: ANN401
        """Enhanced context with country display formatting and deployment status."""
        context = super().get_context_data(**kwargs)

        # Prefetch all deployed program names in a single query for efficiency
        deployed_program_names = set(
            ProgramDeploymentsModel.objects.select_related("program").values_list("program__program_name", flat=True)
        )

        # Convert programs to dictionaries and add flag information
        all_programs = context[self.config.context_object_name]
        programs_with_flags = populate_flags([program.model_dump() for program in all_programs])

        # Separate programs into deployed and non-deployed lists
        context["programs"] = [
            program for program in programs_with_flags if program["program_name"] not in deployed_program_names
        ]
        context["deployed_programs"] = [
            program for program in programs_with_flags if program["program_name"] in deployed_program_names
        ]

        return context


class ProgramAPIUpdateView(APIUpdateView[ExistingProgram]):
    """Update program via API."""

    config = PROGRAM_API_CONFIG

    def get_api_object(self, object_id: str) -> ExistingProgram:
        """Get program by ID from API."""
        return self.client.programs.get_program_by_id(object_id)

    def update_api_object(self, object_id: str, form_data: dict[str, Any]) -> ExistingProgram:
        """Update program via API."""
        # Get existing program and update it
        model = self.get_api_object(object_id)
        updated_model = model.update(ProgramUpdate(**form_data))
        return self.client.programs.update_program_by_id(object_id, updated_model)

    def get_success_url(self) -> str:
        """Return to programs list."""
        return reverse("programs")

    @cached_property
    def crumbs(self) -> Crumbs:
        """Override breadcrumbs to show hierarchy."""
        result = request_to_messages(
            self.request,
            lambda: self.get_api_object(self.kwargs["id"]),
            request_type=RequestType.READ,
        )
        if not request_succeeded(result):
            return [
                ("Programs", reverse("programs")),
                ("Edit Program", None),
            ]
        model, _ = result
        return [
            ("Programs", reverse("programs")),
            (f"Edit Program - {model.name}", None),
        ]


class ProgramAPIDeleteView(APIDeleteView[DeletedProgram]):
    """Delete program via API."""

    config = PROGRAM_API_CONFIG
    list_view = ProgramListView()

    def delete_api_object(self, object_id: str) -> DeletedProgram:
        """Delete program via API."""
        return self.client.programs.delete_program_by_id(object_id)

    def get_success_url(self) -> str:
        """Return to programs list."""
        return reverse("programs")
