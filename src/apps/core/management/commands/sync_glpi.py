import json

from django.core.management.base import BaseCommand, CommandError

from apps.integrations.glpi_client import GLPIClient, GLPIConfig, GLPIError
from apps.integrations.glpi_diagnostic_stage import DiagnosticStage
from apps.integrations.glpi_diagnostics import (
    printer_diagnostics, computer_diagnostics, user_diagnostics,
    location_diagnostics, printer_network_ips, counts, SERIAL_STATES,
)


class Command(BaseCommand):
    help = "Diagnostico GLPI -> NovaDesk exclusivamente de lectura. No sincroniza datos."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--section", choices=("printers", "computers", "users", "all"), default="all")
        parser.add_argument("--with-network", action="store_true", help="Consulta NetworkPort, NetworkName e IPAddress para diagnosticar IPs de impresoras.")

    def handle(self, *args, **options):
        if not options["dry_run"]:
            raise CommandError("Modo escritura no habilitado. Use --dry-run.")
        stage = DiagnosticStage()
        try:
            config = GLPIConfig.from_env()
            client = GLPIClient(config)
            datasets, reports = {}, {}
            section = options["section"]
            stage.set("apertura de sesion GLPI")
            with client:
                stage.set("carga Location")
                datasets["Location"] = client.items("Location")
                if section in {"printers", "all"}:
                    stage.set("carga Printer")
                    datasets["Printer"] = client.items("Printer", expand=True)
                    network = None
                    if options["with_network"]:
                        for name in ("NetworkPort", "NetworkName", "IPAddress"):
                            stage.set(f"carga {name}")
                            datasets[name] = client.items(name)
                        network = printer_network_ips(datasets["NetworkPort"], datasets["NetworkName"], datasets["IPAddress"], stage=stage)
                    stage.set("generacion del diagnostico de impresoras")
                    reports["IMPRESORAS"] = printer_diagnostics(datasets["Printer"], datasets["Location"], network)
                if section in {"computers", "all"}:
                    stage.set("diagnostico de computadoras")
                    datasets["Computer"] = client.items("Computer")
                    reports["COMPUTADORAS"] = computer_diagnostics(datasets["Computer"])
                if section in {"users", "all"}:
                    stage.set("diagnostico de usuarios")
                    datasets["User"] = client.items("User")
                    for user in datasets["User"]:
                        emails = client.items(f"User/{user['id']}/UserEmail")
                        user["emails"] = [row.get("email") for row in emails if row.get("email")]
                    reports["USUARIOS"] = user_diagnostics(datasets["User"])
                stage.set("diagnostico de ubicaciones")
                reports["UBICACIONES"] = location_diagnostics(datasets["Location"])
                stage.set("cierre de sesion GLPI")
            # Output only whitelisted diagnostics, after successful session close.
            stage.set("salida del informe")
            self.stdout.write("SOLO LECTURA: no se modifican datos GLPI ni NovaDesk.")
            self.stdout.write("GLPI (alcance: entidades y permisos visibles para la cuenta API)")
            for name in ("User", "Computer", "Printer", "Location", "NetworkPort", "NetworkName", "IPAddress"):
                self.stdout.write(f"  {name}: {len(datasets[name]) if name in datasets else 'NO CONSULTADO'}")
            for title, rows in reports.items():
                self.stdout.write(title)
                for row in rows:
                    self.stdout.write(client.redact(json.dumps(row, ensure_ascii=False, default=str)))
                summary = counts(rows)
                states = SERIAL_STATES if title in {"IMPRESORAS", "COMPUTADORAS"} else sorted(summary)
                self.stdout.write("  Resumen: " + " | ".join(f"{state}={summary.get(state, 0)}" for state in states))
            self.stdout.write("ERROR=0")
        except GLPIError as exc:
            self.stderr.write("ERROR=1 | Diagnostico incompleto; ningun dato modificado.")
            raise CommandError(str(exc)) from None
        except Exception as exc:
            # Django's explicit --traceback is useful only with controlled test mocks.
            if options.get("traceback"):
                raise
            self.stderr.write("ERROR=1 | Diagnostico incompleto; ningun dato modificado.")
            if options["with_network"]:
                message = stage.failure(exc)
                if "client" in locals():
                    message = client.redact(message)
                raise CommandError(message) from None
            raise CommandError("No se pudo completar el diagnostico. Revise esquema local y disponibilidad de fuentes; no se imprimen respuestas o excepciones sensibles.") from None
