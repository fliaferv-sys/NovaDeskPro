from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import User
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
