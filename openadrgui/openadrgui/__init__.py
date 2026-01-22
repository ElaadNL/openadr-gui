# SPDX-FileCopyrightText: Contributors to openadr-gui<https://github.com/ElaadNL/openadr-gui>
#
# SPDX-License-Identifier: Apache-2.0

"""OpenADR GUI application initialization."""

import importlib.util

__all__ = ["mypy"]

mypy_package = importlib.util.find_spec("mypy")
if mypy_package:
    from .checks import mypy
