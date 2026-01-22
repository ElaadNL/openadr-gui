# SPDX-FileCopyrightText: Contributors to openadr-gui<https://github.com/ElaadNL/openadr-gui>
#
# SPDX-License-Identifier: Apache-2.0

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import UploadedFile
from django.core.validators import MaxValueValidator
from django.utils.translation import gettext as _


class MaxSizeValidator(MaxValueValidator):
    """
    Validator for the maximum size of a file.

    From: https://stackoverflow.com/a/54606500/11366805

    args:
        limit_value: int - The maximum size of the file in MB.

    """

    message = _("The file exceeds the maximum size of %(limit_value)s MB.")

    def __call__(self, value: UploadedFile) -> None:  # noqa: D102
        # get the file size as cleaned value
        cleaned = self.clean(value.size)
        params = {"limit_value": self.limit_value, "show_value": cleaned, "value": value}
        if self.compare(cleaned, self.limit_value * 1024 * 1024):  # convert limit_value from MB to Bytes
            raise ValidationError(self.message, code=self.code, params=params)
