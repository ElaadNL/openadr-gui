# SPDX-FileCopyrightText: Contributors to openadr-gui<https://github.com/ElaadNL/openadr-gui>
#
# SPDX-License-Identifier: Apache-2.0

import re
from typing import Any

from django.forms import BaseFormSet, formset_factory
from django.http import HttpResponse, QueryDict
from django.shortcuts import render

from openadrgui.forms.forms import TargetForm
from openadrgui.types import HtmxHttpRequest


def get_targets_formset_factory() -> type[BaseFormSet[TargetForm]]:
    """Get the targets formset factory."""
    # Trick to add the deleted column to the formset. The field is ignored in the template.
    return formset_factory(
        TargetForm,
        extra=1,
        can_delete=False,
        can_delete_extra=False,
    )


def dynamic_formset_helper(
    post_data: QueryDict,
    dynamic_form_id_prefix: str,
    formset: BaseFormSet[Any],
) -> QueryDict:
    """
    Helper function that correctly formats the formset data for a formset with dynamically added forms.

    INITIAL_FORMS is set to 0, as it is not relevant but required by the formset.

    Args:
        post_data: The POST data to be processed.
        dynamic_form_id_prefix: The prefix to be used for the dynamic form IDs. Not the same as the formset prefix.
        formset: The formset class to be used.

    """
    post_data = post_data.copy()
    counter = 0
    field_counter = 0

    # Replace form-__prefix__ with form-n in keys
    formset_prefix_regex = re.compile(rf"{formset.prefix}-\d+")
    dynamic_form_id_prefix_regex = re.compile(rf"{formset.prefix}-{dynamic_form_id_prefix}\d+")
    for key, values in list(post_data.lists()):
        if formset_prefix_regex.match(key) or dynamic_form_id_prefix_regex.match(key):
            # First remove the __new- prefix, then replace the number with the counter
            replacement = f"{formset.prefix}-{counter}"
            new_key = re.sub(dynamic_form_id_prefix_regex, replacement, key)
            new_key = re.sub(formset_prefix_regex, replacement, new_key)
            del post_data[key]
            post_data.setlist(new_key, values)
            if field_counter == len(formset.empty_form.base_fields) - 1:
                counter += 1
                field_counter = 0
            else:
                field_counter += 1

    post_data[f"{formset.prefix}-TOTAL_FORMS"] = str(counter)
    post_data[f"{formset.prefix}-INITIAL_FORMS"] = "0"
    return post_data


def targets_form(request: HtmxHttpRequest, **kwargs: Any) -> HttpResponse:  # noqa: ANN401
    """Get the targets form."""
    targets_formset: BaseFormSet[TargetForm] = get_targets_formset_factory()()

    context = {
        **kwargs,
        "form": targets_formset.empty_form,
    }

    return render(request, "openadrgui/targets.html#targets-form", context=context)
