# SPDX-FileCopyrightText: Contributors to openadr-gui<https://github.com/ElaadNL/openadr-gui>
#
# SPDX-License-Identifier: Apache-2.0

"""
A file for Huey tasks. Always use this file for tasks, so schedules have a stable entry point.

If you rename or move this file, all schedules must be updated to use the new entry point.
"""

import logging
from collections.abc import Callable
from datetime import datetime, timedelta
from functools import cache
from typing import cast

from django.utils import timezone
from huey import crontab
from huey.contrib.djhuey import db_periodic_task
from lockmgr.lockmgr import LockMgr
from openadr3_client.bl._client import BusinessLogicClient
from openadr3_client.models.event.event import ExistingEvent, NewEvent
from openadr3_client.models.program.program import ExistingProgram, NewProgram
from pydantic import ValidationError

from openadrgui.models.djangomodels import (
    DeploymentStatus,
    DjangoEventModel,
    DjangoProgramModel,
    ProgramDeploymentLogModel,
    ProgramDeploymentsModel,
)
from openadrgui.request_utils import RequestType, generic_handle_request_messages, get_bl_client
from openadrgui.services.repeat_program import repeat_intervals_for_coming_week
from openadrgui.types import BLClientLockError, DeploymentSkippedError, RepeatedProgramError

logger = logging.getLogger(__name__)


@cache
def bl_client() -> BusinessLogicClient:
    """
    Lazily create and cache the BL client.\

    This makes sure that the client is created at runtime, not at import time.
    """
    return get_bl_client()


def _handle_request_or_raise[T](
    request_callable: Callable[[], T], request_type: RequestType, *, auto_lock: bool = False
) -> T:
    """
    Wrap generic_handle_request_messages and raise RepeatedProgramError if errors exist.

    Args:
        request_callable: The callable to execute.
        request_type: The type of request.
        auto_lock: Whether to automatically acquire a lock.

    Returns:
        The result from the request.

    Raises:
        RepeatedProgramError: If errors occur during the request.

    """
    errors, result = generic_handle_request_messages(request_callable, request_type=request_type, auto_lock=auto_lock)
    if len(errors) > 0:
        raise RepeatedProgramError(errors)
    return cast("T", result)


def deploy_program(program_id: str) -> None:
    """
    Deploy a program.

    Args:
        program_id: The ID of the program to deploy.

    Raises:
        RepeatedProgramError: If the program is not valid.
        BLClientLockError: If the lock cannot be acquired.

    """
    from openadrgui.views.dp_views.program_views import validate_program  # avoid circular import  # noqa: PLC0415

    def _get_existing_events(program_id: str) -> tuple[ExistingEvent, ...]:
        return _handle_request_or_raise(
            lambda: bl_client().events.get_events(None, None, program_id),
            request_type=RequestType.READ,
            auto_lock=False,
        )

    def _create_or_get_program_id(existing_program: ExistingProgram | None, program: NewProgram) -> str:
        if not existing_program:
            new_program = _handle_request_or_raise(
                lambda: bl_client().programs.create_program(program),
                request_type=RequestType.CREATE,
                auto_lock=False,
            )
            return str(new_program.id)
        return str(existing_program.id)

    def _create_or_update_events(events: tuple[ExistingEvent | NewEvent, ...], program_id: str) -> None:
        """
        Create or update events.

        If an event is new, create it. If the event already exists, update it.
        """
        for event in events:
            if isinstance(event, NewEvent):
                new_event = event.model_copy(update={"program_id": program_id})

                def _create_event(new_event: NewEvent = new_event) -> None:
                    bl_client().events.create_event(new_event)

                _handle_request_or_raise(
                    _create_event,
                    request_type=RequestType.CREATE,
                    auto_lock=False,
                )
            else:
                existing_event: ExistingEvent = event

                def _update_event(existing_event: ExistingEvent = existing_event) -> None:
                    bl_client().events.update_event_by_id(existing_event.id, existing_event)

                _handle_request_or_raise(
                    _update_event,
                    request_type=RequestType.UPDATE,
                    auto_lock=False,
                )

    db_program = DjangoProgramModel.objects.get(id=program_id)
    db_events = tuple(DjangoEventModel.objects.filter(program_id=db_program).order_by("created_at"))
    program, validated_events = validate_program(db_program, db_events)

    with LockMgr("bl_operations", wait=60, expires=10):
        existing_programs = _handle_request_or_raise(
            lambda: bl_client().programs.get_programs(None, None),
            request_type=RequestType.CREATE,
            auto_lock=False,
        )

        existing_program = next(
            (program for program in existing_programs if program.program_name == db_program.program_name), None
        )

        existing_events = _get_existing_events(program_id) if existing_program else ()

        # First create new events to catch errors early (prevents invalid state in the database)
        # New event contains Dummy id.
        updated_or_new_events = repeat_intervals_for_coming_week(existing_events, validated_events)

        program_id = _create_or_get_program_id(existing_program, program)

        _create_or_update_events(updated_or_new_events, program_id)


def deploy_program_for_coming_week(deployment: ProgramDeploymentsModel) -> None:
    """Deploy a program for the coming week and logs the result."""

    def result_wrapper() -> tuple[DeploymentStatus, str | None]:
        logger.info("Deploying program %s", deployment.program.id)
        try:
            deploy_program(str(deployment.program.id))
        except DeploymentSkippedError as e:
            logger.exception("Deployment skipped")
            return (DeploymentStatus.SKIPPED, str(e))
        except (RepeatedProgramError, ValidationError) as e:
            logger.exception("Error deploying program")
            return (DeploymentStatus.FAILED, f"{type(e).__name__}: {e}")
        except BLClientLockError as e:
            logger.exception("Lock acquisition failed (waited 60 seconds)")
            return (DeploymentStatus.FAILED, f"{type(e).__name__}: {e}")
        else:
            return (DeploymentStatus.SUCCESS, None)

    deployment_log = ProgramDeploymentLogModel.objects.create(
        program_deployment=deployment,
        deployment_date=datetime.now(tz=timezone.get_current_timezone()),
        deployment_status=DeploymentStatus.IN_PROGRESS,
    )

    status, error_message = result_wrapper()

    deployment_log.deployment_status = status
    if error_message:
        deployment_log.deployment_error_message = error_message

    deployment_log.save()


@db_periodic_task(crontab(minute="0", hour="13", day_of_week="3"), name="schedule_program_deployment")  # type: ignore[misc]
def program_deployments_periodic_task() -> None:
    """
    Deploy program deployments on Wednesdays at 13:00.

    This will take a program that lasts exactly one week and deploy it for the coming week.

    If the program is invalid, the deployment will store an error in the deployment log
    and the deployment status will be set to "Failed".

    If the there are already events on the VTN for the coming week,
    the deployment will be skipped and the deployment status will be set to "Skipped".

    When the deployment is started, the deployment log will show the deployment status as "In Progress".
    If the deployment is successful, the deployment log will show the deployment status as "Success".
    """
    deployments = ProgramDeploymentsModel.objects.all()
    for deployment in deployments:
        deploy_program_for_coming_week(deployment)


@db_periodic_task(crontab(minute="0", hour="15", day_of_week="3"), name="delete_old_program_deployment_logs")  # type: ignore[misc]
def delete_old_program_deployment_logs_periodic_task() -> None:
    """Delete all deployment logs older than ~60 days on Wednesdays at 15:00."""
    ProgramDeploymentLogModel.objects.filter(
        deployment_date__lt=datetime.now(tz=timezone.get_current_timezone()) - timedelta(days=60)
    ).delete()
