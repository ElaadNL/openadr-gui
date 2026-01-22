# SPDX-FileCopyrightText: Contributors to openadr-gui<https://github.com/ElaadNL/openadr-gui>
#
# SPDX-License-Identifier: Apache-2.0

import logging
from contextlib import suppress
from http import HTTPStatus

from django.conf import settings
from django.contrib import messages
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.template.loader import render_to_string
from django.urls import NoReverseMatch, reverse
from django.utils.deprecation import MiddlewareMixin

from openadrgui.types import HtmxHttpRequest

logger = logging.getLogger(__name__)


def render_htmx_messages(request: HttpRequest) -> str:
    """Render message partial for HTMX requests if messages exist."""
    if messages.get_messages(request):
        return render_to_string("partials/messages-update-partial.html", request=request)
    return ""


class ServerError(Exception):
    """Exception used to simulate a server error (500)."""


class HtmxErrorMiddleware(MiddlewareMixin):
    """
    Middleware to convert 500-level errors to message partials for HTMX requests.

    Adds messages to error responses if there are none.
    Clears the response content, like the default 505 or 404 error pages
    Also adds the HX-Reswap none header to force OOB swap and preserve the target element.
    """

    def process_response(self, request: HttpRequest, response: HttpResponse) -> HttpResponse:
        """Process the response and convert 500-level errors to message partials for HTMX requests."""
        # Only process HTMX requests
        if not request.headers.get("HX-Request"):
            return response

        if response.status_code >= HTTPStatus.INTERNAL_SERVER_ERROR:
            # Add error message
            if not messages.get_messages(request):
                messages.error(
                    request, "An unexpected error occurred. Please try again or contact support if the issue persists."
                )
            # Return empty response but maintain the error status and force OOB swap
            response.content = ""
            response.headers["HX-Reswap"] = "none"
            return response

        # Form validation errors are handled by the form partial
        if response.status_code == HTTPStatus.UNPROCESSABLE_CONTENT:
            return response

        if response.status_code == HTTPStatus.NOT_FOUND:
            # If there is a 404 error with no messages, add a default error message
            if not messages.get_messages(request):
                messages.error(request, "Not found")
            response.content = ""
            response.headers["HX-Reswap"] = "none"
            return response

        return response


class HtmxBoostedMiddleware(MiddlewareMixin):
    """Middleware to handle HTMX boosted requests."""

    def process_request(self, request: HttpRequest) -> HttpResponse | None:
        """Process the request and handle HTMX boosted requests."""
        # Allow messages to be set on a redirect (see htmx_redirect in utils.py)
        if "messages" in request.session:
            for msg in request.session["messages"]:
                messages.add_message(request, msg[0], msg[1])
            request.session.pop("messages")
        return None


class HtmxMessagesMiddleware(MiddlewareMixin):
    """Middleware to append the message partial to HTMX responses with messages."""

    def process_response(self, request: HtmxHttpRequest, response: HttpResponse) -> HttpResponse:
        """Process the response and chain message partials for HTMX requests."""
        # Only process HTMX requests
        if not request.htmx:
            return response

        message_html = render_htmx_messages(request)
        if message_html:
            response.content = response.content + message_html.encode()

        return response


class LoginRequiredMiddleware(MiddlewareMixin):
    """Redirect anonymous users to ``settings.LOGIN_URL``."""

    def process_request(self, request: HttpRequest) -> HttpResponse | None:
        """Redirect to login unless requesting the login or OIDC callback URL."""
        if request.user.is_authenticated:
            return None

        # Check if this URL should be exempted from login requirements
        # This includes browser reload endpoints to prevent redirect loops
        if hasattr(settings, "OIDC_EXEMPT_URLS"):
            for exempt_pattern in settings.OIDC_EXEMPT_URLS:
                if exempt_pattern.match(request.path):
                    return None

        login_url = settings.LOGIN_URL
        if not login_url.startswith("/"):
            with suppress(NoReverseMatch):
                login_url = reverse(login_url)

        try:
            callback_url = reverse("oidc_authentication_callback")
        except NoReverseMatch:  # pragma: no cover - fallback if name cannot be reversed
            callback_url = "/oidc/callback/"

        if request.path in {login_url, callback_url}:
            return None

        current_url = request.get_full_path()
        redirect_url = f"{login_url}?next={current_url}"

        return redirect(redirect_url)
