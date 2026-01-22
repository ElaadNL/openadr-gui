# SPDX-FileCopyrightText: Contributors to openadr-gui<https://github.com/ElaadNL/openadr-gui>
#
# SPDX-License-Identifier: Apache-2.0

from django.http import HttpResponse
from django.shortcuts import redirect, render

from openadrgui.types import HtmxHttpRequest


def logged_out(request: HtmxHttpRequest) -> HttpResponse:
    """Logged out view."""
    if request.user.is_authenticated:
        return redirect("index")
    return render(request, "openadrgui/logged_out.html")
