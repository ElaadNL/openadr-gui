# SPDX-FileCopyrightText: Contributors to openadr-gui<https://github.com/ElaadNL/openadr-gui>
#
# SPDX-License-Identifier: Apache-2.0

import pycountry
from django.http import HttpResponse
from django.shortcuts import render

from openadrgui.forms.fields import Select
from openadrgui.forms.forms import SubdivisionsForm
from openadrgui.types import HtmxHttpRequest
from openadrgui.views.api_views.program_views import ProgramListView
from openadrgui.views.dp_views.program_views import ProgramDPListView


def programs(request: HtmxHttpRequest) -> HttpResponse:
    """View for programs that combines DP and API programs."""
    api_view = ProgramListView()
    dp_view = ProgramDPListView()

    # Setup the views properly
    api_view.setup(request)
    dp_view.setup(request)

    # Get context from both views
    api_context = api_view.get_context_data()
    dp_view.object_list = dp_view.get_queryset()
    dp_context = dp_view.get_context_data()

    combined_context = {
        "api": api_context,
        "dp": dp_context,
    }

    return render(request, dp_view.config.list_template, combined_context)


def get_subdivisions_choice_field(_request: HtmxHttpRequest, country: str | None = None) -> HttpResponse:
    """Render the subdivisions choice field for a given country."""
    form = SubdivisionsForm()

    if country is None:
        form.fields["principal_subdivision"].choices = [(Select.DISABLED, "Select a country first")]
        return HttpResponse(form["principal_subdivision"].as_widget())

    subdivisions = pycountry.subdivisions.get(country_code=country)  # type: ignore[no-untyped-call]

    choices = (
        [(Select.DISABLED, "Select a subdivision"), ("", "No subdivision")] + [(s.code, s.name) for s in subdivisions]
        if subdivisions
        else [("", "This country has no subdivisions")]
    )

    form.fields["principal_subdivision"].choices = choices

    return HttpResponse(form["principal_subdivision"].as_widget())
