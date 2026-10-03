from collections import defaultdict

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.institution.models import OrganizationalUnit


STRUCTURE = [
    ("PRES", "Presidencia"),
    ("PRES-SEC-PRIV", "Secretaría Privada"),
    ("PRES-GAB", "Dirección Gabinete de Presidencia"),
    ("PRES-GAB-DNCSP", "Unidad Desarrollo de Negocios y Compras Spot"),
    ("PRES-GAB-EXPEXP", "Unidad Exploración y Explotación"),
    ("PRES-GAB-EXPEXP-TEC", "Dpto. Técnico"),
    ("PRES-GAB-EXPEXP-CONFIS", "Dpto. Contratos y Fiscalización"),
    ("PRES-GAB-SGP", "Sub-Gerencia de Planificación"),
    ("PRES-GAB-SGP-PCG", "Dpto. Planificación y Control de Gestión"),
    ("PRES-GAB-SGP-DC", "Dpto. Desarrollo Corporativo"),

    ("PRES-SEG", "Dirección de Seguridad y Vigilancia"),
    ("PRES-SEG-GC", "Unidad de Gestión y Control"),
    ("PRES-SEG-GC-ASV", "Dpto. Administración de Servicios de Vigilancia"),
    (
        "PRES-SEG-GC-MJT",
        "Dpto. de Seguridad y Vigilancia Planta M. J. Troche",
    ),
    (
        "PRES-SEG-GC-PIP",
        "Dpto. Protección de Instalaciones Portuarias",
    ),

    ("PRES-DTI", "Dirección de Tecnología de la Información"),
    ("PRES-DTI-GC", "Unidad de Gestión y Control"),
    ("PRES-DTI-GC-NT", "Dpto. Normas Técnicas"),
    ("PRES-DTI-GC-SI", "Dpto. Sistemas de Información"),
    ("PRES-DTI-UT", "Unidad Técnica"),
    ("PRES-DTI-UT-ST", "Dpto. Servicios Tecnológicos"),
    ("PRES-DTI-UT-AE", "Dpto. Administración de Equipos"),
    ("PRES-DTI-UT-MJT", "Dpto. Informática - M. J. Troche"),

    (
        "PRES-SISOMA",
        "Gerencia Seguridad Industrial, Salud Ocupacional y Medio Ambiente",
    ),
    (
        "PRES-SISOMA-GASI",
        "Unidad de Gestión Ambiental y Seguridad Industrial",
    ),
    ("PRES-SISOMA-MAVE", "Dpto. Medio Ambiente - Villa Elisa"),
    ("PRES-SISOMA-SIVE", "Dpto. Seguridad Industrial - Villa Elisa"),
    (
        "PRES-SISOMA-SIMJT",
        "Dpto. Seguridad Industrial y Medio Ambiente - M. J. Troche",
    ),
    (
        "PRES-SISOMA-SOSS",
        "Dpto. de Salud Ocupacional y Seguridad Social",
    ),

    ("PRES-JUR", "Dirección Jurídica"),
    ("PRES-JUR-ADJ", "Director Jurídico Adjunto"),
    ("PRES-JUR-GCJ", "Unidad de Gestión y Control Jurídico"),
    ("PRES-JUR-GCJ-JA", "Dpto. Jurídico Administrativo"),
    ("PRES-JUR-GCJ-LIT", "Dpto. Litigios"),
    ("PRES-JUR-GCJ-CL", "Dpto. Contratos y Licitaciones"),

    ("PRES-AUD", "Auditoría Interna"),
    ("PRES-AUD-GC", "Unidad de Gestión y Control"),
    ("PRES-AUD-FIN", "Dpto. Auditoría Financiera"),
    ("PRES-AUD-GEST", "Dpto. Auditoría de Gestión"),
    ("PRES-AUD-FOR", "Dpto. Auditoría Forense"),

    ("PRES-PROT", "Dirección de Protocolo y Ceremonial"),
    ("PRES-ENLACE", "Gerencia de Enlace Corporativo"),

    ("PRES-DGE", "Dirección de Gestión Empresarial"),
    (
        "PRES-DGE-GPDO",
        "Unidad Gestión de Personas y Desarrollo Organizacional",
    ),
    ("PRES-DGE-GPDO-GP", "Dpto. Gestión de Personas"),
    ("PRES-DGE-GPDO-DO", "Dpto. Desarrollo Organizacional"),
    ("PRES-DGE-RRHH", "Unidad Gestión de Recursos Humanos"),
    ("PRES-DGE-RRHH-AP", "Dpto. Administración del Personal"),
    ("PRES-DGE-RRHH-REM", "Dpto. de Remuneraciones"),
    (
        "PRES-DGE-RRHH-CLP",
        "Dpto. de Consultoría Laboral del Personal",
    ),
    ("PRES-DGE-APOYO", "Unidad de Apoyo"),
    ("PRES-DGE-APOYO-SG", "Dpto. Servicios Generales"),
    ("PRES-DGE-APOYO-RS", "Dpto. de Responsabilidad Social"),
    ("PRES-DGE-ASISP", "Unidad Asistencia al Personal"),
    ("PRES-DGE-ASISP-BP", "Dpto. Bienestar del Personal"),

    ("PRES-DPO", "Dirección de Proyectos y Obras"),
    ("PRES-DPO-AL", "Unidad de Administración y Logística"),
    ("PRES-DPO-PP", "Unidad de Programación y Planificación"),

    ("PRES-COM", "Dirección de Comunicación"),
    ("PRES-COM-GC", "Unidad de Gestión y Control"),
    ("PRES-COM-MKT", "Unidad de Marketing Institucional"),
    (
        "PRES-COM-CIEI",
        "Dpto. de Comunicación Interna y Enlace Interinstitucional",
    ),
    ("PRES-COM-PGA", "Dpto. de Producción Gráfica y Audiovisual"),
    ("PRES-COM-PRENSA", "Dpto. de Prensa"),

    ("PRES-TRANS", "Dirección de Transparencia"),
    ("PRES-TRANS-GC", "Unidad de Gestión y Control"),
    (
        "PRES-TRANS-DEN",
        "Dpto. de Investigación y Seguimientos de Denuncias",
    ),
    ("PRES-TRANS-AI", "Dpto. de Acceso a la Información"),
    (
        "PRES-TRANS-TAI",
        "Dpto. de Transparencia Activa Institucional",
    ),

    ("GG", "Gerencia General"),

    ("GG-GPVE", "Gerencia de Planta Villa Elisa"),
    ("GG-GPVE-OP", "Gerencia de Operaciones y Proceso"),
    ("GG-GPVE-OP-OP", "Dpto. Operaciones en Planta"),
    ("GG-GPVE-OP-DIST", "Dpto. Distribución"),
    ("GG-GPVE-OP-GLP", "Dpto. Operaciones GLP"),
    ("GG-GPVE-OP-JP", "Dpto. de Jefatura de Planta"),

    ("GG-GPVE-CP", "Gerencia Control de Producto"),
    (
        "GG-GPVE-CP-CCVE",
        "Dpto. Control de Calidad Planta Villa Elisa",
    ),
    ("GG-GPVE-CP-CC", "Dpto. Control de Cantidad"),
    ("GG-GPVE-CP-GC", "Dpto. Gestión de la Calidad"),
    (
        "GG-GPVE-CP-CCE",
        "Dpto. Control de Calidad Plantas Externas y EESS",
    ),
    (
        "GG-GPVE-CP-SIE",
        "Dpto. Sistema de la Información y Estadísticas",
    ),

    ("GG-GPVE-MANT", "Gerencia de Mantenimiento de Planta"),
    (
        "GG-GPVE-MANT-FOCE",
        "Unidad de Fiscalización de Obras y Cálculos Estructurales",
    ),
    (
        "GG-GPVE-MANT-PE",
        "Unidad de Proyectos Electromecánicos",
    ),
    ("GG-GPVE-MANT-POC", "Unidad de Proyectos de Obras Civiles"),
    (
        "GG-GPVE-MANT-MCM",
        "Departamento Mantenimiento Civil y Mecánico",
    ),
    ("GG-GPVE-MANT-OBRAS", "Departamento de Obras"),
    ("GG-GPVE-GC", "Unidad de Gestión y Control"),

    ("GG-GPIMJT", "Gerencia Planta Industrial M. J. Troche"),
    (
        "GG-GPIMJT-RST",
        "Oficina de Responsabilidad Social y Transparencia",
    ),
    ("GG-GPIMJT-GC", "Unidad de Gestión y Control"),

    ("GG-GPIMJT-PROD", "Gerencia de Producción"),
    ("GG-GPIMJT-PROD-DP", "Dpto. de Producción"),
    ("GG-GPIMJT-PROD-CC", "Dpto. Control de Calidad"),

    ("GG-GPIMJT-PA", "Dpto. de Planificación Agrícola"),
    ("GG-GPIMJT-PA-ADM", "Dpto. de Administración"),

    ("GG-GPIMJT-MANT", "Gerencia de Mantenimiento"),
    ("GG-GPIMJT-MANT-DM", "Dpto. de Mantenimiento"),
    ("GG-GPIMJT-MANT-AP", "Dpto. de Apoyo de Planta"),

    ("GG-DNN", "Dirección Nuevos Negocios"),
    ("GG-DNN-AVI", "Unidad Aviación"),

    ("GG-SG", "Secretaría General"),
    ("GG-SG-PROC", "Dpto. de Procesamiento"),
    ("GG-SG-TEC", "Dpto. Técnico"),

    ("GG-GCE", "Gerencia Comercio Exterior"),
    ("GG-GCE-CON", "Unidad Gestión de Contratos"),
    ("GG-GCE-CON-AI", "Dpto. Abastecimiento e Inspección"),
    ("GG-GCE-SUM", "Unidad Administración de Suministros"),
    ("GG-GCE-SUM-LP", "Dpto. Logística Primaria"),
    ("GG-GCE-GC", "Unidad de Gestión y Control"),
    ("GG-GCE-GC-GA", "Dpto. Gestión Aduanera"),
    ("GG-GCE-PD", "Unidad de Planificación y Desarrollo"),
    (
        "GG-GCE-PD-TAE",
        "Dpto. Técnico, Administrativo y Estadístico",
    ),

    ("GG-MECIP", "Unidad de Gestión y Control MECIP"),
    ("GG-MECIP-DI", "Dpto. Diagnóstico e Implementación MECIP"),
    ("GG-MECIP-SM", "Dpto. Seguimiento y Mejoramiento MECIP"),

    ("GG-DOC", "Dirección Operativa de Contrataciones"),
    ("GG-DOC-ADJ", "Dirección Adjunta"),
    (
        "GG-DOC-ADJ-GCP",
        "Unidad de Gestión y Control de Procesos",
    ),
    ("GG-DOC-ADJ-GCP-CONV", "Dpto. Convocatorias"),
    ("GG-DOC-ADJ-PP", "Unidad Planificación de Procesos"),
    ("GG-DOC-ADJ-PP-PROG", "Dpto. Programación"),
    (
        "GG-DOC-ADJ-VE",
        "Unidad de Verificación de Ejecución",
    ),
    ("GG-DOC-ADJ-VE-CG", "Dpto. Contratos y Garantías"),

    ("GG-DF", "Dirección Financiera"),
    ("GG-DF-GP", "Unidad de Gestión Patrimonial"),
    ("GG-DF-GP-PAT", "Dpto. Patrimonio"),
    ("GG-DF-GP-ALM", "Dpto. Almacenes"),

    ("GG-DF-GC", "Unidad de Gestión Contable"),
    ("GG-DF-GC-PRES", "Dpto. Presupuesto"),
    ("GG-DF-GC-SICO", "Dpto. SICO"),
    ("GG-DF-GC-CC", "Dpto. Contabilidad y Costos"),

    # El documento oficial contiene literalmente esta denominación.
    ("GG-DF-GC-IMP", "Dpto. Dpto. Impuesto"),

    ("GG-DF-GA", "Unidad de Gestión Administrativa"),
    ("GG-DF-GA-EGR", "Dpto. Egresos"),
    ("GG-DF-GA-ING", "Dpto. Ingresos"),
    ("GG-DF-GA-CGC", "Dpto. Crédito y Gestión de Cobranzas"),

    ("GG-DC", "Dirección Comercial"),

    ("GG-DC-RETAIL", "Sub-Gerencia Retail"),
    ("GG-DC-RETAIL-EO", "Unidad EESS de Operadores"),
    (
        "GG-DC-RETAIL-EO-PFO",
        "Dpto. Proyectos y Fiscalización de Obras",
    ),
    (
        "GG-DC-RETAIL-EO-AEO",
        "Dpto. Administración de EESS con Operadores",
    ),
    (
        "GG-DC-RETAIL-EO-RCS",
        "Representante Comercial Senior",
    ),

    ("GG-DC-RETAIL-EP", "Unidad EESS Propias"),
    (
        "GG-DC-RETAIL-EP-ADM",
        "Dpto. Administración de EESS Propias",
    ),
    ("GG-DC-RETAIL-LUB", "Unidad Lubricantes"),
    ("GG-DC-RETAIL-GLP", "Unidad GLP"),

    ("GG-DC-GC", "Sub-Gerencia Grandes Consumidores"),
    ("GG-DC-GC-CC", "Unidad Cuentas Corporativas"),
    ("GG-DC-GC-CC-AC", "Dpto. Atención al Cliente"),
    ("GG-DC-GC-CC-ADC", "Dpto. Administración de Contratos"),
    ("GG-DC-GC-CC-OS", "Dpto. Operación de Sistemas"),

    ("GG-DC-GC-BUNKER", "Unidad de Bunker"),

    ("GG-DC-GC-GCC", "Unidad Gestión y Control Comercial"),
    ("GG-DC-GC-GCC-CS", "Dpto. Contratos y Suministros"),
    ("GG-DC-GC-GCC-V", "Dpto. Ventas"),
    (
        "GG-DC-GC-GCC-PSP",
        "Dpto. Provisión Sector Privado y Otros",
    ),
]


def get_parent_code(code):
    if code in {"PRES", "GG"}:
        return None

    if code == "PRES-SEC-PRIV":
        return "PRES"

    return code.rsplit("-", 1)[0]


def get_unit_type(code, name):
    unit_type = OrganizationalUnit.UnitType

    if code == "PRES":
        return unit_type.PRESIDENCY

    if code == "GG":
        return unit_type.GENERAL_MANAGEMENT

    if name.startswith("Sub-Gerencia"):
        return unit_type.SUB_MANAGEMENT

    if (
        name.startswith("Dirección Adjunta")
        or name == "Director Jurídico Adjunto"
    ):
        return unit_type.DEPUTY_DIRECTORATE

    if name.startswith("Dirección"):
        return unit_type.DIRECTORATE

    if name.startswith("Gerencia"):
        return unit_type.MANAGEMENT

    if name.startswith("Unidad"):
        return unit_type.UNIT

    if name.startswith("Oficina"):
        return unit_type.OFFICE

    if (
        name.startswith("Dpto.")
        or name.startswith("Departamento")
    ):
        return unit_type.DEPARTMENT

    return unit_type.OTHER


class Command(BaseCommand):
    help = "Carga o actualiza el organigrama institucional de PETROPAR."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help=(
                "Ejecuta toda la carga pero revierte la transacción "
                "al finalizar."
            ),
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]

        created_count = 0
        updated_count = 0
        processed_count = 0

        sibling_order = defaultdict(int)
        objects_by_code = {}

        with transaction.atomic():
            for code, name in STRUCTURE:
                parent_code = get_parent_code(code)
                parent = None

                if parent_code:
                    parent = objects_by_code.get(parent_code)

                    if parent is None:
                        raise RuntimeError(
                            f"No se encontró el padre {parent_code} "
                            f"para {code}."
                        )

                sibling_order[parent_code] += 1

                obj, created = OrganizationalUnit.objects.update_or_create(
                    code=code,
                    defaults={
                        "name": name,
                        "unit_type": get_unit_type(code, name),
                        "parent": parent,
                        "order": sibling_order[parent_code],
                        "is_active": True,
                    },
                )

                objects_by_code[code] = obj
                processed_count += 1

                if created:
                    created_count += 1
                    action = "CREADA"
                else:
                    updated_count += 1
                    action = "ACTUALIZADA"

                self.stdout.write(
                    f"{action}: {code} | {name}"
                )

            if dry_run:
                transaction.set_rollback(True)
                self.stdout.write("")
                self.stdout.write(
                    self.style.WARNING(
                        "MODO DRY-RUN: no se guardó ningún cambio."
                    )
                )

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                "Proceso finalizado. "
                f"Creadas: {created_count} | "
                f"Actualizadas: {updated_count} | "
                f"Total procesadas: {processed_count}"
            )
        )