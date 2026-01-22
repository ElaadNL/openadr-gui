# SPDX-FileCopyrightText: Contributors to openadr-gui<https://github.com/ElaadNL/openadr-gui>
#
# SPDX-License-Identifier: Apache-2.0

ARG UV_MAJOR_VERSION=0.9
ARG PYTHON_VERSION=3.13
ARG NODE_MAJOR_VERSION=22

ARG DEBIAN_VERSION=trixie

FROM ghcr.io/astral-sh/uv:${UV_MAJOR_VERSION}-python${PYTHON_VERSION}-${DEBIAN_VERSION}-slim

ARG NODE_MAJOR_VERSION
ENV DEBIAN_FRONTEND=noninteractive

# Install some useful CLI tools
RUN apt-get update \
    && apt-get install -y \
        curl \
        git \
        jq \
        less \
        lsof \
        nano \
        htop \
        zip \
        bash-completion \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Install curl, then install nodejs and psycopg build deps
RUN curl -sL https://deb.nodesource.com/setup_${NODE_MAJOR_VERSION}.x | bash - \
    && apt-get install -y --no-install-recommends nodejs libpq-dev python3-dev gcc \
    && apt-get clean && \
    rm -rf /var/lib/apt/lists/*
