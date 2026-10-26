[CmdletBinding()]
param()
if ($env:COMPUTERNAME -ine 'MESATI') { throw 'Consulta preparada exclusivamente para MESATI.' }
$Python = 'C:\NovaDeskPro\venv\Scripts\python.exe'
$Url = Read-Host 'URL completa del resultado al buscar Ariel'
$UrlSilvio = Read-Host 'URL completa del resultado al buscar Silvio'
$UrlDepartamento = Read-Host 'URL completa del resultado al filtrar por el departamento esperado'
$ServiceDirectory = ''
$ServicePython = ''
$ServiceModule = ''
$ServiceSettings = ''
try {
    $Nssm = Get-ItemProperty -LiteralPath 'HKLM:\SYSTEM\CurrentControlSet\Services\NovaDeskPro\Parameters' -ErrorAction Stop
    $ServiceDirectory = [string]$Nssm.AppDirectory
    $ServicePython = [string]$Nssm.Application
    if ([string]$Nssm.AppParameters -match '([A-Za-z_][A-Za-z0-9_.]*):(application|app)') { $ServiceModule = $Matches[1] }
    foreach ($Entry in @($Nssm.AppEnvironment) + @($Nssm.AppEnvironmentExtra)) {
        if ([string]$Entry -match '^DJANGO_SETTINGS_MODULE=([A-Za-z_][A-Za-z0-9_.]*)$') { $ServiceSettings = $Matches[1] }
    }
} catch { }
# Only reads selected NSSM paths. No environment values, credentials or arguments.
$Codigo = @'
import ast
import base64
import hashlib
import inspect
import json
import os
from pathlib import Path
import socket
import sqlite3
import sys
from types import SimpleNamespace
from urllib.parse import urlsplit
from unittest.mock import patch

EXPECTED_ROOT = Path(r"C:\NovaDeskPro\src\src")
EXPECTED_DB = EXPECTED_ROOT / "db.sqlite3"
TERM = "Ariel"
stage = "initialization"
report = {}

def read_input(argv):
    # Windows PowerShell may omit empty native arguments. One nonempty encoded
    # JSON argument preserves every optional field without positional shifts.
    if len(argv) != 2:
        raise RuntimeError("DIAGNOSTIC_INPUT_ARGUMENT_MISSING")
    data = json.loads(base64.b64decode(argv[1], validate=True).decode("utf-8"))
    if not isinstance(data, dict):
        raise RuntimeError("DIAGNOSTIC_INPUT_INVALID")
    for key in ("ariel_url", "silvio_url", "third_url"):
        if not isinstance(data.get(key), str) or not data[key].strip():
            raise RuntimeError("DIAGNOSTIC_REQUIRED_URL_MISSING")
    for key in ("service_directory", "service_python", "service_module", "service_settings"):
        if not isinstance(data.get(key, ""), str):
            raise RuntimeError("DIAGNOSTIC_OPTIONAL_INPUT_INVALID")
        data.setdefault(key, "")
    return data


def classify_query(query):
    fields = [key for key in ("department", "user_unit", "installation") if query.get(key, "").strip()]
    return dict(query_kind="department_filter" if fields else "text_search" if query.get("search", "").strip() else "no_department_or_text_search",
        active_department_fields=fields, has_text_search=bool(query.get("search", "").strip()))


def output():
    print(json.dumps(report, ensure_ascii=True, indent=2))

def guard(event, args):
    if event == "sqlite3.connect" and str(args[0]) != EXPECTED_DB.as_uri() + "?mode=ro":
        raise RuntimeError("DIAGNOSTIC_NON_READONLY_CONNECTION_FORBIDDEN")
    if event in {"socket.connect", "socket.connect_ex", "socket.getaddrinfo", "socket.sendto", "subprocess.Popen", "os.system"}:
        raise RuntimeError("DIAGNOSTIC_NETWORK_OR_PROCESS_FORBIDDEN")
    if event == "open" and isinstance(args[2], int) and args[2] & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
        raise RuntimeError("DIAGNOSTIC_FILE_WRITES_FORBIDDEN")

def sql_guard(action, table, column, database, trigger):
    return sqlite3.SQLITE_OK if action in {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ,
        sqlite3.SQLITE_FUNCTION, sqlite3.SQLITE_TRANSACTION, sqlite3.SQLITE_PRAGMA,
        sqlite3.SQLITE_SAVEPOINT, sqlite3.SQLITE_RECURSIVE} else sqlite3.SQLITE_DENY

# Force every SQLite connection into the confirmed active DB in mode=ro.
original_connect = sqlite3.connect
def readonly_connect(*args, **kwargs):
    args = list(args)
    requested = args[0] if args else kwargs.get("database")
    if str(requested) != str(EXPECTED_DB) and str(requested) != EXPECTED_DB.as_uri() + "?mode=ro":
        raise RuntimeError("UNEXPECTED_DATABASE_REFUSED")
    if args:
        args[0] = EXPECTED_DB.as_uri() + "?mode=ro"
    else:
        kwargs["database"] = EXPECTED_DB.as_uri() + "?mode=ro"
    kwargs["uri"] = True
    connection = original_connect(*args, **kwargs)
    connection.execute("PRAGMA query_only=ON")
    connection.set_authorizer(sql_guard)
    return connection

sqlite3.connect = readonly_connect
sqlite3.dbapi2.connect = readonly_connect
sys.addaudithook(guard)

try:
    stage = "service_and_settings"
    inputs = read_input(sys.argv)
    service_root = Path(inputs["service_directory"]) if inputs["service_directory"] else None
    root = service_root if service_root and (service_root / "manage.py").is_file() else EXPECTED_ROOT
    sys.path.insert(0, str(root))
    os.environ["DJANGO_SETTINGS_MODULE"] = inputs["service_settings"] or os.environ.get("DJANGO_SETTINGS_MODULE", "config.settings")
    report["runtime"] = dict(service_app_directory=inputs["service_directory"] or "NOT_AVAILABLE",
        service_application=inputs["service_python"] or "NOT_AVAILABLE", service_wsgi_module=inputs["service_module"] or "NOT_AVAILABLE",
        settings_module=os.environ["DJANGO_SETTINGS_MODULE"], diagnostic_source_root=str(root),
        service_directory_matches_expected=service_root == EXPECTED_ROOT if service_root else None,
        installed_file_sha256=hashlib.sha256((EXPECTED_ROOT / "apps/printing/inventory_users.py").read_bytes()).hexdigest())
    from django.conf import settings
    configured = settings.DATABASES["default"]
    if configured["ENGINE"] != "django.db.backends.sqlite3" or Path(configured["NAME"]).resolve() != EXPECTED_DB.resolve():
        raise RuntimeError("DATABASE_CONFIG_DIFFERS_FROM_CONFIRMED_ACTIVE_DATABASE")
    settings.DEBUG = False
    import django
    django.setup()
    from django.contrib.auth import get_user_model
    from django.db import connection, transaction
    from django.db.models import Q
    from django.http import QueryDict
    from django.urls import resolve
    from apps.printing.models import PrintingDevice, PrintingDeviceUserAssignment
    from apps.printing import inventory_users
    report["runtime"]["imported_search_file"] = inventory_users.__file__
    report["runtime"]["imported_file_sha256"] = hashlib.sha256(Path(inventory_users.__file__).read_bytes()).hexdigest()

    stage = "request_route_and_templates"
    allowed_filters = ("lifecycle", "department", "user_unit", "installation", "location", "brand", "model", "status")
    requests = {}
    report["requests"] = {}
    for label, url in (("Ariel", inputs["ariel_url"]), ("Silvio", inputs["silvio_url"]), ("department", inputs["third_url"])):
        parsed = urlsplit(url)
        if parsed.scheme and parsed.scheme not in {"http", "https"}:
            raise RuntimeError("INVALID_SEARCH_URL")
        match = resolve(parsed.path)
        params = QueryDict(parsed.query)
        requests[label] = params
        item = dict(path=parsed.path, resolved_view=match.func.__module__ + "." + match.func.__name__,
            search_present="search" in params, search_equals_expected_person=params.get("search", "").strip().casefold() == label.casefold() if label != "department" else None,
            search_token_count=len(params.get("search", "").split()),
            repeated_parameter_names=[key for key in params if len(params.getlist(key)) > 1],
            supplied_filter_names=[key for key in allowed_filters if params.get(key)],
            lifecycle=params.get("lifecycle", "active"), page_supplied="page" in params,
            unexpected_parameter_names=[key for key in params if key not in (*allowed_filters, "search", "page")])
        item.update(classify_query(params))
        report["requests"][label] = item
        if match.func.__module__ != "apps.printing.views" or match.func.__name__ != "printing_devices_by_model":
            raise RuntimeError("URL_IS_NOT_THE_PRINTING_INVENTORY_VIEW")
        view = inspect.unwrap(match.func)
        item["resolved_view_file"] = inspect.getsourcefile(view)
        item["view_delegates_to_inventory_context"] = "inventory_context(request)" in inspect.getsource(view)
    report["third_url_is_department_filter"] = bool(report["requests"]["department"]["active_department_fields"])
    report["templates"] = {}
    for name in ("psline_dashboard.html", "printing_devices_by_model.html"):
        text = (root / "templates/printing" / name).read_text(encoding="utf-8-sig")
        report["templates"][name] = dict(has_search_input='name="search"' in text,
            has_inventory_route="printing:devices_by_model" in text,
            has_department_filter='name="department"' in text,
            has_institutional_unit_filter='name="user_unit"' in text,
            has_installation_department_filter='name="installation"' in text,
            sha256=hashlib.sha256(text.encode()).hexdigest())

    stage = "read_only_snapshot"
    def contains(value):
        return TERM.casefold() in str(value or "").casefold()

    def nested_match(value):
        if isinstance(value, dict):
            return any(nested_match(item) for item in value.values())
        if isinstance(value, list):
            return any(nested_match(item) for item in value)
        return contains(value)

    with transaction.atomic():
        assert connection.cursor().execute("PRAGMA query_only").fetchone()[0] == 1
        User = get_user_model()
        report["people"] = {}
        for TERM in ("Ariel", "Silvio"):
            person = {}
            report["people"][TERM] = person
            people = User.objects.filter(Q(first_name__icontains=TERM) | Q(last_name__icontains=TERM) | Q(username__icontains=TERM))
            person_ids = list(people.values_list("pk", flat=True))
            email_only = User.objects.filter(email__icontains=TERM).exclude(pk__in=person_ids)
            person["local_accounts"] = dict(name_or_username_matches=len(person_ids), active_matches=people.filter(is_active=True).count(), email_only_matches=email_only.count())
            active_assignments = PrintingDeviceUserAssignment.objects.filter(user_id__in=person_ids, ended_at__isnull=True)
            ended_assignments = PrintingDeviceUserAssignment.objects.filter(user_id__in=person_ids, ended_at__isnull=False)
            active_devices = set(active_assignments.values_list("device_id", flat=True))
            ended_devices = set(ended_assignments.values_list("device_id", flat=True))
            sql_snapshot = set(PrintingDevice.objects.filter(responsible_identity__name__icontains=TERM).values_list("pk", flat=True))
            sql_fk = set(PrintingDevice.objects.filter(responsible_user_id__in=person_ids).values_list("pk", flat=True))
            person["stored_matches"] = dict(total_printers=PrintingDevice.objects.count(),
                responsible_fk=len(sql_fk), responsible_json_name_sql=len(sql_snapshot),
                current_assignment_printers=len(active_devices), ended_assignment_printers=len(ended_devices))
            # Report only operational printer ID and boolean source matches, never
            # names, emails, usernames, person IDs, notes or JSON values.
            related = []
            for device in PrintingDevice.objects.select_related("responsible_user", "asset__assigned_user"):
                snapshot = device.responsible_identity
                json_name = snapshot.get("name") if isinstance(snapshot, dict) else None
                asset_user = device.asset.assigned_user if device.asset_id else None
                flags = dict(fk_name_match=device.pk in sql_fk, snapshot_name_python_match=contains(json_name),
                    snapshot_name_sql_match=device.pk in sql_snapshot, snapshot_other_value_match=nested_match(snapshot) and not contains(json_name),
                    notes_has_term=contains(device.notes), asset_assigned_person_matches=bool(asset_user and asset_user.pk in person_ids),
                    current_assignment_match=device.pk in active_devices, ended_assignment_match=device.pk in ended_devices)
                flags["fk_email_only_match"] = bool(device.responsible_user_id and contains(device.responsible_user.email) and device.pk not in sql_fk)
                flags["snapshot_email_only_match"] = isinstance(snapshot, dict) and contains(snapshot.get("email")) and not contains(json_name)
                flags["displayed_responsible_matches"] = contains(device.responsible_display_name) if isinstance(snapshot, dict) else False
                if any(flags.values()):
                    related.append(dict(printer_id=device.photocopier_id or "NO_OPERATIONAL_ID", active=device.is_active,
                        has_responsible_fk=bool(device.responsible_user_id), snapshot_type=type(snapshot).__name__,
                        snapshot_has_name_key=isinstance(snapshot, dict) and "name" in snapshot, **flags))
            person["printer_match_sources"] = related
        from apps.core.models import Department
        from apps.institution.models import OrganizationalUnit
        report["relationship_coverage"] = dict(
            printers_with_responsible_fk=PrintingDevice.objects.filter(responsible_user__isnull=False).count(),
            printers_with_snapshot_name=PrintingDevice.objects.filter(responsible_identity__name__isnull=False).count(),
            printers_with_responsible_operational_department=PrintingDevice.objects.filter(responsible_user__department__isnull=False).count(),
            printers_with_responsible_institutional_unit=PrintingDevice.objects.filter(responsible_user__organizational_unit__isnull=False).count(),
            printers_with_current_user_operational_department=PrintingDeviceUserAssignment.objects.filter(ended_at__isnull=True, user__department__isnull=False).values("device_id").distinct().count(),
            printers_with_current_user_institutional_unit=PrintingDeviceUserAssignment.objects.filter(ended_at__isnull=True, user__organizational_unit__isnull=False).values("device_id").distinct().count(),
            printers_with_asset=PrintingDevice.objects.filter(asset__isnull=False).count(),
            printers_with_installation_department=PrintingDevice.objects.filter(asset__isnull=False).exclude(asset__department="").count())
        report["selected_departments"] = {}
        for key, catalog, user_field in (("department", Department, "department"), ("user_unit", OrganizationalUnit, "organizational_unit")):
            value = requests["department"].get(key, "")
            if not value:
                continue
            valid = value.isascii() and value.isdigit() and len(value) < 19
            entry = catalog.objects.filter(pk=value).first() if valid else None
            entry_report = dict(valid_id_format=valid, exists_in_expected_catalog=entry is not None)
            if entry is not None:
                linked_users = User.objects.filter(**{user_field+"_id": entry.pk})
                entry_report["local_user_count"] = linked_users.count()
                entry_report["responsible_printer_count"] = PrintingDevice.objects.filter(responsible_user__in=linked_users).count()
                entry_report["current_assignment_printer_count"] = PrintingDeviceUserAssignment.objects.filter(ended_at__isnull=True, user__in=linked_users).values("device_id").distinct().count()
                entry_report["catalog_label_in_legacy_notes_count"] = PrintingDevice.objects.filter(notes__icontains=entry.name).count()
                entry_report["catalog_label_in_asset_department_count"] = PrintingDevice.objects.filter(asset__department__icontains=entry.name).count()
            report["selected_departments"][key] = entry_report
        stage = "actual_search_function"
        report["actual_queries"] = {}
        with patch.object(inventory_users, "enrich_person_records", side_effect=lambda records, *args: list(records)):
            def evaluate(query):
                sql_shapes = []
                def record_sql(execute, sql, params, many, context):
                    sql_shapes.append(sql)
                    return execute(sql, params, many, context)
                with connection.execute_wrapper(record_sql):
                    context = inventory_users.inventory_context(SimpleNamespace(GET=query))
                # Count SQL contains filters, unlike page SELECTs that include
                # responsible fields even when they are not searched.
                joined = " ".join(sql for sql in sql_shapes if sql.lstrip().casefold().startswith("select count(")).casefold()
                return dict(total=context["total"], sql_statement_count=len(sql_shapes),
                    search_sql_mentions_responsible_account="responsible_user_id" in joined,
                    search_sql_mentions_responsible_snapshot="responsible_identity" in joined,
                    search_sql_mentions_user_assignments="printing_printingdeviceuserassignment" in joined)
            for label, params in requests.items():
                item = dict(received_url=evaluate(params))
                if label != "department":
                    item["person_without_other_filters"] = evaluate(QueryDict("search=" + label + "&lifecycle=all"))
                item["without_each_filter"] = {}
                for key in allowed_filters:
                    if params.get(key):
                        modified = params.copy()
                        modified.pop(key, None)
                        item["without_each_filter"][key] = evaluate(modified)["total"]
                report["actual_queries"][label] = item
            report["actual_queries"]["all_inventory_without_search"] = evaluate(QueryDict("lifecycle=all"))
        report["readonly"] = dict(sqlite_mode="ro", query_only=True, mutations_denied=True,
            external_directory_enrichment_skipped=True, network_and_process_launch_denied=True)
    connection.close()
    report["status"] = "DIAGNOSTIC_COMPLETE"
except Exception as exc:
    report["status"] = "DIAGNOSTIC_STOPPED"
    report["stage"] = stage
    # Omit exception text/tracebacks, which can contain personal data or SQL.
    report["error_type"] = type(exc).__name__
    if isinstance(exc, RuntimeError) and str(exc).replace("_", "").isalnum():
        report["error_code"] = str(exc)
finally:
    output()
'@
$EntradaDiagnostico = @{
    ariel_url = $Url
    silvio_url = $UrlSilvio
    third_url = $UrlDepartamento
    service_directory = $ServiceDirectory
    service_python = $ServicePython
    service_module = $ServiceModule
    service_settings = $ServiceSettings
} | ConvertTo-Json -Compress
$ArgumentoDiagnostico = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($EntradaDiagnostico))
$Codigo | & $Python -I -B - $ArgumentoDiagnostico
