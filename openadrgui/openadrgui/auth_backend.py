# SPDX-FileCopyrightText: Contributors to openadr-gui<https://github.com/ElaadNL/openadr-gui>
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Protocol, cast

from mozilla_django_oidc.auth import OIDCAuthenticationBackend

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from django.db import models


class _UserLike(Protocol):
    username: str
    email: str
    first_name: str
    last_name: str

    def save(self, *args: object, **kwargs: object) -> None: ...


class PatchedOIDCAuthenticationBackend(OIDCAuthenticationBackend):  # type: ignore[misc]
    """Patched OIDC backend to use the sub claim for the username instead of a hash of the email claim."""

    def create_user(self, claims: dict[str, str]) -> models.Model:
        """Create a new user and log the login."""
        user = cast("models.Model", super().create_user(claims))
        self._update_user_fields(cast("_UserLike", user), claims)
        return user

    def update_user(self, user: models.Model, claims: dict[str, str]) -> models.Model:
        """Update an existing user and log the login."""
        updated = cast("models.Model", super().update_user(user, claims))
        self._update_user_fields(cast("_UserLike", updated), claims)
        return updated

    @staticmethod
    def _update_user_fields(user: _UserLike, claims: dict[str, str]) -> None:
        # Use the sub claim for the username instead of a hash of the email claim.
        # This is the stable identifier as per the OIDC spec.
        user.username = claims.get("sub", "")
        user.email = claims.get("preferred_username", claims.get("email", ""))
        user.first_name = claims.get("given_name", "")
        user.last_name = claims.get("family_name", "")
        user.save()

    def filter_users_by_claims(self, claims: dict[str, str]) -> models.QuerySet[models.Model]:
        """Match users based on the sub claim."""
        username = claims.get("sub")
        if not username:
            return cast("models.QuerySet[models.Model]", self.UserModel.objects.none())
        return cast("models.QuerySet[models.Model]", self.UserModel.objects.filter(username__exact=username))
