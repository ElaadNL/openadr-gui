# SPDX-FileCopyrightText: Contributors to openadr-gui<https://github.com/ElaadNL/openadr-gui>
#
# SPDX-License-Identifier: Apache-2.0

from django.http import HttpRequest, HttpResponse
from django.template import loader
from django.views.decorators.csrf import requires_csrf_token


@requires_csrf_token
def server_error(request: HttpRequest) -> HttpResponse:
    """
    500 error handler.

    Templates: `500.html`.
    """
    template = loader.get_template("errors/500.html")
    return HttpResponse(template.render({}, request), status=500)


@requires_csrf_token
def page_not_found(request: HttpRequest, _exception: Exception) -> HttpResponse:
    """
    404 error handler.

    Templates: `404.html`.
    """
    template = loader.get_template("errors/404.html")
    return HttpResponse(template.render({}, request), status=404)
