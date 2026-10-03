from django.contrib.auth.backends import ModelBackend
from django.db import IntegrityError, transaction

from apps.accounts.models import User
from apps.directory.ad_services import (
    ActiveDirectoryError,
    authenticate_ad_credentials,
    search_ad_users,
)
from apps.directory.identity_services import (
    InstitutionalIdentityError,
    resolve_institutional_identity,
)


class ApprovedUserModelBackend(ModelBackend):
    """Reject accounts that are inactive, unapproved, suspended, or expired."""

    def user_can_authenticate(self, user):
        return super().user_can_authenticate(user) and user.can_access_system


class ActiveDirectoryBackend(ApprovedUserModelBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        if not isinstance(username, str):
            return None
        identifier = username.strip()
        if not identifier or not isinstance(password, str) or password == "":
            return None

        try:
            if not authenticate_ad_credentials(identifier, password):
                return None
        except ActiveDirectoryError:
            return None

        try:
            ad_users = search_ad_users(identifier, limit=20)
        except ActiveDirectoryError:
            return None

        identifier_key = identifier.casefold()
        if "@" in identifier:
            ad_user = next(
                (
                    candidate
                    for candidate in ad_users
                    if isinstance(candidate.get("email"), str)
                    and candidate["email"].strip().casefold() == identifier_key
                ),
                None,
            )
        else:
            ad_user = next(
                (
                    candidate
                    for candidate in ad_users
                    if isinstance(candidate.get("username"), str)
                    and candidate["username"].strip().casefold() == identifier_key
                ),
                None,
            )

        if ad_user is None or ad_user.get("is_active") is not True:
            return None

        ad_email = ad_user.get("email")
        try:
            identity = resolve_institutional_identity(email=ad_email)
        except InstitutionalIdentityError:
            return None
        if identity is None or identity.get("is_active") is not True:
            return None

        ad_username = (ad_user.get("username") or "").strip().lower()
        email = (
            identity.get("email")
            or ad_user.get("email")
            or ""
        ).strip().lower()
        if not email or not ad_username:
            return None

        first_name = (
            (identity.get("first_name") or "").strip()
            or (ad_user.get("first_name") or "").strip()
        )
        last_name = (
            (identity.get("last_name") or "").strip()
            or (ad_user.get("last_name") or "").strip()
        )

        user = User.objects.filter(email__iexact=email).first()
        if user is None:
            user = User.objects.filter(username__iexact=ad_username).first()

        if user is not None:
            self._update_existing_user(
                user,
                identity,
                ad_username,
                first_name,
                last_name,
            )
            return user if self.user_can_authenticate(user) else None

        try:
            with transaction.atomic():
                user = User(
                    username=ad_username,
                    email=email,
                    first_name=first_name,
                    last_name=last_name,
                    id_personal=identity.get("id_personal"),
                    employee_number=identity.get("employee_number") or None,
                    phone=identity.get("phone") or None,
                    position=identity.get("position") or None,
                    role=User.Role.CLIENT,
                    approval_status=User.ApprovalStatus.APPROVED,
                    is_active=True,
                )
                user.set_unusable_password()
                user.save()
        except IntegrityError:
            user = User.objects.filter(email__iexact=email).first()
            if user is None:
                return None
            self._update_existing_user(
                user,
                identity,
                ad_username,
                first_name,
                last_name,
            )

        return user if self.user_can_authenticate(user) else None

    @staticmethod
    def _update_existing_user(user, identity, ad_username, first_name, last_name):
        updated_fields = []

        for field_name, value in (
            ("first_name", first_name),
            ("last_name", last_name),
        ):
            if value and getattr(user, field_name) != value:
                setattr(user, field_name, value)
                updated_fields.append(field_name)

        for field_name, value in (
            ("id_personal", identity.get("id_personal")),
            ("employee_number", identity.get("employee_number")),
            ("phone", identity.get("phone")),
            ("position", identity.get("position")),
        ):
            if value is not None and value != "" and getattr(user, field_name) != value:
                setattr(user, field_name, value)
                updated_fields.append(field_name)

        if ad_username and user.username != ad_username:
            username_conflict = User.objects.filter(
                username__iexact=ad_username,
            ).exclude(pk=user.pk).exists()
            if not username_conflict:
                user.username = ad_username
                updated_fields.append("username")

        if updated_fields:
            user.save(update_fields=updated_fields + ["updated_at"])
