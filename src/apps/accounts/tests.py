from datetime import timedelta
import re

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .access import (
    can_manage_deliveries,
    can_manage_inventory,
    can_register_intervention,
)

from .models import User
from apps.tickets.models import Ticket


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
        self.assertNotIn(
            f'href="{reverse("inventory:my_asset_list")}',
            sidebar,
        )

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
