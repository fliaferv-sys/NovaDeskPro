from contextlib import contextmanager
from datetime import timedelta
import re
from unittest.mock import patch

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts import backends
from .access import (
    can_manage_deliveries,
    can_manage_inventory,
    can_register_intervention,
)

from .models import (
    TechnicianAvailabilityRequest,
    TechnicianWorkday,
    User,
    WorkShift,
)
from .services import (
    create_technician_availability_request,
    finish_technician_workday,
    resolve_technician_availability_request,
)
from apps.tickets.models import Ticket
from apps.notifications.models import Notification


# Template-rendering tests do not require a collectstatic manifest.
TEST_STORAGES = {
    **settings.STORAGES,
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
    },
}


class ActiveDirectoryBackendTests(TestCase):
    def setUp(self):
        self.backend = backends.ActiveDirectoryBackend()

    def ad_profile(self, **overrides):
        profile = {
            "name": "Julia Valenzuela Samudio",
            "first_name": "Julia",
            "last_name": "Valenzuela Samudio",
            "email": "juvalenzuela@example.test",
            "username": "juvalenzuela",
            "is_active": True,
        }
        profile.update(overrides)
        return profile

    def institutional_identity(self, profile, **overrides):
        identity = {
            "source": "ACTIVE_DIRECTORY",
            "id_personal": None,
            "employee_number": "",
            "name": profile["name"],
            "first_name": profile["first_name"],
            "last_name": profile["last_name"],
            "email": profile["email"],
            "phone": "",
            "position": "",
            "employment_type": "",
            "status": "Activo" if profile["is_active"] else "Inactivo",
            "username": profile["username"],
            "is_active": profile["is_active"],
            "organizational_unit": None,
            "organizational_path": [],
        }
        identity.update(overrides)
        return identity

    @contextmanager
    def mock_ad_dependencies(
        self,
        *,
        credentials_valid=True,
        profiles=None,
        identity=None,
    ):
        with (
            patch.object(
                backends,
                "authenticate_windows_credentials",
                return_value=credentials_valid,
                create=True,
            ) as authenticate_windows,
            patch.object(
                backends,
                "search_ad_users",
                return_value=profiles if profiles is not None else [],
                create=True,
            ) as search_ad,
            patch.object(
                backends,
                "resolve_institutional_identity",
                return_value=identity,
                create=True,
            ) as resolve_identity,
        ):
            yield authenticate_windows, search_ad, resolve_identity

    def test_invalid_ad_credentials_do_not_create_local_user(self):
        with (
            self.mock_ad_dependencies(credentials_valid=False) as dependencies,
            patch.object(
                backends,
                "authenticate_ad_credentials",
                create=True,
            ) as legacy_authenticate,
        ):
            authenticate_windows, search_ad, resolve_identity = dependencies
            user = self.backend.authenticate(
                request=None,
                username="juvalenzuela",
                password="institutional-secret",
            )

        self.assertIsNone(user)
        self.assertEqual(User.objects.count(), 0)
        authenticate_windows.assert_called_once_with(
            "juvalenzuela",
            "institutional-secret",
        )
        legacy_authenticate.assert_not_called()
        search_ad.assert_not_called()
        resolve_identity.assert_not_called()

    def test_valid_ad_user_is_created_as_approved_client(self):
        profile = self.ad_profile()
        identity = self.institutional_identity(profile)
        with self.mock_ad_dependencies(
            profiles=[profile],
            identity=identity,
        ):
            user = self.backend.authenticate(
                request=None,
                username="juvalenzuela",
                password="institutional-secret",
            )

        self.assertIsInstance(user, User)
        self.assertEqual(user.email, "juvalenzuela@example.test")
        self.assertEqual(user.username, "juvalenzuela")
        self.assertEqual(user.first_name, "Julia")
        self.assertEqual(user.last_name, "Valenzuela Samudio")
        self.assertEqual(user.role, User.Role.CLIENT)
        self.assertEqual(user.approval_status, User.ApprovalStatus.APPROVED)
        self.assertTrue(user.is_active)
        self.assertFalse(user.has_usable_password())
        self.assertEqual(User.objects.count(), 1)

    def test_rrhh_identity_keeps_ad_username_and_applies_hr_fields(self):
        profile = self.ad_profile(
            name="Marciano Colman Zaracho",
            first_name="Marciano",
            last_name="Colman Zaracho",
            email="mcolman@example.test",
            username="mcolman",
        )
        identity = self.institutional_identity(
            profile,
            source="RRHH",
            id_personal=616,
            employee_number="1123",
            name="MARCIANO ISRAEL COLMAN ZARACHO",
            first_name="",
            last_name="",
            phone="0962000000",
            position="Asistente",
            employment_type="Contratado",
            username="",
        )
        with self.mock_ad_dependencies(
            profiles=[profile],
            identity=identity,
        ):
            user = self.backend.authenticate(
                request=None,
                username="MCOLMAN",
                password="institutional-secret",
            )

        self.assertIsInstance(user, User)
        self.assertEqual(user.username, "mcolman")
        self.assertEqual(user.id_personal, 616)
        self.assertEqual(user.employee_number, "1123")
        self.assertEqual(user.phone, "0962000000")
        self.assertEqual(user.position, "Asistente")
        self.assertEqual(user.role, User.Role.CLIENT)
        self.assertFalse(user.has_usable_password())

    def test_existing_technician_is_returned_without_role_downgrade(self):
        technician = User.objects.create_user(
            username="tecnico",
            email="tecnico@example.test",
            password="local-password",
            role=User.Role.TECHNICIAN,
            approval_status=User.ApprovalStatus.APPROVED,
        )
        profile = self.ad_profile(
            name="Técnico Existente",
            first_name="Técnico",
            last_name="Existente",
            email="tecnico@example.test",
            username="tecnico",
        )
        identity = self.institutional_identity(profile)

        with self.mock_ad_dependencies(
            profiles=[profile],
            identity=identity,
        ):
            authenticated = self.backend.authenticate(
                request=None,
                username="tecnico",
                password="institutional-secret",
            )

        technician.refresh_from_db()
        self.assertEqual(authenticated.pk, technician.pk)
        self.assertEqual(User.objects.count(), 1)
        self.assertEqual(technician.role, User.Role.TECHNICIAN)
        self.assertEqual(
            technician.approval_status,
            User.ApprovalStatus.APPROVED,
        )

    def test_suspended_local_user_is_not_reactivated(self):
        suspended = User.objects.create_user(
            username="suspended-user",
            email="suspended@example.test",
            password="local-password",
            approval_status=User.ApprovalStatus.SUSPENDED,
        )
        profile = self.ad_profile(
            name="Suspended User",
            first_name="Suspended",
            last_name="User",
            email="suspended@example.test",
            username="suspended-user",
        )
        identity = self.institutional_identity(profile)

        with self.mock_ad_dependencies(
            profiles=[profile],
            identity=identity,
        ):
            result = self.backend.authenticate(
                request=None,
                username="suspended-user",
                password="institutional-secret",
            )

        suspended.refresh_from_db()
        self.assertIsNone(result)
        self.assertEqual(
            suspended.approval_status,
            User.ApprovalStatus.SUSPENDED,
        )

    def test_inactive_institutional_identity_does_not_create_user(self):
        profile = self.ad_profile()
        identity = self.institutional_identity(profile, is_active=False)

        with self.mock_ad_dependencies(
            profiles=[profile],
            identity=identity,
        ):
            result = self.backend.authenticate(
                request=None,
                username="juvalenzuela",
                password="institutional-secret",
            )

        self.assertIsNone(result)
        self.assertEqual(User.objects.count(), 0)

    def test_empty_identifier_or_password_is_rejected_before_ad(self):
        cases = (
            ("", "institutional-secret"),
            ("   ", "institutional-secret"),
            ("juvalenzuela", ""),
        )
        with self.mock_ad_dependencies() as dependencies:
            authenticate_windows, search_ad, resolve_identity = dependencies
            for username, password in cases:
                with self.subTest(username=username, password_empty=not password):
                    result = self.backend.authenticate(
                        request=None,
                        username=username,
                        password=password,
                    )
                    self.assertIsNone(result)

        authenticate_windows.assert_not_called()
        search_ad.assert_not_called()
        resolve_identity.assert_not_called()
        self.assertEqual(User.objects.count(), 0)

    def test_valid_credentials_without_ad_profile_do_not_create_user(self):
        with self.mock_ad_dependencies(profiles=[]):
            result = self.backend.authenticate(
                request=None,
                username="unknown-user",
                password="institutional-secret",
            )

        self.assertIsNone(result)
        self.assertEqual(User.objects.count(), 0)

    def test_email_login_authenticates_and_finds_user_case_insensitively(self):
        profile = self.ad_profile(
            email="juvalenzuela@example.test",
            username="juvalenzuela",
        )
        identity = self.institutional_identity(profile)

        with self.mock_ad_dependencies(
            profiles=[profile],
            identity=identity,
        ):
            user = self.backend.authenticate(
                request=None,
                username="  JUVALENZUELA@EXAMPLE.TEST  ",
                password="institutional-secret",
            )

        self.assertIsInstance(user, User)
        self.assertEqual(user.email, "juvalenzuela@example.test")
        self.assertEqual(User.objects.count(), 1)

    def test_username_match_is_case_insensitive_but_not_partial(self):
        exact_profile = self.ad_profile(
            email="colman@example.test",
            username="MColman",
        )
        exact_identity = self.institutional_identity(exact_profile)
        with self.mock_ad_dependencies(
            profiles=[exact_profile],
            identity=exact_identity,
        ):
            matched = self.backend.authenticate(
                request=None,
                username="mcolman",
                password="institutional-secret",
            )

        self.assertIsInstance(matched, User)
        self.assertEqual(matched.username.casefold(), "mcolman")

        partial_profile = self.ad_profile(
            email="different@example.test",
            username="prefix-mcolman",
        )
        with self.mock_ad_dependencies(
            profiles=[partial_profile],
            identity=self.institutional_identity(partial_profile),
        ):
            unmatched = self.backend.authenticate(
                request=None,
                username="mcolman",
                password="institutional-secret",
            )

        self.assertIsNone(unmatched)
        self.assertEqual(User.objects.count(), 1)


class TechnicianAvailabilityRequestServiceTests(TestCase):
    def setUp(self):
        self.technician = User.objects.create_user(
            username="availability-technician",
            email="availability-technician@example.test",
            password="test-password",
            role=User.Role.TECHNICIAN,
            availability_status=User.AvailabilityStatus.AVAILABLE,
        )
        self.admin = User.objects.create_user(
            username="availability-admin",
            email="availability-admin@example.test",
            password="test-password",
            role=User.Role.ADMIN,
        )
        self.supervisor = User.objects.create_user(
            username="availability-supervisor",
            email="availability-supervisor@example.test",
            password="test-password",
            role=User.Role.SUPERVISOR,
        )
        self.client_user = User.objects.create_user(
            username="availability-client",
            email="availability-client@example.test",
            password="test-password",
            role=User.Role.CLIENT,
        )
        self.shift = WorkShift.objects.create(
            name="Turno de prueba",
            start_time="08:00",
            end_time="16:00",
        )
        now = timezone.now()
        self.workday = TechnicianWorkday.objects.create(
            technician=self.technician,
            date=timezone.localdate(),
            shift=self.shift,
            started_at=now,
            scheduled_end_at=now + timedelta(hours=4),
        )

    def create_request(self, request_type):
        return create_technician_availability_request(
            self.technician,
            request_type,
            "Motivo operativo justificado.",
        )

    def test_request_requires_reason_active_workday_and_is_unique(self):
        with self.assertRaises(ValidationError):
            create_technician_availability_request(
                self.technician,
                TechnicianAvailabilityRequest.RequestType.UNAVAILABLE,
                "",
            )
        self.create_request(TechnicianAvailabilityRequest.RequestType.UNAVAILABLE)
        with self.assertRaises(ValidationError):
            self.create_request(TechnicianAvailabilityRequest.RequestType.UNAVAILABLE)
        self.workday.status = TechnicianWorkday.Status.FINISHED
        self.workday.ended_at = timezone.now()
        self.workday.save(update_fields=["status", "ended_at"])
        with self.assertRaises(ValidationError):
            self.create_request(
                TechnicianAvailabilityRequest.RequestType.EARLY_WORKDAY_END
            )

    def test_creation_notifications_are_idempotent_and_recipient_specific(self):
        availability_request = self.create_request(
            TechnicianAvailabilityRequest.RequestType.EARLY_WORKDAY_END
        )
        notifications = Notification.objects.filter(
            object_type="TechnicianAvailabilityRequest",
            object_id=str(availability_request.pk),
        )
        self.assertEqual(notifications.count(), 2)
        self.assertSetEqual(
            set(notifications.values_list("recipient_id", flat=True)),
            {self.admin.pk, self.supervisor.pk},
        )
        self.assertFalse(notifications.filter(is_read=True).exists())
        self.assertFalse(notifications.filter(recipient=self.client_user).exists())
        for notification in notifications:
            self.assertEqual(
                notification.link,
                reverse("dashboard:technician_control"),
            )
            self.assertIn(str(notification.recipient_id), notification.unique_key)

        with self.assertRaises(ValidationError):
            self.create_request(
                TechnicianAvailabilityRequest.RequestType.EARLY_WORKDAY_END
            )
        self.assertEqual(notifications.count(), 2)

    def test_direct_early_finish_is_rejected(self):
        with self.assertRaises(ValidationError):
            finish_technician_workday(self.technician)
        self.workday.refresh_from_db()
        self.assertTrue(self.workday.is_active_workday)

    def test_admin_approval_sets_unavailable_without_finishing_workday(self):
        availability_request = self.create_request(
            TechnicianAvailabilityRequest.RequestType.UNAVAILABLE
        )
        resolve_technician_availability_request(
            availability_request, self.admin, approve=True
        )
        availability_request.refresh_from_db()
        self.technician.refresh_from_db()
        self.workday.refresh_from_db()
        self.assertEqual(
            availability_request.status,
            TechnicianAvailabilityRequest.Status.APPROVED,
        )
        self.assertEqual(availability_request.resolved_by, self.admin)
        self.assertEqual(
            self.technician.availability_status,
            User.AvailabilityStatus.UNAVAILABLE,
        )
        self.assertTrue(self.workday.is_active_workday)
        notification = Notification.objects.get(
            recipient=self.technician,
            object_type="TechnicianAvailabilityRequest",
            object_id=str(availability_request.pk),
        )
        self.assertIn("aprobada", notification.message)
        self.assertFalse(notification.is_read)
        self.assertEqual(notification.link, reverse("tickets:dashboard"))
        with self.assertRaises(ValidationError):
            resolve_technician_availability_request(
                availability_request, self.admin, approve=True
            )
        self.assertEqual(
            Notification.objects.filter(
                recipient=self.technician,
                object_id=str(availability_request.pk),
            ).count(),
            1,
        )

    def test_supervisor_approval_finishes_workday_without_releasing_ticket(self):
        ticket = Ticket.objects.create(
            title="Ticket asignado",
            description="Debe conservar responsable.",
            requester=self.admin,
            assigned_to=self.technician,
            status=Ticket.Status.IN_PROGRESS,
        )
        availability_request = self.create_request(
            TechnicianAvailabilityRequest.RequestType.EARLY_WORKDAY_END
        )
        resolve_technician_availability_request(
            availability_request,
            self.supervisor,
            approve=True,
            resolution_note="Salida autorizada.",
        )
        ticket.refresh_from_db()
        self.workday.refresh_from_db()
        self.assertEqual(ticket.assigned_to, self.technician)
        self.assertEqual(self.workday.status, TechnicianWorkday.Status.FINISHED)
        self.assertFalse(self.workday.ended_automatically)

    def test_rejection_preserves_workday_and_availability(self):
        availability_request = self.create_request(
            TechnicianAvailabilityRequest.RequestType.EARLY_WORKDAY_END
        )
        resolve_technician_availability_request(
            availability_request, self.admin, approve=False
        )
        availability_request.refresh_from_db()
        self.technician.refresh_from_db()
        self.workday.refresh_from_db()
        self.assertEqual(
            availability_request.status,
            TechnicianAvailabilityRequest.Status.REJECTED,
        )
        self.assertEqual(
            self.technician.availability_status,
            User.AvailabilityStatus.AVAILABLE,
        )
        self.assertTrue(self.workday.is_active_workday)
        notification = Notification.objects.get(
            recipient=self.technician,
            object_type="TechnicianAvailabilityRequest",
            object_id=str(availability_request.pk),
        )
        self.assertIn("rechazada", notification.message)


class UserDirectoryIdPersonalTests(TestCase):
    def test_user_can_be_created_without_id_personal(self):
        user = User.objects.create_user(
            username="directory-link-optional",
            email="directory-link-optional@example.test",
            password="test-password",
        )

        self.assertIsNone(user.id_personal)

    def test_user_can_be_created_with_id_personal(self):
        user = User.objects.create_user(
            username="directory-link-present",
            email="directory-link-present@example.test",
            password="test-password",
            id_personal=1234,
        )

        self.assertEqual(user.id_personal, 1234)

    def test_id_personal_must_be_unique(self):
        User.objects.create_user(
            username="directory-link-unique-first",
            email="directory-link-unique-first@example.test",
            password="test-password",
            id_personal=1234,
        )

        with self.assertRaises(IntegrityError), transaction.atomic():
            User.objects.create_user(
                username="directory-link-unique-second",
                email="directory-link-unique-second@example.test",
                password="test-password",
                id_personal=1234,
            )


@override_settings(STORAGES=TEST_STORAGES)
class AccountAccessTests(TestCase):
    password = "A-secure-test-password-9482"

    def create_user(self, email, **extra):
        return User.objects.create_user(
            username=email, email=email, password=self.password, **extra
        )

    def mobile_navigation(self, response):
        match = re.search(
            rb'<nav class="mobile-bottom-nav".*?</nav>',
            response.content,
            re.DOTALL,
        )
        self.assertIsNotNone(match)
        return match.group(0).decode()

    def test_suspended_user_cannot_log_in(self):
        user = self.create_user(
            "suspended@example.test",
            approval_status=User.ApprovalStatus.SUSPENDED,
        )
        self.assertFalse(self.client.login(email=user.email, password=self.password))

    def test_expired_user_cannot_log_in(self):
        user = self.create_user(
            "expired@example.test",
            employment_end_date=timezone.localdate() - timedelta(days=1),
        )
        self.assertFalse(self.client.login(email=user.email, password=self.password))

    def test_valid_approved_user_can_log_in(self):
        user = self.create_user("approved@example.test")
        self.assertTrue(self.client.login(email=user.email, password=self.password))

    def test_profile_requires_authentication(self):
        response = self.client.get(reverse("profile"))
        self.assertRedirects(
            response,
            f'{reverse("login")}?next={reverse("profile")}',
            fetch_redirect_response=False,
        )

    def test_profile_only_shows_authenticated_user(self):
        current_user = self.create_user(
            "current@example.test", first_name="Usuario", last_name="Actual"
        )
        other_user = self.create_user(
            "other@example.test", first_name="Usuario", last_name="Ajeno"
        )
        self.client.force_login(current_user)

        response = self.client.get(reverse("profile"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["profile_user"], current_user)
        self.assertContains(response, current_user.email)
        self.assertNotContains(response, other_user.email)

    def test_profile_marks_mobile_navigation_as_active(self):
        user = self.create_user("profile-navigation@example.test")
        self.client.force_login(user)

        response = self.client.get(reverse("profile"))

        self.assertContains(response, 'href="/accounts/profile/"')
        self.assertContains(response, 'class="mobile-bottom-nav-item is-active"')
        self.assertContains(response, 'aria-current="page"')

    def test_client_mobile_navigation_links_to_my_assets(self):
        user = self.create_user(
            "client-mobile-assets@example.test", role=User.Role.CLIENT
        )
        self.client.force_login(user)

        response = self.client.get(reverse("inventory:my_asset_list"))
        mobile_navigation = self.mobile_navigation(response)

        self.assertIn(reverse("inventory:my_asset_list"), mobile_navigation)
        self.assertIn("Mis equipos", mobile_navigation)
        self.assertIn("mobile-bottom-nav-item is-active", mobile_navigation)
        self.assertNotIn("Notificaciones", mobile_navigation)

    def test_non_client_mobile_navigation_keeps_notifications(self):
        for role in (
            User.Role.TECHNICIAN,
            User.Role.ADMIN,
            User.Role.SUPERVISOR,
        ):
            with self.subTest(role=role):
                user = self.create_user(
                    f"mobile-{role.lower()}@example.test", role=role
                )
                self.client.force_login(user)

                response = self.client.get(reverse("profile"))
                mobile_navigation = self.mobile_navigation(response)

                self.assertIn(
                    reverse("notifications:notification_list"),
                    mobile_navigation,
                )
                self.assertIn("Notificaciones", mobile_navigation)
                self.assertNotIn("Mis equipos", mobile_navigation)

    def test_admin_home_keeps_global_ticket_metrics(self):
        admin = self.create_user("global-admin@example.test", role=User.Role.ADMIN)
        requester = self.create_user("global-requester@example.test")
        Ticket.objects.create(
            title="Ticket global",
            description="Visible en el dashboard ejecutivo",
            requester=requester,
        )
        self.client.force_login(admin)

        response = self.client.get(reverse("home"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["total_tickets"], 1)

    def test_user_list_photo_priority_and_shared_preview(self):
        admin = self.create_user("photo-admin@example.test", role=User.Role.ADMIN)
        uploaded = self.create_user("uploaded@example.test", profile_image="profiles/test.jpg")
        institutional = self.create_user("institutional@example.test")
        initials = self.create_user("initials@example.test")
        self.client.force_login(admin)

        def photo_for(user):
            return "/media/funcionarios/testF.jpg" if user.pk == institutional.pk else ""

        with patch("apps.accounts.views.get_user_photo_url", side_effect=photo_for) as lookup:
            response = self.client.get(reverse("user_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, uploaded.profile_image.url)
        self.assertContains(response, "/media/funcionarios/testF.jpg")
        self.assertContains(response, 'data-photo-preview', count=3)
        self.assertContains(response, 'id="photoPreviewModal"', count=1)
        self.assertContains(response, "shared/js/photo_preview.js", count=1)
        self.assertNotIn(uploaded.pk, [call.args[0].pk for call in lookup.call_args_list])
        institutional.refresh_from_db()
        initials.refresh_from_db()
        self.assertFalse(institutional.profile_image)
        self.assertFalse(initials.profile_image)

    def test_client_cannot_open_global_user_list(self):
        user = self.create_user("client@example.test", role=User.Role.CLIENT)
        self.client.force_login(user)
        self.assertEqual(self.client.get(reverse("user_list")).status_code, 403)

    def test_client_cannot_open_executive_dashboard(self):
        user = self.create_user("dashboard@example.test", role=User.Role.CLIENT)
        self.client.force_login(user)
        response = self.client.get(reverse("dashboard:executive_dashboard"))
        self.assertEqual(response.status_code, 403)

    def test_client_home_opens_ticket_creation(self):
        user = self.create_user("client-home@example.test", role=User.Role.CLIENT)
        self.client.force_login(user)

        response = self.client.get(reverse("home"))

        self.assertRedirects(
            response,
            reverse("tickets:ticket_create"),
            fetch_redirect_response=False,
        )

    def test_suspended_existing_session_is_ended(self):
        user = self.create_user("session@example.test")
        self.client.force_login(user)
        user.approval_status = User.ApprovalStatus.SUSPENDED
        user.save(update_fields=["approval_status"])
        response = self.client.get(reverse("home"))
        self.assertRedirects(response, reverse("login"), fetch_redirect_response=False)
        self.assertNotIn("_auth_user_id", self.client.session)

        

class CentralizedPermissionTests(TestCase):
    def create_user(self, email, role, is_superuser=False):
        return User.objects.create_user(
            username=email,
            email=email,
            password="test-password-123",
            role=role,
            is_superuser=is_superuser,
        )

    def test_inventory_management_roles(self):
        admin = self.create_user("admin@example.test", User.Role.ADMIN)
        supervisor = self.create_user(
            "supervisor@example.test",
            User.Role.SUPERVISOR,
        )
        technician = self.create_user(
            "technician@example.test",
            User.Role.TECHNICIAN,
        )

        self.assertTrue(can_manage_inventory(admin))
        self.assertTrue(can_manage_inventory(supervisor))
        self.assertFalse(can_manage_inventory(technician))

    def test_delivery_management_roles(self):
        admin = self.create_user("delivery-admin@example.test", User.Role.ADMIN)
        supervisor = self.create_user(
            "delivery-supervisor@example.test",
            User.Role.SUPERVISOR,
        )
        technician = self.create_user(
            "delivery-technician@example.test",
            User.Role.TECHNICIAN,
        )

        self.assertTrue(can_manage_deliveries(admin))
        self.assertTrue(can_manage_deliveries(supervisor))
        self.assertFalse(can_manage_deliveries(technician))

    def test_intervention_registration_roles(self):
        supervisor = self.create_user(
            "intervention-supervisor@example.test",
            User.Role.SUPERVISOR,
        )
        technician = self.create_user(
            "intervention-technician@example.test",
            User.Role.TECHNICIAN,
        )
        client = self.create_user(
            "intervention-client@example.test",
            User.Role.CLIENT,
        )

        self.assertTrue(can_register_intervention(supervisor))
        self.assertTrue(can_register_intervention(technician))
        self.assertFalse(can_register_intervention(client))        


@override_settings(STORAGES=TEST_STORAGES)
class GlobalNavigationTests(TestCase):
    def create_user(self, name, role, **extra):
        return User.objects.create_user(
            username=name,
            email=f"{name}@example.test",
            password="test-password-123",
            role=role,
            **extra,
        )

    def sidebar_html(self, response):
        match = re.search(rb'<aside\s+class="sidebar".*?</aside>', response.content, re.DOTALL)
        self.assertIsNotNone(match)
        return match.group(0).decode()

    def test_global_home_shows_quick_access_for_global_roles(self):
        destinations = (
            reverse("reports:index"),
            reverse("notifications:notification_list"),
            reverse("monitoring:dashboard"),
            reverse("inventory:my_asset_list"),
            reverse("inventory:asset_qr_center"),
        )
        for role in (User.Role.ADMIN, User.Role.SUPERVISOR, User.Role.AUDITOR):
            with self.subTest(role=role):
                user = self.create_user(f"quick-{role.lower()}", role)
                self.client.force_login(user)
                response = self.client.get(reverse("home"))
                self.assertEqual(response.status_code, 200)
                for destination in destinations:
                    self.assertContains(response, f'href="{destination}"')

    def test_superuser_with_default_client_role_reaches_global_home(self):
        user = User.objects.create_superuser(
            username="navigation-root",
            email="navigation-root@example.test",
            password="test-password-123",
        )
        self.client.force_login(user)
        response = self.client.get(reverse("home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Accesos rápidos")
        self.assertContains(response, f'href="{reverse("reports:index")}"')
        self.assertContains(response, f'href="{reverse("inventory:asset_qr_center")}"')

    def test_sidebar_omits_secondary_navigation_for_global_user(self):
        admin = self.create_user("lean-sidebar-admin", User.Role.ADMIN)
        self.client.force_login(admin)
        sidebar = self.sidebar_html(self.client.get(reverse("home")))
        for destination in (
            reverse("reports:index"),
            reverse("monitoring:dashboard"),
            reverse("notifications:notification_list"),
            reverse("inventory:my_asset_list"),
            reverse("deliveries:custody_movement_list"),
        ):
            self.assertNotIn(f'href="{destination}"', sidebar)

        client = self.create_user("lean-sidebar-client", User.Role.CLIENT)
        self.client.force_login(client)
        sidebar = self.sidebar_html(self.client.get(reverse("inventory:my_asset_list")))
        self.assertIn(
            f'href="{reverse("inventory:my_asset_list")}',
            sidebar,
        )

    def test_my_assets_sidebar_link_is_client_only(self):
        destination = reverse("inventory:my_asset_list")

        for role in (
            User.Role.CLIENT,
            User.Role.TECHNICIAN,
            User.Role.ADMIN,
            User.Role.SUPERVISOR,
            User.Role.AUDITOR,
        ):
            with self.subTest(role=role):
                user = self.create_user(f"my-assets-sidebar-{role.lower()}", role)
                self.client.force_login(user)
                sidebar = self.sidebar_html(self.client.get(destination))

                if role == User.Role.CLIENT:
                    self.assertIn(f'href="{destination}"', sidebar)
                    self.assertIn("Mis equipos", sidebar)
                else:
                    self.assertNotIn(f'href="{destination}"', sidebar)
                    self.assertNotIn("Mis equipos", sidebar)

    def test_client_and_technician_home_flows_are_unchanged(self):
        client = self.create_user("navigation-client", User.Role.CLIENT)
        technician = self.create_user("navigation-tech", User.Role.TECHNICIAN)
        self.client.force_login(client)
        self.assertRedirects(
            self.client.get(reverse("home")),
            reverse("tickets:ticket_create"),
            fetch_redirect_response=False,
        )
        self.client.force_login(technician)
        self.assertRedirects(
            self.client.get(reverse("home")),
            reverse("tickets:dashboard"),
            fetch_redirect_response=False,
        )


@override_settings(STORAGES=TEST_STORAGES)
class ToolQuickAccessVisibilityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.users = {
            role: User.objects.create_user(
                username=f"quick-tools-{role.lower()}",
                email=f"quick-tools-{role.lower()}@example.test", role=role,
            ) for role in User.Role.values
        }

    def test_authorized_home_shows_single_card_with_named_destination(self):
        for role in (User.Role.ADMIN, User.Role.SUPERVISOR, User.Role.TECHNICIAN):
            with self.subTest(role=role):
                self.client.force_login(self.users[role])
                response = self.client.get(reverse("home"), follow=True)
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, '<h3>Herramientas DTI</h3>', count=1)
                self.assertContains(response, 'Préstamos, devoluciones y control de herramientas de trabajo.')
                self.assertContains(response, f'href="{reverse("inventory:tool_dashboard")}" class="staff-quick-access-link"')
                self.assertContains(response, 'Gestionar herramientas', count=1)
                self.assertContains(response, 'bi bi-tools')
                if role == User.Role.TECHNICIAN:
                    self.assertEqual(response.redirect_chain, [(reverse("tickets:dashboard"), 302)])
                else:
                    self.assertContains(response, '<h3>Control de técnicos</h3>')
                    self.assertContains(response, '<h3>QR de activos</h3>')

    def test_client_flow_and_other_roles_do_not_show_card(self):
        for role in User.Role.values:
            if role in (User.Role.ADMIN, User.Role.SUPERVISOR, User.Role.TECHNICIAN):
                continue
            with self.subTest(role=role):
                self.client.force_login(self.users[role])
                response = self.client.get(reverse("home"))
                if role == User.Role.CLIENT:
                    self.assertRedirects(response, reverse("tickets:ticket_create"), fetch_redirect_response=False)
                    response = self.client.get(reverse("tickets:dashboard"))
                self.assertNotContains(response, 'Gestionar herramientas')


@override_settings(STORAGES=TEST_STORAGES)
class AdminInstitutionalLookupTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            username="lookup-admin", email="lookup-admin@example.test", password="test-password"
        )
        self.url = reverse("admin:accounts_user_institutional_lookup")
        self.client.force_login(self.admin)

    def lookup(self, email="person@petropar.gov.py"):
        return self.client.get(self.url, {"email": email})

    @patch("apps.accounts.admin.find_institutional_identity_by_email")
    def test_found_payload_is_limited_and_maps_model_choices(self, lookup):
        lookup.return_value = {
            "first_name": "Nombre", "last_name": "Apellido", "employee_number": "1002",
            "document_number": "TEST-CI", "phone": "123", "position": "Analista",
            "employment_type": "Contratado", "photo_url": "/private.jpg", "source": "RRHH",
            "id_personal": 999, "password": "never-return", "username": "ad-name",
        }
        response = self.lookup(" Person@petropar.gov.py ")
        self.assertEqual(response.status_code, 200)
        fields = response.json()["fields"]
        self.assertEqual(fields["username"], "person")
        self.assertEqual(fields["employment_type"], User.EmploymentType.CONTRACTED)
        self.assertEqual(fields["position"], "Analista")
        self.assertEqual(set(fields), {"username", "first_name", "last_name", "employee_number", "document_number", "phone", "position", "employment_type"})
        lookup.assert_called_once_with("person@petropar.gov.py")

    @patch("apps.accounts.admin.find_institutional_identity_by_email", return_value=None)
    def test_missing_email_returns_nonblocking_status(self, lookup):
        self.assertEqual(self.lookup().json(), {"status": "not_found"})

    @patch("apps.accounts.admin.find_institutional_identity_by_email")
    def test_ambiguous_and_unavailable_return_no_personal_data(self, lookup):
        from apps.directory.identity_services import AmbiguousInstitutionalIdentity, InstitutionalIdentityError
        lookup.side_effect = AmbiguousInstitutionalIdentity("test")
        self.assertEqual(self.lookup().json(), {"status": "ambiguous"})
        lookup.side_effect = InstitutionalIdentityError("test")
        self.assertEqual(self.lookup().status_code, 503)
        self.assertEqual(self.lookup().json(), {"status": "unavailable"})

    @patch("apps.accounts.admin.find_institutional_identity_by_email")
    def test_invalid_external_email_and_post_do_not_query(self, lookup):
        self.assertEqual(self.lookup("invalid").status_code, 400)
        self.assertEqual(self.lookup("person@example.test").json(), {"status": "not_found"})
        self.assertEqual(self.client.post(self.url).status_code, 405)
        lookup.assert_not_called()

    @patch("apps.accounts.admin.find_institutional_identity_by_email")
    def test_authentication_staff_and_add_permission_are_required(self, lookup):
        from django.contrib.auth.models import Permission
        self.client.logout()
        self.assertEqual(self.lookup().status_code, 302)
        staff = User.objects.create_user(username="lookup-staff", email="lookup-staff@example.test", password="test", is_staff=True)
        self.client.force_login(staff)
        self.assertEqual(self.lookup().status_code, 403)
        lookup.assert_not_called()
        staff.user_permissions.add(Permission.objects.get(codename="add_user", content_type__app_label="accounts"))
        lookup.return_value = None
        self.assertEqual(self.lookup().status_code, 200)
        staff.is_staff = False
        staff.save(update_fields=["is_staff"])
        self.assertEqual(self.lookup().status_code, 302)

    @patch("apps.accounts.admin.find_institutional_identity_by_email")
    def test_department_requires_unique_active_exact_location(self, lookup):
        from apps.core.models import Department
        department = Department.objects.create(name="Sede", code="LOOKUP-1")
        lookup.return_value = {"location": " sede "}
        fields = self.lookup().json()["fields"]
        self.assertEqual(fields["department"]["value"], str(department.pk))
        Department.objects.create(name="SEDE", code="LOOKUP-2")
        self.assertNotIn("department", self.lookup().json()["fields"])

    def test_add_and_change_forms_include_shared_identity_component(self):
        add_response = self.client.get(reverse("admin:accounts_user_add"))
        self.assertEqual(add_response.status_code, 200)
        self.assertContains(add_response, "shared/js/institutional_identity.js")
        self.assertContains(add_response, reverse("directory:identity_search_api"))
        change_response = self.client.get(reverse("admin:accounts_user_change", args=[self.admin.pk]))
        self.assertContains(change_response, "shared/js/institutional_identity.js")
        self.assertContains(change_response, 'data-mode="change"')
