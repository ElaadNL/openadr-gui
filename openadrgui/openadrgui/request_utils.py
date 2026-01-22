# SPDX-FileCopyrightText: Contributors to openadr-gui<https://github.com/ElaadNL/openadr-gui>
#
# SPDX-License-Identifier: Apache-2.0

import enum
import logging
from collections.abc import Callable
from http import HTTPStatus
from typing import Any, Literal, TypeGuard, cast

import requests
from django.conf import settings
from django.contrib import messages
from django.forms import BaseForm
from django.http import HttpRequest
from lockmgr.lockmgr import Locked, LockMgr, is_locked
from openadr3_client.bl._client import BusinessLogicClient
from openadr3_client.bl.http_factory import BusinessLogicHttpClientFactory

from openadrgui.types import BLClientLockError, HtmxHttpRequest

logger = logging.getLogger(__name__)


class LockedAttributeProxy:
    """
    Proxy that enforces lock checking on all method calls.

    Uses __getattr__ for cleaner attribute delegation and functools.wraps
    for better function metadata preservation.
    """

    def __init__(self, target: Any) -> None:  # noqa: ANN401
        """
        Initialize the proxy.

        Args:
            target: The actual object to proxy

        """
        # Use object.__setattr__ to bypass our own __setattr__
        object.__setattr__(self, "_target", target)

    def __getattr__(self, name: str) -> Any:  # noqa: ANN401
        """
        Intercept attribute access to check lock and wrap returned objects.

        __getattr__ is only called for attributes that don't exist on the proxy itself,
        making it cleaner than __getattribute__.
        """
        target = object.__getattribute__(self, "_target")
        attr = getattr(target, name)

        # If it's a callable (method), wrap it with lock checking
        if callable(attr):

            def locked_method(*args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
                if not is_locked("bl_operations"):
                    msg = (
                        "BL operations require an active 'bl_operations' lock. "
                        "Wrap your operations in a LockMgr context manager:\n"
                        "    with LockMgr('bl_operations'):\n"
                        "        client.programs.get_programs(...)  # Lock enforced here"
                    )
                    raise BLClientLockError(msg)
                return attr(*args, **kwargs)

            return locked_method

        # If it's an object (like .programs, .events), wrap it recursively
        if hasattr(attr, "__dict__") or hasattr(attr, "__class__"):
            return LockedAttributeProxy(attr)

        return attr

    def __setattr__(self, name: str, value: Any) -> None:  # noqa: ANN401
        """Delegate attribute setting to the wrapped target."""
        if name == "_target":
            object.__setattr__(self, name, value)
        else:
            target = object.__getattribute__(self, "_target")
            setattr(target, name, value)

    def __repr__(self) -> str:
        """Return representation of the proxied object."""
        target = object.__getattribute__(self, "_target")
        return f"LockedProxy({target!r})"


def get_bl_client() -> BusinessLogicClient:
    """
    Get the BusinessLogicClient wrapped with lock enforcement.

    The returned client will check that a lock is active on every method call.
    This allows the client to be created at module/class level, but enforces
    that operations are only performed within a lock context.

    Returns:
        BusinessLogicClient: The client instance wrapped with lock checking

    Raises:
        BLClientLockError: If any operation is attempted without an active lock

    Example:
        @cached_property
        def client(self) -> BusinessLogicClient:
            \"\"\"
            Lazily create the BL client.

            This must not run at import/class-definition time because Django imports URLconfs and view modules during
            management commands (e.g. `migrate`) as part of system checks.
            \"\"\"
            return get_bl_client()

        # Operations require any lock to be active
        with LockMgr('bl_operations'):
            # Lock is automatically detected and checked on each method call
            programs = BL.programs.get_programs(None, None)
            program = BL.programs.create_program(program_data)
            events = BL.events.create_event(event_data)

    """
    client = BusinessLogicHttpClientFactory.create_http_bl_client(
        vtn_base_url=settings.API_URL,
        client_id=settings.OAUTH_CLIENT_ID,
        client_secret=settings.OAUTH_CLIENT_SECRET,
        token_url=settings.OAUTH_TOKEN_ENDPOINT,
        scopes=settings.OAUTH_SCOPES,
        audience="http://localhost:3000",
    )
    return LockedAttributeProxy(client)  # type: ignore[return-value]


class RequestType(enum.Enum):
    """Type of request to make."""

    READ = "read"
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"


def generic_handle_request_messages[T](
    request_method: Callable[[], T],
    request_type: RequestType,
    *,
    auto_lock: bool = True,
) -> tuple[list[str], T | None]:
    """
    Handle an API request and fill messages bag with human readable error messages.

    Args:
        request_method: Callable that executes the request and returns type T
        request_type: Type of request to make. Determines the messages for certain errors.
        auto_lock: Automatically uses a lock for the duration of the request.
            On by default, set to false if you want to lock for multiple requests.

    """
    errors = []
    response: T | None = None
    try:
        if auto_lock:
            try:
                with LockMgr("bl_operations", expires=10):
                    response = request_method()
            except Locked:
                logger.exception("BL client is locked")
                errors.append("Somebody else is already using the VTN. Please try again in a few seconds.")
                return errors, response
        else:
            response = request_method()
            return errors, response
    except requests.exceptions.ConnectionError:
        logger.exception("Unable to reach the API server")
        errors.append("Unable to reach the API server. Check whether the VTN is running and you can connect to it.")

    except requests.exceptions.Timeout:
        logger.exception("Request timed out")
        errors.append("The request timed out. Please try again later.")

    except requests.exceptions.HTTPError as e:
        logger.exception("HTTP error")

        # Try to extract detailed error information from the response
        detail = None
        try:
            response_data = e.response.json()
            detail = response_data.get("detail")
            # Log the full response for debugging
            if e.response.status_code == HTTPStatus.BAD_REQUEST:
                logger.info("Bad Request response body: %s", response_data)
        except (ValueError, KeyError, AttributeError):
            # If we can't parse JSON, log the raw response text
            logger.info("Response body (raw): %s", e.response.text)

        create_update_conflict_message = "Conflict: An entity with the same name already exists."
        delete_conflict_message = "Conflict: Make sure any child resources are deleted first."
        error_messages = {
            HTTPStatus.UNAUTHORIZED: "Unauthorized access. Please check your credentials and try again.",
            HTTPStatus.BAD_REQUEST: (
                f"Invalid request: {detail}" if detail else "Invalid request. Please check your input and try again."
            ),
            HTTPStatus.FORBIDDEN: (
                f"Forbidden: {detail}" if detail else "Forbidden: You are not authorized to access this resource."
            ),
            HTTPStatus.NOT_FOUND: "The requested resource was not found.",
            HTTPStatus.CONFLICT: (
                create_update_conflict_message
                if request_type in (RequestType.CREATE, RequestType.UPDATE)
                else delete_conflict_message
            ),
        }
        status = HTTPStatus(e.response.status_code)
        error_message = error_messages.get(
            status,
            f"Server error occurred ({status.name.title()}). Please try again later.",
        )
        errors.append(error_message)

    except Locked:
        logger.exception("BL client is locked")
        errors.append("Somebody else is already using the VTN. Please try again in a few seconds.")

    except Exception:
        logger.exception("Unexpected error")
        errors.append("An unexpected error occurred")

    return errors, response


def request_to_messages[T](
    request: HtmxHttpRequest | HttpRequest,
    request_method: Callable[[], T],
    request_type: RequestType,
    *,
    auto_lock: bool = True,
) -> tuple[T, Literal[True]] | tuple[None, Literal[False]]:
    """
    Handle an API request and fill messages bag with human readable error messages.

    Args:
        request: The HTMX HTTP request object
        request_method: Callable that executes the request and returns type T
        request_type: Type of request to make. Determines the messages for certain errors.
        auto_lock: Automatically uses a lock for the duration of the request.
            On by default, set to false if you want to lock for multiple requests.

    Returns:
        tuple[T, True] | tuple[None, False]: (response object if successful or None, success status)

    """
    errors, response = generic_handle_request_messages(request_method, request_type, auto_lock=auto_lock)
    for error in errors:
        messages.error(request, error)
    if errors:
        return None, False
    return cast("T", response), True


def request_succeeded[T](
    result: tuple[T, Literal[True]] | tuple[None, Literal[False]],
) -> TypeGuard[tuple[T, Literal[True]]]:
    """Type guard for request_to_messages results."""
    return result[1] is True


def request_to_form_errors[T](
    form: BaseForm,
    request_method: Callable[[], T],
    request_type: RequestType,
    *,
    auto_lock: bool = True,
) -> T | None:
    """
    Handle an API request and add errors to a Django form.

    Args:
        form: Django form to add errors to
        request_method: Callable that executes the request and returns type T
        request_type: Type of request to make. Determines the messages for certain errors.
        auto_lock: Automatically uses a lock for the duration of the request.
            On by default, set to false if you want to lock for multiple requests.

    Returns:
        tuple[T, True] | tuple[None, False]: (response object if successful or None, success status)

    """
    errors, response = generic_handle_request_messages(request_method, request_type, auto_lock=auto_lock)
    for error in errors:
        form.add_error(None, error)
    return response
