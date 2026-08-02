from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import User


class AccountAccessTests(TestCase):
    password = "A-secure-test-password-9482"

    def create_user(self, email, **extra):
        return User.objects.create_user(
            username=email, email=email, password=self.password, **extra
        )

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

    def test_client_cannot_open_global_user_list(self):
        user = self.create_user("client@example.test", role=User.Role.CLIENT)
        self.client.force_login(user)
        self.assertEqual(self.client.get(reverse("user_list")).status_code, 403)

    def test_client_cannot_open_executive_dashboard(self):
        user = self.create_user("dashboard@example.test", role=User.Role.CLIENT)
        self.client.force_login(user)
        response = self.client.get(reverse("dashboard:executive_dashboard"))
        self.assertEqual(response.status_code, 403)

    def test_suspended_existing_session_is_ended(self):
        user = self.create_user("session@example.test")
        self.client.force_login(user)
        user.approval_status = User.ApprovalStatus.SUSPENDED
        user.save(update_fields=["approval_status"])
        response = self.client.get(reverse("home"))
        self.assertRedirects(response, reverse("login"), fetch_redirect_response=False)
        self.assertNotIn("_auth_user_id", self.client.session)
