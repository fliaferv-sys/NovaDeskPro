"""Prepare the approved Printing masters without importing equipment."""
from collections import Counter

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.accounts.models import Branch
from apps.inventory.models import OrganizationalLocation
from apps.printing.printer_import import PROVISIONAL_LOCATION_CODE, serial_key


SPECS = (
    ("PLANTA-VILLA-ELISA", "Planta Villa Elisa", Branch.BranchType.INDUSTRIAL_PLANT,
     ("Planta Villa Elisa", "Sede Villa Elisa")),
    ("OFICINA-CENTRAL", "Oficina Central", Branch.BranchType.OFFICE,
     ("Oficina Central",)),
    ("PLANTA-MAURICIO-JOSE-TROCHE", "Planta Mauricio Jos\u00e9 Troche",
     Branch.BranchType.INDUSTRIAL_PLANT, ("Planta Mauricio Jos\u00e9 Troche",)),
)


def plan_master_data(*, lock=False):
    plans = []
    branches = Branch.objects.all()
    locations = OrganizationalLocation.objects.all()
    if lock:
        branches = branches.select_for_update()
        locations = locations.select_for_update()
    branches = list(branches)
    locations = list(locations)
    for code, name, kind, allowed_names in SPECS:
        matches = [b for b in branches if serial_key(b.code) == serial_key(code)]
        if len(matches) > 1:
            raise CommandError(f"Conflicto de sede: varios registros para {code}.")
        branch = matches[0] if matches else None
        if branch:
            allowed_types = {kind}
            if code == "OFICINA-CENTRAL":
                allowed_types.add(Branch.BranchType.HEADQUARTERS)
            if (branch.code != code or serial_key(branch.name) not in
                    {serial_key(n) for n in allowed_names} or
                    branch.branch_type not in allowed_types or not branch.is_active):
                raise CommandError(f"Conflicto de sede {code}: nombre, tipo, codigo o estado incompatible.")
            plans.append(("SEDE", code, branch, False))
        else:
            branch = Branch(code=code, name=name, branch_type=kind, is_active=True)
            branch.full_clean()
            plans.append(("SEDE", code, branch, True))
        location_name = "Ubicaci\u00f3n pendiente de verificar - " + name
        # Both code and reserved name are checked within the correct branch.
        matches = [loc for loc in locations if loc.branch_id == branch.pk and
                   (serial_key(loc.code) == serial_key(PROVISIONAL_LOCATION_CODE) or
                    serial_key(loc.name) == serial_key(location_name))]
        if len(matches) > 1:
            raise CommandError(f"Conflicto de ubicacion: varios registros provisionales para {code}.")
        location = matches[0] if matches else None
        if location:
            if (location.code != PROVISIONAL_LOCATION_CODE or
                    location.name != location_name or not location.is_active or
                    location.parent_id is not None or
                    location.location_type != OrganizationalLocation.LocationType.OTHER):
                raise CommandError(f"Conflicto de ubicacion provisional para {code}: datos incompatibles.")
            plans.append(("UBICACION", code, location, False))
        else:
            location = OrganizationalLocation(
                branch=branch, code=PROVISIONAL_LOCATION_CODE, name=location_name,
                location_type=OrganizationalLocation.LocationType.OTHER, is_active=True,
            )
            # An unsaved planned branch has a UUID but does not exist in DB yet.
            location.full_clean(exclude=["branch"] if branch._state.adding else None)
            plans.append(("UBICACION", code, location, True))
    return plans


def save_master_data(plans):
    for _, _, obj, create in plans:
        if create:
            obj.save()


class Command(BaseCommand):
    help = "Prepara sedes y ubicaciones provisionales aprobadas para Printing."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Valida y simula sin escrituras.")

    def handle(self, *args, **options):
        try:
            if options["dry_run"]:
                plans = plan_master_data()
            else:
                with transaction.atomic():
                    plans = plan_master_data(lock=True)
                    save_master_data(plans)
        except CommandError:
            raise
        except ValidationError as exc:
            raise CommandError("Conflicto de validacion de datos maestros: " + "; ".join(exc.messages)) from exc
        except Exception as exc:
            raise CommandError("Error critico preparando datos maestros; ningun cambio confirmado (rollback).") from exc
        self.stdout.write("SIMULACION" if options["dry_run"] else "PREPARACION")
        counts = Counter()
        for entity, code, _, create in plans:
            status = "NUEVO" if create else "REUTILIZADO"
            counts[status] += 1
            self.stdout.write(f"{entity} {code}: {status}")
        self.stdout.write(f"Resumen: NUEVO={counts['NUEVO']} | REUTILIZADO={counts['REUTILIZADO']}")
