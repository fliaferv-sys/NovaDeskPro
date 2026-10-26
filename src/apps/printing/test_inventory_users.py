from datetime import timedelta
from unittest.mock import patch

from django.db import IntegrityError, connection, transaction
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase, Client, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User, Branch
from apps.core.models import Department
from apps.inventory.models import Asset, OrganizationalLocation
from apps.institution.models import OrganizationalUnit
from .inventory_users import assign_user, end_assignment
from .models import PrintingDevice, PrintingDeviceNetworkDetection, PrintingDeviceUserAssignment


class PrintingInventoryUsersTests(TestCase):
    def setUp(self):
        self.sync = patch("apps.accounts.signals.try_sync_user_institutional_data")
        self.sync.start()
        self.addCleanup(self.sync.stop)
        self.admin = User.objects.create_user(username="operator", email="operator@example.test", role="ADMIN")
        self.department = Department.objects.create(name="Financiera", code="FIN")
        self.person = User.objects.create_user(username="griselda", email="griselda@example.test", first_name="Griselda", last_name="Gomez", department=self.department)
        self.other = User.objects.create_user(username="other", email="other@example.test", first_name="Pedro")
        self.device = PrintingDevice.objects.create(photocopier_id="11", serial_number="SERIE-11", model="MX622", brand="Lexmark", ip_address="10.1.1.11")
        self.detection = PrintingDeviceNetworkDetection.objects.create(printing_device=self.device, detected_mac="00:21:B7:1F:8F:43", detected_ip="10.1.1.12")
        self.client.force_login(self.admin)
        self.list_url = reverse("printing:devices_by_model")
        self.detail_url = reverse("printing:device_detail", args=[self.device.pk])
        self.manage_url = reverse("printing:manage_device_user", args=[self.device.pk])

    def search_ids(self, **params):
        response = self.client.get(self.list_url, params)
        self.assertEqual(response.status_code, 200)
        return [d.pk for d in response.context["devices"]]

    def test_search_technical_fields_and_mac_formats(self):
        for term in ["11", "SERIE-11", "Lexmark", "MX622", "10.1.1.11", "10.1.1.12", "00:21:B7:1F:8F:43", "0021b71f8f43", "00-21-b7-1f-8f-43"]:
            with self.subTest(term=term):
                self.assertEqual(self.search_ids(search=term), [self.device.pk])

    def test_search_person_full_name_and_department(self):
        assign_user(self.device.pk, self.person.pk, self.admin)
        for term in ["Griselda", "Gomez", "Griselda Gomez", "Financiera"]:
            self.assertEqual(self.search_ids(search=term), [self.device.pk])
        self.assertEqual(self.search_ids(search="Griselda", department=str(self.department.pk)), [self.device.pk])
        self.assertEqual(self.search_ids(search="no existe", department=str(self.department.pk)), [])

    def test_many_to_many_and_database_duplicate_constraint(self):
        second = PrintingDevice.objects.create(photocopier_id="12")
        assign_user(self.device.pk, self.person.pk, self.admin)
        assign_user(self.device.pk, self.other.pk, self.admin)
        assign_user(second.pk, self.person.pk, self.admin)
        self.assertEqual(len(self.search_ids(search="Griselda")), 2)
        with self.assertRaises(ValidationError):
            assign_user(self.device.pk, self.person.pk, self.admin)
        with self.assertRaises(IntegrityError), transaction.atomic():
            PrintingDeviceUserAssignment.objects.create(device=self.device, user=self.person, assigned_by=self.admin)

    def test_removal_keeps_history_and_reassignment_creates_new_period(self):
        assignment = assign_user(self.device.pk, self.person.pk, self.admin)
        end_assignment(self.device.pk, assignment.pk, self.admin)
        assignment.refresh_from_db()
        self.assertIsNotNone(assignment.ended_at)
        self.assertEqual(assignment.ended_by, self.admin)
        self.assertEqual(assignment.assigned_by, self.admin)
        self.assertEqual(self.search_ids(search="Griselda"), [])
        new = assign_user(self.device.pk, self.person.pk, self.admin)
        self.assertNotEqual(assignment.pk, new.pk)
        self.assertContains(self.client.get(self.detail_url), "Historial de asociaciones finalizadas")
        ended_at = assignment.ended_at
        end_assignment(self.device.pk, assignment.pk, self.admin)
        assignment.refresh_from_db()
        self.assertEqual(assignment.ended_at, ended_at)

    def test_archive_keeps_associations_but_rejects_new_ones(self):
        assignment = assign_user(self.device.pk, self.person.pk, self.admin)
        PrintingDevice.objects.filter(pk=self.device.pk).update(is_active=False)
        self.assertEqual(self.search_ids(search="Griselda"), [])
        self.assertEqual(self.search_ids(search="Griselda", lifecycle="archived"), [self.device.pk])
        self.assertEqual(self.search_ids(search="Griselda", lifecycle="all"), [self.device.pk])
        self.assertContains(self.client.get(self.detail_url), "Archivada")
        with self.assertRaises(ValidationError):
            assign_user(self.device.pk, self.other.pk, self.admin)
        self.assertTrue(PrintingDeviceUserAssignment.objects.filter(pk=assignment.pk).exists())
        end_assignment(self.device.pk, assignment.pk, self.admin)

    def test_technical_rows_unchanged_by_assignment_operations(self):
        before = list(PrintingDevice.objects.values())
        detections = list(PrintingDeviceNetworkDetection.objects.values())
        assignment = assign_user(self.device.pk, self.person.pk, self.admin)
        end_assignment(self.device.pk, assignment.pk, self.admin)
        self.assertEqual(list(PrintingDevice.objects.values()), before)
        self.assertEqual(list(PrintingDeviceNetworkDetection.objects.values()), detections)

    def test_read_only_roles_and_server_permissions(self):
        for role in ["AUDITOR", "TECHNICIAN"]:
            reader = User.objects.create_user(username=role, email=role+"@example.test", role=role)
            self.client.force_login(reader)
            self.assertEqual(self.client.get(self.detail_url).status_code, 200)
            self.assertEqual(self.client.post(self.manage_url, {"action": "add", "user_id": self.person.pk}).status_code, 403)
            with self.assertRaises(PermissionDenied):
                assign_user(self.device.pk, self.person.pk, reader)
        self.assertEqual(PrintingDeviceUserAssignment.objects.count(), 0)

    def test_remove_permissions_and_consultation_only_ui(self):
        assignment = assign_user(self.device.pk, self.person.pk, self.admin)
        reader = User.objects.create_user(username="reader", email="reader@example.test", role="AUDITOR")
        self.client.force_login(reader)
        self.assertNotContains(self.client.get(self.detail_url), "Quitar usuario")
        self.assertEqual(self.client.post(self.manage_url, {"action": "remove", "assignment_id": assignment.pk}).status_code, 403)
        with self.assertRaises(PermissionDenied):
            end_assignment(self.device.pk, assignment.pk, reader)
        assignment.refresh_from_db()
        self.assertIsNone(assignment.ended_at)

    def test_supervisor_management_and_denied_general_user(self):
        supervisor = User.objects.create_user(username="supervisor", email="supervisor@example.test", role="SUPERVISOR")
        self.client.force_login(supervisor)
        self.assertEqual(self.client.post(self.manage_url, {"action": "add", "user_id": self.person.pk}).status_code, 302)
        self.assertEqual(PrintingDeviceUserAssignment.objects.get().assigned_by, supervisor)
        self.client.force_login(self.person)
        self.assertEqual(self.client.get(self.list_url).status_code, 403)
        self.client.logout()
        self.assertEqual(self.client.get(self.list_url).status_code, 302)

    @override_settings(MIDDLEWARE=["django.contrib.sessions.middleware.SessionMiddleware", "django.contrib.auth.middleware.AuthenticationMiddleware", "django.contrib.messages.middleware.MessageMiddleware", "django.middleware.csrf.CsrfViewMiddleware"])
    def test_post_requires_csrf_token(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.admin)
        self.assertEqual(client.post(self.manage_url, {"action": "add", "user_id": self.person.pk}).status_code, 403)
        self.assertEqual(PrintingDeviceUserAssignment.objects.count(), 0)

    def test_post_add_remove_and_user_selection(self):
        response = self.client.get(self.detail_url, {"person_search": "Griselda"})
        self.assertContains(response, "Agregar usuario")
        self.assertEqual(self.client.post(self.manage_url, {"action": "add", "user_id": self.person.pk}).status_code, 302)
        assignment = PrintingDeviceUserAssignment.objects.get()
        self.assertContains(self.client.get(self.detail_url), "Quitar usuario")
        self.client.post(self.manage_url, {"action": "add", "user_id": self.person.pk})
        self.assertEqual(PrintingDeviceUserAssignment.objects.count(), 1)
        self.client.post(self.manage_url, {"action": "remove", "assignment_id": assignment.pk})
        assignment.refresh_from_db()
        self.assertIsNotNone(assignment.ended_at)
        self.assertEqual(self.client.get(self.manage_url).status_code, 405)

    def test_tampered_form_cannot_remove_other_printer_assignment(self):
        other_device = PrintingDevice.objects.create(photocopier_id="99")
        assignment = assign_user(other_device.pk, self.person.pk, self.admin)
        self.assertEqual(self.client.post(self.manage_url, {"action": "remove", "assignment_id": assignment.pk}).status_code, 404)
        assignment.refresh_from_db()
        self.assertIsNone(assignment.ended_at)

    def test_inactive_or_missing_person_is_not_created(self):
        User.objects.filter(pk=self.person.pk).update(is_active=False)
        count = User.objects.count()
        self.assertEqual(self.client.post(self.manage_url, {"action": "add", "user_id": self.person.pk}).status_code, 404)
        self.assertEqual(User.objects.count(), count)
        self.assertEqual(PrintingDeviceUserAssignment.objects.count(), 0)

    def test_location_and_installation_department_are_distinct_from_user_department(self):
        branch = Branch.objects.create(name="Central", code="C")
        location = OrganizationalLocation.objects.create(branch=branch, code="OF", name="Oficina")
        asset = Asset.objects.create(internal_code="ASSET", department="InformÃ¡tica", physical_location=location)
        PrintingDevice.objects.filter(pk=self.device.pk).update(asset=asset)
        assign_user(self.device.pk, self.person.pk, self.admin)
        self.assertEqual(self.search_ids(department=str(self.department.pk), installation="InformÃ¡tica", location=str(location.pk)), [self.device.pk])
        self.assertEqual(self.search_ids(installation="Financiera"), [])
        self.assertEqual(self.search_ids(search="Oficina"), [self.device.pk])
        self.assertEqual(self.search_ids(location="invalid"), [])

    def test_institutional_department_filter_and_person_selection(self):
        unit = OrganizationalUnit.objects.create(name="Gerencia Financiera", code="GF", unit_type="MANAGEMENT")
        User.objects.filter(pk=self.person.pk).update(organizational_unit=unit, department=None)
        assign_user(self.device.pk, self.person.pk, self.admin)
        self.assertEqual(self.search_ids(user_unit=str(unit.pk)), [self.device.pk])
        self.assertEqual(self.search_ids(search="Gerencia Financiera"), [self.device.pk])
        self.assertEqual(self.search_ids(user_unit="invalid"), [])
        self.assertEqual(self.search_ids(department="9"*200), [])

    def test_pagination_and_query_count_are_bounded(self):
        PrintingDevice.objects.bulk_create([PrintingDevice(photocopier_id=f"P{i}") for i in range(120)])
        with CaptureQueriesContext(connection) as captured:
            response = self.client.get(self.list_url, {"search": "P", "page": "2"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["devices"]), 50)
        self.assertEqual(response.context["total"], 120)
        self.assertLess(len(captured), 30)
        self.assertContains(response, "search=P&amp;page=3")

    def test_effective_status_filters_stale_and_duplicate_ips(self):
        PrintingDevice.objects.filter(pk=self.device.pk).update(connection_status="ONLINE", monitored_ip=self.device.ip_address,
            monitor_method="TCP", monitor_evidence={"network_port": 9100}, last_checked_at=timezone.now())
        self.assertEqual(self.search_ids(status="ONLINE"), [self.device.pk])
        PrintingDevice.objects.filter(pk=self.device.pk).update(last_checked_at=timezone.now()-timedelta(days=1))
        self.assertEqual(self.search_ids(status="ONLINE"), [])
        self.assertEqual(self.search_ids(status="UNKNOWN"), [self.device.pk])
        PrintingDevice.objects.filter(pk=self.device.pk).update(last_checked_at=timezone.now())
        PrintingDevice.objects.create(ip_address=self.device.ip_address)
        self.assertEqual(self.search_ids(status="ONLINE"), [])


class PrintingResponsibleSearchTests(TestCase):
    def setUp(self):
        sync = patch("apps.accounts.signals.try_sync_user_institutional_data")
        sync.start()
        self.addCleanup(sync.stop)
        # Search is local SQL; avoid unrelated external-directory enrichment.
        enrich = patch("apps.printing.inventory_users.enrich_person_records", side_effect=lambda records, *args: list(records))
        enrich.start()
        self.addCleanup(enrich.stop)
        self.admin = User.objects.create_user(username="search-operator", email="search-operator@example.test", role="ADMIN")
        self.department = Department.objects.create(name="Financiera", code="SEARCH-FIN")
        self.unit = OrganizationalUnit.objects.create(name="Gerencia Financiera", code="SEARCH-GF", unit_type="MANAGEMENT")
        self.ariel = User.objects.create_user(username="ariel-account", email="ariel@example.test", first_name="Ariel", last_name="Benitez", department=self.department, organizational_unit=self.unit)
        self.silvio = User.objects.create_user(username="silvio-account", email="silvio@example.test", first_name="Silvio", last_name="Duarte")
        self.client.force_login(self.admin)
        self.url = reverse("printing:devices_by_model")

    def search(self, text, **filters):
        response = self.client.get(self.url, {"search": text, **filters})
        self.assertEqual(response.status_code, 200)
        devices = list(response.context["devices"])
        self.assertEqual(len(devices), len({device.pk for device in devices}))
        self.assertEqual(response.context["total"], len(devices))
        return {device.photocopier_id for device in devices}

    def test_existing_responsible_account_name_surname_and_partial_case_insensitive(self):
        PrintingDevice.objects.create(photocopier_id="12", responsible_user=self.ariel)
        for term in ("Ariel", "ARIEL", "ari", "bEnI", "Benitez", "arIel BEN", "ariel-account"):
            with self.subTest(term=term):
                self.assertEqual(self.search(term), {"12"})
        self.assertEqual(PrintingDeviceUserAssignment.objects.count(), 0)

    def test_responsible_name_snapshot_without_account_link(self):
        PrintingDevice.objects.create(photocopier_id="13", responsible_identity={"name": "Ariel Benitez"})
        self.assertEqual(self.search("ARi BEN"), {"13"})
        self.assertEqual(self.search("Benitez"), {"13"})
        self.assertFalse(PrintingDevice.objects.exclude(responsible_user=None).exists())
        self.assertEqual(PrintingDeviceUserAssignment.objects.count(), 0)

    def test_responsible_and_assigned_union_matches_three_distinct_printers(self):
        PrintingDevice.objects.create(photocopier_id="12", responsible_user=self.ariel)
        assigned = PrintingDevice.objects.create(photocopier_id="27")
        both = PrintingDevice.objects.create(photocopier_id="45", responsible_user=self.ariel, responsible_identity={"name": "Ariel Benitez"})
        assign_user(assigned.pk, self.ariel.pk, self.admin)
        assign_user(both.pk, self.ariel.pk, self.admin)
        assign_user(both.pk, self.silvio.pk, self.admin)
        self.assertEqual(self.search("Ariel"), {"12", "27", "45"})
        self.assertEqual(self.search("Benitez"), {"12", "27", "45"})

    def test_person_related_to_five_printers(self):
        for number in range(1, 6):
            device = PrintingDevice.objects.create(photocopier_id=str(number), responsible_user=self.silvio if number < 3 else None,
                responsible_identity={"name": "Silvio Duarte"} if number == 3 else {})
            if number >= 4:
                assign_user(device.pk, self.silvio.pk, self.admin)
        self.assertEqual(self.search("silv"), {"1", "2", "3", "4", "5"})

    def test_ended_assignment_does_not_match_unless_still_responsible(self):
        ended_only = PrintingDevice.objects.create(photocopier_id="27")
        responsible = PrintingDevice.objects.create(photocopier_id="45", responsible_user=self.ariel)
        for device in (ended_only, responsible):
            assignment = assign_user(device.pk, self.ariel.pk, self.admin)
            end_assignment(device.pk, assignment.pk, self.admin)
        self.assertEqual(self.search("Ariel"), {"45"})
        self.assertEqual(PrintingDeviceUserAssignment.objects.filter(ended_at__isnull=False).count(), 2)

    def test_responsible_search_preserves_lifecycle_and_connectivity_filters(self):
        PrintingDevice.objects.create(photocopier_id="12", responsible_user=self.ariel,
            ip_address="10.1.2.12", monitored_ip="10.1.2.12", connection_status="ONLINE", monitor_method="TCP",
            monitor_evidence={"network_port": 9100}, last_checked_at=timezone.now())
        PrintingDevice.objects.create(photocopier_id="27", responsible_identity={"name": "Ariel Benitez"})
        PrintingDevice.objects.create(photocopier_id="45", responsible_user=self.ariel, is_active=False)
        self.assertEqual(self.search("Ariel"), {"12", "27"})
        self.assertEqual(self.search("Ariel", lifecycle="archived"), {"45"})
        self.assertEqual(self.search("Ariel", lifecycle="all"), {"12", "27", "45"})
        self.assertEqual(self.search("Ariel", status="ONLINE"), {"12"})
        self.assertEqual(self.search("Ariel", status="UNKNOWN"), {"27"})

    def test_responsible_search_combines_department_unit_location_brand_and_model(self):
        branch = Branch.objects.create(name="Search Central", code="SC")
        location = OrganizationalLocation.objects.create(branch=branch, code="SEARCH-OFFICE", name="Oficina")
        PrintingDevice.objects.create(photocopier_id="12", responsible_user=self.ariel, branch=branch,
            organizational_location=location, brand="Lexmark", model="MX622")
        PrintingDevice.objects.create(photocopier_id="27", responsible_user=self.ariel, model="Other")
        self.assertEqual(self.search("Ariel", department=str(self.department.pk), user_unit=str(self.unit.pk), location=str(location.pk), brand="Lexmark", model="MX622"), {"12"})
        self.assertEqual(self.search("Ariel", location=str(location.pk), model="Other"), set())
        self.assertEqual(self.search("Ariel", department="invalid"), set())

    def test_person_search_does_not_modify_printers_users_assignments_or_history(self):
        device = PrintingDevice.objects.create(photocopier_id="12", responsible_identity={"name": "Ariel Benitez"})
        assign_user(device.pk, self.ariel.pk, self.admin)
        models = (PrintingDevice, PrintingDeviceNetworkDetection, PrintingDeviceUserAssignment, User)
        before = [list(model.objects.order_by("pk").values()) for model in models]
        self.assertEqual(self.search("Ariel"), {"12"})
        self.assertEqual([list(model.objects.order_by("pk").values()) for model in models], before)
