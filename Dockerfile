# SPDX-FileCopyrightText: Contributors to openadr-gui<https://github.com/ElaadNL/openadr-gui>
#
# SPDX-License-Identifier: Apache-2.0

ARG UV_MAJOR_VERSION=0.9
ARG PYTHON_VERSION=3.13
ARG NODE_MAJOR_VERSION=22

ARG DEBIAN_VERSION=trixie

# Build the virtual environment using poetry. 'Build' the CSS file with NPM and Tailwind.
FROM ghcr.io/astral-sh/uv:${UV_MAJOR_VERSION}-python${PYTHON_VERSION}-${DEBIAN_VERSION}-slim AS builder

ARG NODE_MAJOR_VERSION
ENV DEBIAN_FRONTEND=noninteractive

# Install curl, then install nodejs and psycopg build deps
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && curl -sL https://deb.nodesource.com/setup_${NODE_MAJOR_VERSION}.x | bash - \
    && apt-get install -y --no-install-recommends nodejs libpq-dev python3-dev gcc \
    && apt-get clean && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml uv.lock ./

RUN uv sync --frozen --no-dev

# Ensure subsequent `python` uses the virtual environment created by `uv sync`
ENV VIRTUAL_ENV=/app/.venv \
    PATH="/app/.venv/bin:$PATH"

COPY package.json package-lock.json ./

COPY openadrgui ./openadrgui

RUN npm install && npm run css:build

RUN python openadrgui/manage.py collectstatic --noinput

# Use a separate runtime image without uv or NPM to run the code
FROM python:${PYTHON_VERSION}-slim-${DEBIAN_VERSION} AS runtime

ENV DEBIAN_FRONTEND=noninteractive

# Install NPM and psycopg build deps
RUN apt-get update && apt-get install -y --no-install-recommends libpq5 \
    && apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Setup a non-root user
RUN groupadd --system --gid 999 nonroot \
 && useradd --system --gid 999 --uid 999 --create-home nonroot

WORKDIR /app

ENV VIRTUAL_ENV=/app/.venv \
    PATH="/app/.venv/bin:$PATH"

COPY --chown=nonroot:nonroot --from=builder ${VIRTUAL_ENV} ${VIRTUAL_ENV}

COPY --chown=nonroot:nonroot --from=builder /app/openadrgui ./openadrgui

# Copy entrypoint script
COPY docker-entrypoint.sh /app/docker-entrypoint.sh
RUN chmod +x /app/docker-entrypoint.sh

# Set environment variables to optimize Python
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Switch to non-root user
USER nonroot

WORKDIR /app/openadrgui

EXPOSE 80

ENTRYPOINT ["/app/docker-entrypoint.sh"]
