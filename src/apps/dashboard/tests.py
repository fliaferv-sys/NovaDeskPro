from datetime import time, timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import (
    TechnicianAvailabilityRequest,
    TechnicianWorkday,
    User,
    WorkShift,
)
from apps.deliveries.models import AssetCustodyMovement
from apps.inventory.models import Asset


class ExecutiveDashboardCustodyKpiTests(TestCase):
    def test_pending_signature_kpi_excludes_delivered_movements(self):
        user = User.objects.create_user(
            username="dashboard-custody-admin",
            email="dashboard-custody-admin@example.test",
            password="test-password-123",
            role=User.Role.ADMIN,
        )
        pending_asset = Asset.objects.create(
            internal_code="DASH-CUSTODY-PENDING",
            asset_type=Asset.AssetType.LAPTOP,
        )
        delivered_asset = Asset.objects.create(
            internal_code="DASH-CUSTODY-DELIVERED",
            asset_type=Asset.AssetType.DESKTOP,
        )
        second_pending_asset = Asset.objects.create(
            internal_code="DASH-CUSTODY-PENDING-002",
            asset_type=Asset.AssetType.MONITOR,
        )
        AssetCustodyMovement.objects.create(
            asset=pending_asset,
            status=AssetCustodyMovement.MovementStatus.PENDING_SIGNATURE,
            delivery_responsible=user,
            created_by=user,
        )
        AssetCustodyMovement.objects.create(
            asset=second_pending_asset,
            status=AssetCustodyMovement.MovementStatus.PENDING_SIGNATURE,
            delivery_responsible=user,
            created_by=user,
        )
        AssetCustodyMovement.objects.create(
            asset=delivered_asset,
            status=AssetCustodyMovement.MovementStatus.DELIVERED,
            delivery_responsible=user,
            created_by=user,
        )
        self.client.force_login(user)

        response = self.client.get(reverse("dashboard:executive_dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["pending_signature_movements"], 2)
        self.assertEqual(response.context["completed_movements"], 1)


class TechnicianControlTests(TestCase):
    def setUp(self):
        self.users = {}
        for role in User.Role.values:
            self.users[role] = User.objects.create_user(
                username=f"control-{role.lower()}",
                email=f"control-{role.lower()}@example.test",
                password="test-password",
                role=role,
            )
        shift = WorkShift.objects.create(
            name="Control de técnicos",
            start_time=time(8),
            end_time=time(16),
        )
        now = timezone.now()
        self.workday = TechnicianWorkday.objects.create(
            technician=self.users[User.Role.TECHNICIAN],
            date=timezone.localdate(),
            shift=shift,
            started_at=now,
            scheduled_end_at=now + timedelta(hours=4),
        )
        self.availability_request = TechnicianAvailabilityRequest.objects.create(
            technician=self.users[User.Role.TECHNICIAN],
            workday=self.workday,
            request_type=TechnicianAvailabilityRequest.RequestType.UNAVAILABLE,
            reason="Gestión personal.",
        )

    def test_control_access_by_role(self):
        url = reverse("dashboard:technician_control")
        for role in (User.Role.ADMIN, User.Role.SUPERVISOR, User.Role.AUDITOR):
            with self.subTest(role=role):
                self.client.force_login(self.users[role])
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.context["pending_count"], 1)
                self.assertEqual(response.context["can_resolve"], role != User.Role.AUDITOR)
        for role in (User.Role.TECHNICIAN, User.Role.CLIENT):
            with self.subTest(role=role):
                self.client.force_login(self.users[role])
                self.assertEqual(self.client.get(url).status_code, 403)

    def test_home_card_is_visible_only_to_admin_and_supervisor(self):
        url = reverse("dashboard:technician_control")
        for role in (User.Role.ADMIN, User.Role.SUPERVISOR):
            with self.subTest(role=role):
                self.client.force_login(self.users[role])
                response = self.client.get(reverse("home"))
                self.assertContains(response, url)
                self.assertContains(response, "Control de técnicos")
        self.client.force_login(self.users[User.Role.AUDITOR])
        self.assertNotContains(self.client.get(reverse("home")), url)

    def test_admin_can_approve_and_supervisor_can_reject(self):
        resolve_url = reverse(
            "dashboard:resolve_technician_request",
            args=[self.availability_request.pk],
        )
        self.client.force_login(self.users[User.Role.ADMIN])
        response = self.client.post(resolve_url, {"decision": "approve"})
        self.assertRedirects(response, reverse("dashboard:technician_control"))
        self.availability_request.refresh_from_db()
        self.assertEqual(
            self.availability_request.status,
            TechnicianAvailabilityRequest.Status.APPROVED,
        )

        second_request = TechnicianAvailabilityRequest.objects.create(
            technician=self.users[User.Role.TECHNICIAN],
            workday=self.workday,
            request_type=TechnicianAvailabilityRequest.RequestType.EARLY_WORKDAY_END,
            reason="Otra solicitud.",
        )
        self.client.force_login(self.users[User.Role.SUPERVISOR])
        response = self.client.post(
            reverse(
                "dashboard:resolve_technician_request",
                args=[second_request.pk],
            ),
            {"decision": "reject"},
        )
        self.assertEqual(response.status_code, 302)
        second_request.refresh_from_db()
        self.assertEqual(
            second_request.status,
            TechnicianAvailabilityRequest.Status.REJECTED,
        )

    def test_technician_and_client_cannot_resolve_requests(self):
        url = reverse(
            "dashboard:resolve_technician_request",
            args=[self.availability_request.pk],
        )
        for role in (User.Role.TECHNICIAN, User.Role.CLIENT, User.Role.AUDITOR):
            with self.subTest(role=role):
                self.client.force_login(self.users[role])
                self.assertEqual(
                    self.client.post(url, {"decision": "approve"}).status_code,
                    403,
                )
