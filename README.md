<!--
SPDX-FileCopyrightText: Contributors to openadr-gui<https://github.com/ElaadNL/openadr-gui>

SPDX-License-Identifier: Apache-2.0
-->

[![CodeQL Advanced](https://github.com/ElaadNL/openadr-gui/actions/workflows/codeql.yml/badge.svg)](https://github.com/ElaadNL/openadr-gui/actions/workflows/codeql.yml)
[![Python Default CI](https://github.com/ElaadNL/openadr-gui/actions/workflows/ci.yml/badge.svg)](https://github.com/ElaadNL/openadr-gui/actions/workflows/ci.yml)
![Python Version from PEP 621 TOML](https://img.shields.io/python/required-version-toml?tomlFilePath=https%3A%2F%2Fraw.githubusercontent.com%2FElaadNL%2Fopenadr-gui%2Frefs%2Fheads%2Fmain%2Fpyproject.toml)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Checked with mypy](https://www.mypy-lang.org/static/mypy_badge.svg)](https://mypy-lang.org/)

# OpenADR GUI

This repository holds all sourcefiles and deployment information for the ElaadNL OpenADR backend with GUI.

## Docker compose: local test of production dockerfile

First, start up the hydra related services. This will start up Hydra, create credentials and put them in your .env file

```sh
docker compose up hydra-migrate hydra bootstrap token-hook
```

Then, stop those containers (ctrl-c or docker compose down) and start the openadrgui, vtn and hydra containers. This will load the credentials from your .env file
```sh
docker compose up openadrgui caddy vtn db token-hook hydra
```

The application is ready when the db-seeding service is done executing (it will log "Database migrations and seeding done").

## Devcontainer

1. Open this folder in a devcontainer compatible IDE (E.G. VSCode, JetBrains, etc.). Opening the devcontainer will take quite a while. You can check in on the progress by clicking on the notification in the bottom left corner of the IDE.
2. Once running, open one terminal and run `npm run css:watch`. This will watch for changes in the CSS files and compile them to the dist folder.
3. Open another terminal and run `uv run python openadrgui/manage.py migrate`. This will perform any outstanding database migrations.
4. In a terminal window, run `uv run task dev`. This will start the Django server.
4. Open your browser and navigate to `http://localhost:8000`. You should see the OpenADR GUI.

## Development

1. Install [uv](https://docs.astral.sh/uv/). This tool replaces pip, pip-tools, pipx, poetry, pyenv, twine, virtualenv, and more. It also manages your python version, so you don't need tools like pyenv.
2. Make sure to have Node.js installed. Using a version manager like [nvm](https://github.com/nvm-sh/nvm) or [fnm](https://github.com/Schniz/fnm) is recommended. See the required version in the [package.json](package.json) file.

```sh
uv sync
uv run python openadrgui/manage.py migrate
```

4. Create a `.env` file in the root directory with the following variables. The
`SECRET_KEY` can be generated with the command shown below.

```
SECRET_KEY=
DEBUG=True
API_URL=http://vtn:3000
CLIENT_ID=
CLIENT_SECRET=
OIDC_RP_CLIENT_ID=
OIDC_RP_CLIENT_SECRET=
OIDC_OP_BASE_URL=
```

When configuring OpenID Connect (OIDC) you need the values from your OIDC
provider:

- **Azure Entra ID** – set `OIDC_OP_BASE_URL` to your tenant authority URL such
  as `https://login.microsoftonline.com/<tenant>/v2.0`. The GUI will fetch the
  actual authorization, token and userinfo endpoints from the
  `/.well-known/openid-configuration` document of that base URL. Provide the
  client ID and secret of your app registration in `OIDC_RP_CLIENT_ID` and
  `OIDC_RP_CLIENT_SECRET`.

- **Other providers** - For now, only Entra has been used for this application. The implementation should be fairly generic, but if something does not work, please file a bug report and feel free to expand the README.

Successful logins are stored as `LogEntry` records, so you can audit who has
logged in via the Django admin or directly from the database.

Generate a random secret with:

```sh
uv run python -c 'from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())'
```

```sh
uv run task runserver
```
## Development

To start the development server, run the following commands:

In one terminal:
```sh
npm run css:watch
```

In another terminal:
```sh
uv run task runserver
```

### Usage

Navigate to `https://localhost` for the GUI and `https://localhost/api` for the VTN API. When prompted that the website is insecure, proceed. You get the warning because the certificates are self-signed.

Firefox:

- "Warning: Potential Security Risk Ahead" -> "Advanced" -> "Accept the Risk and Continue"

Chrome:

- "Your connection is not private" -> "Advanced" -> "Proceed to localhost (unsafe)"

## Analysis tools

### Lint

```sh
uv run task lint
```

### Lint fix

```sh
uv run task lint-fix
```

## Stack

The OpenADR GUI stack was chosen with the following goals in mind:

- **Backend:**: The backend should be the driver of the application.
- **Frontend:**: The frontend logic needs to be as simple as possible, and the backend should be the driver of the application. Frontend styling should be flexible. A thing that follows from that, is that the project preferably shouldn't have a package.json.
- **Python:**: The backend should be written in Python, to enable developers with a Data Science background to easily contribute to the project.
- **Flexibility:**: The stack should not be too locked in to a specific framework.


OpenADR GUI uses the [Hypermedia Driven Architecture (HDA)](https://htmx.org/essays/hypermedia-driven-applications/) to build the GUI. HDA combines the simplicity & flexibility of traditional Multi-Page Applications (MPAs) with the better user experience of Single-Page Applications (SPAs). This means that, instead of the frontend recieving data, the frontend recieves HTML responses that are placed as is in the DOM. To achieve this, the GUI uses the following technologies:
- [HTMX](https://htmx.org/): A library that allows you to use HTML as your templating language and add interactivity to your pages without JavaScript.
- [Alpine.js](https://alpinejs.dev/): "Modern JQuery"; A lightweight and simple JavaScript framework that allows you to add interactivity to your pages without writing JavaScript: fills in the gaps where HTMX doesn't cover.
- [TailwindCSS](https://tailwindcss.com/) + [Flowbite](https://flowbite.com/): A utility-first CSS framework that allows you to build custom designs without writing custom CSS. Flowbite is a library of components that you can use to build your own design system.
    - [TailwindCSS Animated](https://www.tailwindcss-animated.com): A more complete library of animations for TailwindCSS. Use [The builder](https://www.tailwindcss-animated.com/configurator.html) to generate the classes for your animations. When using delays, add the class on x-init (see messages-partial.html).
- [Django-cotton](https://django-cotton.com/): A library that brings component-based design to Django.
- [Python](https://www.python.org/): The backend is written in Python and uses the [Django](https://www.djangoproject.com/) framework.
- [Poetry](https://python-poetry.org/): A tool for dependency management and packaging in Python.

## Helpfull material on HDA applications

- [This video](https://youtu.be/akd7u69k27k?si=oDyXmeNBSDbYVJvB) is a great introduction to the HDA approach. It uses DaisyUI instead of Flowbite and Django-template-partials instead of Django-cotton, but the principles are the same.
- [This essay](https://htmx.org/essays/hypermedia-friendly-scripting/) explains one of the things that you run into with HDA applications: how to do scripting/how to integrate "client-side-first" libraries. Especially this quote is useful:

> So scripting is a legitimate part a REST-ful system, in order to allow the creation of additional features not directly implemented within the underlying hypermedia, thus making a hypermedia (e.g. HTML) more extensible.

> A good example of this sort of feature is a rich-text editor: it might have an extremely sophisticated JavaScript model of the editor’s document, including selection information, highlighting information, code completion and so forth. However, this model should be isolated from the rest of the DOM and the rich text editor should expose its information to the DOM using standard hypermedia features. For example, it should use a hidden input to communicate the contents of the editor to the surrounding DOM, rather than requiring a JavaScript API call to get the content.

## Notes to self regarding AlpineJS
- When wanting to bind input values, use x-model.fill ([see here](https://github.com/alpinejs/alpine/pull/3423) and [here](https://alpinejs.dev/directives/model#fill).). Used in date_time_range_widget.html

## License

This project is licensed under the Apache-2.0 - see LICENSE for details.

## Licenses third-party libraries

This project includes third-party libraries, which are licensed under their own respective Open-Source licenses.
SPDX-License-Identifier headers are used to show which license is applicable. The concerning license files can be found in the LICENSES directory.
