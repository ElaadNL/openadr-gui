#!/bin/sh

# SPDX-FileCopyrightText: Contributors to openadr-gui<https://github.com/ElaadNL/openadr-gui>
#
# SPDX-License-Identifier: Apache-2.0

set -e

echo "Applying database migrations..."
python manage.py migrate --noinput

echo "Starting huey task scheduler consumer process..."
python manage.py run_huey &

echo "Starting Gunicorn..."
exec gunicorn --bind 0.0.0.0:80 --workers 3 openadrgui.wsgi:application
