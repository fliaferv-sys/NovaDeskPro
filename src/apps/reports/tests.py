from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Branch, User
from apps.core.models import Department
from apps.inventory.models import (
    Asset, OrganizationalLocation, StockBalance, StockDelivery, StockDeliveryLine,
    StockMovement, StockProduct, StockCategory, TicketStockUsage, TicketStockUsageLine,
)
from apps.printing.models import Consumable, PrintingDevice, StockMovement as PrintingMovement
from apps.tickets.models import Ticket

from .selectors import get_inventory_report, get_printing_report, get_ticket_report


class ReportsFixtureMixin:
    @classmethod
    def setUpTestData(cls):
        cls.branch = Branch.objects.create(code="RPT-01", name="Sede Reportes")
        cls.other_branch = Branch.objects.create(code="RPT-02", name="Otra sede")
        cls.department = Department.objects.create(name="Soporte Reportes", code="RPT-SOP", sla_hours=24)
        cls.other_department = Department.objects.create(name="Otro Departamento", code="RPT-OTR")
        cls.admin = User.objects.create_user(username="rpt-admin", email="rpt-admin@example.test", password="pass", role=User.Role.ADMIN, branch=cls.branch)
        cls.supervisor = User.objects.create_user(username="rpt-super", email="rpt-super@example.test", password="pass", role=User.Role.SUPERVISOR)
        cls.auditor = User.objects.create_user(username="rpt-auditor", email="rpt-auditor@example.test", password="pass", role=User.Role.AUDITOR)
        cls.technician = User.objects.create_user(username="rpt-tech", email="rpt-tech@example.test", password="pass", role=User.Role.TECHNICIAN, department=cls.department)
        cls.client_user = User.objects.create_user(username="rpt-client", email="rpt-client@example.test", password="pass", role=User.Role.CLIENT, branch=cls.branch)
        cls.other_client = User.objects.create_user(username="rpt-other-client", email="rpt-other-client@example.test", password="pass", role=User.Role.CLIENT, branch=cls.other_branch)
        cls.superuser = User.objects.create_superuser(username="rpt-root", email="root@example.test", password="pass")


class ReportAccessTests(ReportsFixtureMixin, TestCase):
    urls = ("reports:index", "reports:tickets", "reports:inventory", "reports:printing")

    def test_global_roles_and_superuser_have_access(self):
        for user in (self.admin, self.supervisor, self.auditor, self.superuser):
            self.client.force_login(user)
            for name in self.urls:
                with self.subTest(role=user.role, url=name):
                    self.assertEqual(self.client.get(reverse(name)).status_code, 200)

    def test_client_and_technician_are_forbidden(self):
        for user in (self.client_user, self.technician):
            self.client.force_login(user)
            for name in self.urls:
                with self.subTest(role=user.role, url=name):
                    self.assertEqual(self.client.get(reverse(name)).status_code, 403)

    def test_anonymous_user_is_redirected_to_login(self):
        for name in self.urls:
            self.assertEqual(self.client.get(reverse(name)).status_code, 302)

    def test_reports_expose_get_only_pages(self):
        self.client.force_login(self.admin)
        for name in self.urls:
            self.assertEqual(self.client.post(reverse(name)).status_code, 405)

    def test_sidebar_does_not_include_reports_shortcut(self):
        for user in (self.admin, self.supervisor, self.auditor, self.superuser):
            self.client.force_login(user)
            self.assertNotContains(self.client.get(reverse("reports:index")), 'title="Reportes"')
        for user in (self.client_user, self.technician):
            self.client.force_login(user)
            response = self.client.get(
                reverse("home") if user.role == User.Role.CLIENT else reverse("tickets:dashboard"),
                follow=True,
            )
            self.assertNotContains(response, 'title="Reportes"')

    def test_invalid_filters_render_errors_instead_of_500(self):
        self.client.force_login(self.admin)
        for name in ("reports:tickets", "reports:inventory", "reports:printing"):
            response = self.client.get(reverse(name), {"date_from": "invalid", "branch": "invalid"})
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.context["form"].errors)


class TicketReportTests(ReportsFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        now = timezone.now()
        cls.met = Ticket.objects.create(title="Cumplido", description="x", requester=cls.client_user, assigned_to=cls.technician, department=cls.department, priority=Ticket.Priority.HIGH, status=Ticket.Status.RESOLVED)
        Ticket.objects.filter(pk=cls.met.pk).update(created_at=now - timedelta(days=2), due_date=now - timedelta(days=1), resolved_at=now - timedelta(days=1, hours=1))
        cls.met.refresh_from_db()
        cls.breached = Ticket.objects.create(title="Incumplido", description="x", requester=cls.client_user, department=cls.department, status=Ticket.Status.CLOSED)
        Ticket.objects.filter(pk=cls.breached.pk).update(created_at=now - timedelta(days=1), due_date=now - timedelta(hours=4), resolved_at=now)
        cls.breached.refresh_from_db()
        cls.active_overdue = Ticket.objects.create(title="Activo vencido", description="x", requester=cls.other_client, department=cls.other_department, status=Ticket.Status.OPEN)
        Ticket.objects.filter(pk=cls.active_overdue.pk).update(due_date=now - timedelta(minutes=1))
        cls.no_data = Ticket.objects.create(title="Sin SLA", description="x", requester=cls.client_user, status=Ticket.Status.RESOLVED)

    def test_totals_groups_and_sla(self):
        report = get_ticket_report({})
        self.assertEqual(report["total"], 4)
        self.assertIn({"priority": Ticket.Priority.HIGH, "total": 1}, report["by_priority"])
        self.assertIn({"status": Ticket.Status.RESOLVED, "total": 2}, report["by_status"])
        self.assertEqual(report["sla"]["met"], 1)
        self.assertEqual(report["sla"]["breached"], 1)
        self.assertEqual(report["sla"]["active_overdue"], 1)
        self.assertEqual(report["sla"]["no_data"], 1)
        self.assertEqual(report["sla"]["evaluable_resolved"], 2)

    def test_dimension_filters(self):
        self.assertEqual(get_ticket_report({"department": self.department})["total"], 2)
        self.assertEqual(get_ticket_report({"technician": self.technician})["total"], 1)
        self.assertEqual(get_ticket_report({"status": Ticket.Status.OPEN})["total"], 1)
        self.assertEqual(get_ticket_report({"branch": self.other_branch})["total"], 1)

    def test_date_to_includes_the_whole_day(self):
        target = timezone.localdate(self.breached.created_at)
        report = get_ticket_report({"date_from": target, "date_to": target})
        self.assertEqual(report["total"], 1)
        self.assertEqual(sum(row["total"] for row in report["created_by_day"]), 1)

    def test_resolved_series_uses_resolved_date(self):
        target = timezone.localdate()
        report = get_ticket_report({"date_from": target, "date_to": target})
        self.assertEqual(sum(row["total"] for row in report["resolved_by_day"]), 1)


class InventoryReportTests(ReportsFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.location = OrganizationalLocation.objects.create(branch=cls.branch, code="RPT-LOC", name="Depósito RPT", location_type=OrganizationalLocation.LocationType.WAREHOUSE)
        cls.category = StockCategory.objects.create(name="Reportes", code="reportes")
        cls.product = StockProduct.objects.create(name="Cable", reference_code="RPT-CABLE", category=cls.category, minimum_stock=10)
        cls.low_balance = StockBalance.objects.create(product=cls.product, branch=cls.branch, organizational_location=cls.location, quantity=2, minimum_stock=3)
        cls.zero_product = StockProduct.objects.create(name="Adaptador", reference_code="RPT-ADAPT", category=cls.category, minimum_stock=8)
        cls.zero_balance = StockBalance.objects.create(product=cls.zero_product, branch=cls.branch, organizational_location=cls.location, quantity=0)
        now = timezone.now()
        StockMovement.objects.create(product=cls.product, balance=cls.low_balance, quantity=5, direction=StockMovement.Direction.ENTRY, reason=StockMovement.Reason.PURCHASE, performed_by=cls.admin)
        StockMovement.objects.create(product=cls.product, balance=cls.low_balance, quantity=2, direction=StockMovement.Direction.EXIT, reason=StockMovement.Reason.CONSUMPTION, performed_by=cls.admin, department=cls.department)
        StockMovement.objects.create(product=cls.product, balance=cls.low_balance, quantity=1, direction=StockMovement.Direction.EXIT, reason=StockMovement.Reason.TRANSFER, performed_by=cls.admin)
        StockMovement.objects.create(product=cls.product, balance=cls.low_balance, quantity=1, direction=StockMovement.Direction.ENTRY, reason=StockMovement.Reason.TRANSFER, performed_by=cls.admin)
        ticket = Ticket.objects.create(title="Uso", description="x", requester=cls.client_user, department=cls.department)
        usage = TicketStockUsage.objects.create(ticket=ticket, registered_by=cls.admin)
        TicketStockUsageLine.objects.create(usage=usage, product=cls.product, source_branch=cls.branch, source_location=cls.location, quantity=2)
        TicketStockUsage.objects.filter(pk=usage.pk).update(status=TicketStockUsage.Status.CONFIRMED, confirmed_by=cls.admin, confirmed_at=now)
        delivery = StockDelivery.objects.create(recipient=cls.client_user, department=cls.department, branch=cls.branch, delivery_responsible=cls.admin, delivery_date=timezone.localdate(), created_by=cls.admin)
        StockDeliveryLine.objects.create(delivery=delivery, product=cls.product, quantity=3, source_branch=cls.branch, source_location=cls.location)
        StockDelivery.objects.filter(pk=delivery.pk).update(status=StockDelivery.Status.COMPLETED, completed_by=cls.admin, completed_at=now)

    def test_stock_minimum_movements_transfers_and_confirmed_activity(self):
        report = get_inventory_report({})
        self.assertEqual(report["stock_total"], 2)
        self.assertEqual(report["low_count"], 1)
        self.assertEqual(report["empty_count"], 1)
        self.assertEqual(report["low_balances"][0].effective_minimum, 3)
        self.assertEqual(report["movement_totals"]["transfer_entries"], 1)
        self.assertEqual(report["movement_totals"]["transfer_exits"], 1)
        self.assertEqual(report["delivery_quantity"], 3)
        self.assertEqual(report["usage_quantity"], 2)

    def test_inventory_filters(self):
        self.assertEqual(get_inventory_report({"branch": self.other_branch})["stock_total"], 0)
        self.assertEqual(get_inventory_report({"department": self.other_department})["delivery_count"], 0)


class PrintingReportTests(ReportsFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.asset = Asset.objects.create(internal_code="RPT-PRINT", asset_type=Asset.AssetType.PRINTER, brand="Test", model="P1", serial_number="RPT-SERIAL", branch=cls.branch)
        cls.device = PrintingDevice.objects.create(asset=cls.asset)
        cls.consumable = Consumable.objects.create(name="Tóner RPT", reference_code="TON-RPT", manufacturer="Test", initial_stock=5, minimum_stock=5)
        for movement_type, quantity in ((PrintingMovement.MovementType.ENTRY, 4), (PrintingMovement.MovementType.POSITIVE_ADJUSTMENT, 1), (PrintingMovement.MovementType.ISSUE, 2), (PrintingMovement.MovementType.NEGATIVE_ADJUSTMENT, 1), (PrintingMovement.MovementType.TRANSFER, 9)):
            PrintingMovement.objects.create(consumable=cls.consumable, movement_type=movement_type, quantity=quantity, performed_by=cls.admin)

    def test_stock_formula_minimum_and_transfer(self):
        report = get_printing_report({})
        row = report["consumables"][0]
        self.assertEqual(row.current_stock_value, 7)
        self.assertEqual(row.entries_total, 5)
        self.assertEqual(row.outputs_total, 3)
        self.assertEqual(report["low_count"], 0)

    def test_minimum_is_inclusive_and_branch_only_filters_devices(self):
        Consumable.objects.filter(pk=self.consumable.pk).update(initial_stock=3)
        report = get_printing_report({"branch": self.other_branch})
        self.assertEqual(report["device_total"], 0)
        self.assertEqual(report["consumable_count"], 1)
        self.assertEqual(report["low_count"], 1)
