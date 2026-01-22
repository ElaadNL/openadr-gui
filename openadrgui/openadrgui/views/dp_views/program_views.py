# SPDX-FileCopyrightText: Contributors to openadr-gui<https://github.com/ElaadNL/openadr-gui>
#
# SPDX-License-Identifier: Apache-2.0

import logging
import uuid
from functools import cached_property
from http import HTTPStatus
from typing import Any, cast

from django.contrib import messages
from django.core.exceptions import ValidationError as DjangoValidationError
from django.forms import BaseForm
from django.forms.models import model_to_dict
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views import View
from django.views.generic import FormView
from lockmgr.lockmgr import Locked, LockMgr
from openadr3_client.bl._client import BusinessLogicClient
from openadr3_client.models.event.event import NewEvent
from openadr3_client.models.program.program import NewProgram

from openadrgui.forms.forms import DjangoProgramForm, ScheduleDeploymentForm
from openadrgui.models.djangomodels import (
    DjangoEventModel,
    DjangoProgramModel,
    LogEntry,
    ProgramDeploymentLogModel,
    ProgramDeploymentsModel,
)
from openadrgui.models.models import ValidatedEvent
from openadrgui.request_utils import RequestType, get_bl_client, request_succeeded, request_to_messages
from openadrgui.services.repeat_program import check_dp_event_intervals_are_continuous
from openadrgui.tasks import deploy_program_for_coming_week
from openadrgui.types import HtmxHttpRequest, RepeatedProgramError
from openadrgui.utils import htmx_redirect, populate_flags
from openadrgui.views.base_views import (
    DjangoCreateView,
    DjangoDeleteView,
    DjangoEntityConfig,
    DjangoListView,
    DjangoUpdateView,
)
from openadrgui.views.types import Crumbs

logger = logging.getLogger(__name__)

# Program configuration for Django package views
PROGRAM_DP_CONFIG = DjangoEntityConfig(
    entity_name="program",
    entity_name_plural="programs",
    log_entry_type=LogEntry.LogEntryType.PROGRAM,
    # Templates
    list_template="openadrgui/programs.html",
    form_template="openadrgui/dp_program_form.html",
    delete_partial_template="partials/programs-delete-partial.html",
    form_class=DjangoProgramForm,
)


class ProgramDPListView(DjangoListView):
    """List programs for a specific deployment package."""

    config = PROGRAM_DP_CONFIG

    def _get_deploy_form(self, program_id: uuid.UUID) -> ScheduleDeploymentForm:
        """Get a deploy form for a program."""
        if ProgramDeploymentsModel.objects.filter(program=program_id).exists():
            return ScheduleDeploymentForm(initial={"repeat": True})
        return ScheduleDeploymentForm(initial={"repeat": False})

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:  # noqa: ANN401
        """Enhanced context with country display formatting."""
        # Get the base context with Django objects
        context = super().get_context_data(**kwargs)
        # Convert QuerySet to list of dictionaries for the flag utility
        programs_list = [
            {
                **model_to_dict(program),
                "id": str(program.id),
                "deploy_form": self._get_deploy_form(program.id),
                "deployment_status": (
                    deployment_log.deployment_status
                    if (
                        deployment_log := ProgramDeploymentLogModel.objects.filter(
                            program_deployment__program=program.id
                        )
                        .order_by("-deployment_date")
                        .first()
                    )
                    else None
                ),
            }
            for program in context[self.config.context_object_name]
        ]
        # Use utility function to populate flag information
        context[self.config.context_object_name] = populate_flags(programs_list)
        context["deployment_package"] = True
        return context


class ProgramDPCreateView(DjangoCreateView):
    """Create a new Django program."""

    config = PROGRAM_DP_CONFIG

    def get_success_url(self) -> str:
        """Return to programs list."""
        return reverse("programs")


class ProgramDPUpdateView(DjangoUpdateView):
    """Update a Django program."""

    config = PROGRAM_DP_CONFIG

    def get_success_url(self) -> str:
        """Return to programs list."""
        return reverse("programs")

    @cached_property
    def crumbs(self) -> Crumbs:
        """Override breadcrumbs to show hierarchy."""
        program_name = getattr(self.object, "name", "Unknown Program")
        return [
            ("Programs", reverse("programs")),
            (f"Edit Program - {program_name}", None),
        ]


class ProgramDPDeleteView(DjangoDeleteView):
    """Delete a Django program."""

    config = PROGRAM_DP_CONFIG
    list_view = ProgramDPListView()

    def get_success_url(self) -> str:
        """Return to programs list."""
        return reverse("programs")


def validate_program(
    program: DjangoProgramModel,
    events: tuple[DjangoEventModel, ...],
) -> tuple[NewProgram, tuple[ValidatedEvent, ...]]:
    """Validate the program."""
    if len(events) == 0:
        msg = "Cannot deploy program without events."
        raise DjangoValidationError(msg)

    # Check for events without intervals
    events_without_intervals = [
        event.event_name
        for event in events
        if event.intervals is None or (event.intervals is not None and len(event.intervals) == 0)
    ]
    if events_without_intervals:
        event_list = ", ".join(f"'{name}'" for name in events_without_intervals)
        msg = (
            f"Cannot deploy program. The following event(s) have no intervals: {event_list}. \n"
            "Add intervals to these events and try again."
        )
        raise DjangoValidationError(msg)

    # Check for events without payload descriptors
    events_without_payloads = [
        event.event_name for event in events if event.payload_descriptors is None or len(event.payload_descriptors) == 0
    ]
    if events_without_payloads:
        event_list = ", ".join(f"'{name}'" for name in events_without_payloads)
        msg = (
            f"Cannot deploy program. The following event(s) have no payload descriptors: {event_list}. \n"
            "Add payload descriptors to at least one event and try again."
        )
        raise DjangoValidationError(msg)

    new_program = NewProgram.model_validate(model_to_dict(program))

    validated_events = []
    for event in events:
        event_dict = model_to_dict(event)
        for i, interval in enumerate(event_dict["intervals"]):
            interval["id"] = i

        # Dummy UUID from https://www.rfc-editor.org/rfc/rfc9562.html#name-version-field
        # Program does not yet exist, must be replaced when deploying (see task)
        event_dict["program_id"] = "00000000-0000-4000-8000-000000000000"

        # Model validation should succeed. If it fails, let exception bubble up to give 500 error response.
        validated_event = ValidatedEvent.from_django_event_model(event)

        try:
            check_dp_event_intervals_are_continuous(validated_event)
        except RepeatedProgramError as e:
            msg = f"Error validating event intervals:\n {'\n'.join(e.errors)}"
            raise DjangoValidationError([msg]) from e

        validated_events.append(validated_event)
    return new_program, tuple(validated_events)


class ScheduledProgramDeploymentView(FormView[ScheduleDeploymentForm]):
    """Schedule a deployment of a program."""

    request: HtmxHttpRequest
    template_name = "partials/programs-partial.html#schedule-deployment-form"
    form_class = ScheduleDeploymentForm

    def form_valid(self, form: BaseForm) -> HttpResponse:
        """Schedule a deployment of a program."""
        db_program = get_object_or_404(DjangoProgramModel, id=self.kwargs["id"])
        db_events = tuple(DjangoEventModel.objects.filter(program_id=db_program.id).order_by("created_at"))

        if form.cleaned_data["repeat"] is True:
            try:
                _, _validated_events = validate_program(db_program, db_events)
            except (DjangoValidationError, RepeatedProgramError) as e:
                new_form = self.get_form()
                new_form.add_error(None, cast("DjangoValidationError", e).error_list)
                return self.form_invalid(new_form)

            deployment, created = ProgramDeploymentsModel.objects.get_or_create(
                program=db_program,
            )

            if created:
                deploy_program_for_coming_week(deployment)
                messages.success(
                    self.request,
                    (
                        "Deployment scheduled successfully.\n"
                        "First deployment has been started, check the 'Last deployments' to see if it was successful."
                    ),
                )
            else:
                messages.success(self.request, "Deployment already scheduled for this program. Nothing to do.")

        if form.cleaned_data["repeat"] is False:
            if not ProgramDeploymentsModel.objects.filter(program=db_program).exists():
                messages.success(self.request, "No deployments scheduled for this program. Nothing to do.")
                return self.render_success()
            deployment = ProgramDeploymentsModel.objects.get(program=db_program)
            deployment.delete()
            messages.success(self.request, "Scheduled deployment cancelled.")

        return self.render_success()

    def form_invalid(self, form: BaseForm) -> HttpResponse:
        """Handle invalid form data."""
        return render(
            self.request,
            self.template_name,
            status=HTTPStatus.UNPROCESSABLE_CONTENT,
            context=self.get_context_data(deploy_form=form),
        )

    def render_success(self) -> HttpResponse:
        """Render the success response."""
        return htmx_redirect(self.request, reverse("programs"))

    def render_error(self) -> HttpResponse:
        """Render the error response."""
        return render(
            self.request, self.template_name, status=HTTPStatus.INTERNAL_SERVER_ERROR, context=self.get_context_data()
        )

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:  # noqa: ANN401
        """Context data for the deploy program view."""
        context = super().get_context_data(**kwargs)
        context["program"] = {
            "id": self.kwargs["id"],
            "deploy_form": kwargs.get("deploy_form", self.get_form()),
        }
        return context


class DeployProgramView(View):
    """Deploy a program."""

    @cached_property
    def client(self) -> BusinessLogicClient:
        """
        Lazily create the BL client.

        This must not run at import/class-definition time because Django imports URLconfs and view modules during
        management commands (e.g. `migrate`) as part of system checks.
        """
        return get_bl_client()

    def post(self, request: HtmxHttpRequest, **kwargs: Any) -> HttpResponse:  # noqa: ANN401
        """Deploy a program."""
        program = get_object_or_404(DjangoProgramModel, id=kwargs["id"])
        events = tuple(DjangoEventModel.objects.filter(program_id=program.id).order_by("created_at"))
        try:
            new_program, new_events = validate_program(program, events)
        except (DjangoValidationError, RepeatedProgramError) as e:
            for error in cast("DjangoValidationError", e).messages:
                messages.error(request, error)
            return htmx_redirect(request, reverse("programs"))
        return self._deploy_program(request, new_program, new_events)

    def _deploy_program(
        self, request: HtmxHttpRequest, program: NewProgram, events: tuple[ValidatedEvent, ...]
    ) -> HttpResponse:
        try:
            with LockMgr("bl_operations", expires=10):
                result = request_to_messages(
                    request,
                    lambda: self.client.programs.create_program(program),
                    request_type=RequestType.CREATE,
                    auto_lock=False,
                )
                if not request_succeeded(result):
                    return htmx_redirect(request, reverse("programs"))
                created_program, _ = result

                for event in events:
                    event.program_id = uuid.UUID(created_program.id)

                for event in events:

                    def create_event_request(event_to_create: ValidatedEvent = event) -> Any:  # noqa: ANN401
                        # Serialize UUIDs to strings at the API boundary.
                        event_data = event_to_create.model_dump(mode="json")
                        return self.client.events.create_event(NewEvent.model_validate(event_data))

                    _, success = request_to_messages(
                        request,
                        create_event_request,
                        request_type=RequestType.CREATE,
                        auto_lock=False,
                    )
                    if not success:
                        return htmx_redirect(request, reverse("programs"))

                messages.success(request, f"Program deployed successfully as program ID: {created_program.id}")
                return htmx_redirect(request, reverse("programs"))
        except Locked:
            logger.exception("BL client is locked")
            messages.error(request, "Somebody else is already using the VTN. Please try again in a few seconds.")
            return htmx_redirect(request, reverse("programs"))
