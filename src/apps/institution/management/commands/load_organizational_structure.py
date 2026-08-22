from django.core.management.base import BaseCommand
from django.db import transaction

from apps.institution.models import OrganizationalUnit


class Command(BaseCommand):
    help = "Carga o actualiza la estructura organizacional institucional de PETROPAR."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Simula la carga completa sin guardar cambios en la base de datos.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]

        # ----------------------------------------------------------
        # ESTRUCTURA ORGANIZACIONAL
        #
        # Formato:
        # (
        #     código,
        #     nombre,
        #     tipo,
        #     código_padre,
        #     orden,
        # )
        #
        # IMPORTANTE:
        # La lista está ordenada de padres a hijos.
        # ----------------------------------------------------------

        structure = [

            # ======================================================
            # PRESIDENCIA
            # ======================================================

            (
                "PRES",
                "Presidencia",
                "PRESIDENCY",
                None,
                10,
            ),

            (
                "PRES-SEC-PRIV",
                "Secretaría Privada",
                "OTHER",
                "PRES",
                10,
            ),

            # ======================================================
            # DIRECCIÓN GABINETE DE PRESIDENCIA
            # ======================================================

            (
                "PRES-GAB",
                "Dirección Gabinete de Presidencia",
                "DIRECTORATE",
                "PRES",
                20,
            ),

            (
                "PRES-GAB-DNCSP",
                "Unidad Desarrollo de Negocios y Compras Spot",
                "UNIT",
                "PRES-GAB",
                10,
            ),

            (
                "PRES-GAB-EXPEXP",
                "Unidad Exploración y Explotación",
                "UNIT",
                "PRES-GAB",
                20,
            ),

            (
                "PRES-GAB-EXPEXP-TEC",
                "Dpto. Técnico",
                "DEPARTMENT",
                "PRES-GAB-EXPEXP",
                10,
            ),

            (
                "PRES-GAB-EXPEXP-CONFIS",
                "Dpto. Contratos y Fiscalización",
                "DEPARTMENT",
                "PRES-GAB-EXPEXP",
                20,
            ),

            (
                "PRES-GAB-SGP",
                "Sub-Gerencia de Planificación",
                "SUB_MANAGEMENT",
                "PRES-GAB",
                30,
            ),

            (
                "PRES-GAB-SGP-PCG",
                "Dpto. Planificación y Control de Gestión",
                "DEPARTMENT",
                "PRES-GAB-SGP",
                10,
            ),

            (
                "PRES-GAB-SGP-DC",
                "Dpto. Desarrollo Corporativo",
                "DEPARTMENT",
                "PRES-GAB-SGP",
                20,
            ),

            # ======================================================
            # DIRECCIÓN DE SEGURIDAD Y VIGILANCIA
            # ======================================================

            (
                "PRES-SEG",
                "Dirección de Seguridad y Vigilancia",
                "DIRECTORATE",
                "PRES",
                30,
            ),

            (
                "PRES-SEG-GC",
                "Unidad de Gestión y Control",
                "UNIT",
                "PRES-SEG",
                10,
            ),

            (
                "PRES-SEG-GC-ASV",
                "Dpto. Administración de Servicios de Vigilancia",
                "DEPARTMENT",
                "PRES-SEG-GC",
                10,
            ),

            (
                "PRES-SEG-GC-MJT",
                "Dpto. de Seguridad y Vigilancia Planta M. J. Troche",
                "DEPARTMENT",
                "PRES-SEG-GC",
                20,
            ),

            (
                "PRES-SEG-GC-PIP",
                "Dpto. Protección de Instalaciones Portuarias",
                "DEPARTMENT",
                "PRES-SEG-GC",
                30,
            ),

            # ======================================================
            # DIRECCIÓN DE TECNOLOGÍA DE LA INFORMACIÓN
            # ======================================================

            (
                "PRES-DTI",
                "Dirección de Tecnología de la Información",
                "DIRECTORATE",
                "PRES",
                40,
            ),

            (
                "PRES-DTI-GC",
                "Unidad de Gestión y Control",
                "UNIT",
                "PRES-DTI",
                10,
            ),

            (
                "PRES-DTI-GC-NT",
                "Dpto. Normas Técnicas",
                "DEPARTMENT",
                "PRES-DTI-GC",
                10,
            ),

            (
                "PRES-DTI-GC-SI",
                "Dpto. Sistemas de Información",
                "DEPARTMENT",
                "PRES-DTI-GC",
                20,
            ),

            (
                "PRES-DTI-UT",
                "Unidad Técnica",
                "UNIT",
                "PRES-DTI",
                20,
            ),

            (
                "PRES-DTI-UT-ST",
                "Dpto. Servicios Tecnológicos",
                "DEPARTMENT",
                "PRES-DTI-UT",
                10,
            ),

            (
                "PRES-DTI-UT-AE",
                "Dpto. Administración de Equipos",
                "DEPARTMENT",
                "PRES-DTI-UT",
                20,
            ),

            (
                "PRES-DTI-UT-MJT",
                "Dpto. Informática - M. J. Troche",
                "DEPARTMENT",
                "PRES-DTI-UT",
                30,
            ),

            # ======================================================
            # SEGURIDAD INDUSTRIAL, SALUD OCUPACIONAL Y MEDIO AMBIENTE
            # ======================================================

            (
                "PRES-SISOMA",
                "Gerencia Seguridad Industrial, Salud Ocupacional y Medio Ambiente",
                "MANAGEMENT",
                "PRES",
                50,
            ),

            (
                "PRES-SISOMA-GASI",
                "Unidad de Gestión Ambiental y Seguridad Industrial",
                "UNIT",
                "PRES-SISOMA",
                10,
            ),

            (
                "PRES-SISOMA-MAVE",
                "Dpto. Medio Ambiente - Villa Elisa",
                "DEPARTMENT",
                "PRES-SISOMA-GASI",
                10,
            ),

            (
                "PRES-SISOMA-SIVE",
                "Dpto. Seguridad Industrial - Villa Elisa",
                "DEPARTMENT",
                "PRES-SISOMA-GASI",
                20,
            ),

            (
                "PRES-SISOMA-SIMJT",
                "Dpto. Seguridad Industrial y Medio Ambiente - M. J. Troche",
                "DEPARTMENT",
                "PRES-SISOMA-GASI",
                30,
            ),

            (
                "PRES-SISOMA-SOSS",
                "Dpto. de Salud Ocupacional y Seguridad Social",
                "DEPARTMENT",
                "PRES-SISOMA-GASI",
                40,
            ),

            # ======================================================
            # DIRECCIÓN JURÍDICA
            # ======================================================

            (
                "PRES-JUR",
                "Dirección Jurídica",
                "DIRECTORATE",
                "PRES",
                60,
            ),

            (
                "PRES-JUR-ADJ",
                "Director Jurídico Adjunto",
                "OTHER",
                "PRES-JUR",
                10,
            ),

            (
                "PRES-JUR-GCJ",
                "Unidad de Gestión y Control Jurídico",
                "UNIT",
                "PRES-JUR-ADJ",
                10,
            ),

            (
                "PRES-JUR-GCJ-JA",
                "Dpto. Jurídico Administrativo",
                "DEPARTMENT",
                "PRES-JUR-GCJ",
                10,
            ),

            (
                "PRES-JUR-GCJ-LIT",
                "Dpto. Litigios",
                "DEPARTMENT",
                "PRES-JUR-GCJ",
                20,
            ),

            (
                "PRES-JUR-GCJ-CL",
                "Dpto. Contratos y Licitaciones",
                "DEPARTMENT",
                "PRES-JUR-GCJ",
                30,
            ),

            # ======================================================
            # AUDITORÍA INTERNA
            # ======================================================

            (
                "PRES-AUD",
                "Auditoría Interna",
                "OTHER",
                "PRES",
                70,
            ),

            (
                "PRES-AUD-GC",
                "Unidad de Gestión y Control",
                "UNIT",
                "PRES-AUD",
                10,
            ),

            (
                "PRES-AUD-FIN",
                "Dpto. Auditoría Financiera",
                "DEPARTMENT",
                "PRES-AUD-GC",
                10,
            ),

            (
                "PRES-AUD-GEST",
                "Dpto. Auditoría de Gestión",
                "DEPARTMENT",
                "PRES-AUD-GC",
                20,
            ),

            (
                "PRES-AUD-FOR",
                "Dpto. Auditoría Forense",
                "DEPARTMENT",
                "PRES-AUD-GC",
                30,
            ),

            # ======================================================
            # PROTOCOLO Y CEREMONIAL
            # ======================================================

            (
                "PRES-PROT",
                "Dirección de Protocolo y Ceremonial",
                "DIRECTORATE",
                "PRES",
                80,
            ),

            # ======================================================
            # GERENCIA DE ENLACE CORPORATIVO
            # SIN DEPENDENCIAS HIJAS
            # ======================================================

            (
                "PRES-ENLACE",
                "Gerencia de Enlace Corporativo",
                "MANAGEMENT",
                "PRES",
                90,
            ),

            # ======================================================
            # DIRECCIÓN DE GESTIÓN EMPRESARIAL
            # ======================================================

            (
                "PRES-DGE",
                "Dirección de Gestión Empresarial",
                "DIRECTORATE",
                "PRES",
                100,
            ),

            (
                "PRES-DGE-GPDO",
                "Unidad Gestión de Personas y Desarrollo Organizacional",
                "UNIT",
                "PRES-DGE",
                10,
            ),

            (
                "PRES-DGE-GPDO-GP",
                "Dpto. Gestión de Personas",
                "DEPARTMENT",
                "PRES-DGE-GPDO",
                10,
            ),

            (
                "PRES-DGE-GPDO-DO",
                "Dpto. Desarrollo Organizacional",
                "DEPARTMENT",
                "PRES-DGE-GPDO",
                20,
            ),

            (
                "PRES-DGE-RRHH",
                "Unidad Gestión de Recursos Humanos",
                "UNIT",
                "PRES-DGE",
                20,
            ),

            (
                "PRES-DGE-RRHH-AP",
                "Dpto. Administración del Personal",
                "DEPARTMENT",
                "PRES-DGE-RRHH",
                10,
            ),

            (
                "PRES-DGE-RRHH-REM",
                "Dpto. de Remuneraciones",
                "DEPARTMENT",
                "PRES-DGE-RRHH",
                20,
            ),

            (
                "PRES-DGE-RRHH-CLP",
                "Dpto. de Consultoría Laboral del Personal",
                "DEPARTMENT",
                "PRES-DGE-RRHH",
                30,
            ),

            (
                "PRES-DGE-APOYO",
                "Unidad de Apoyo",
                "UNIT",
                "PRES-DGE",
                30,
            ),

            (
                "PRES-DGE-APOYO-SG",
                "Dpto. Servicios Generales",
                "DEPARTMENT",
                "PRES-DGE-APOYO",
                10,
            ),

            (
                "PRES-DGE-APOYO-RS",
                "Dpto. de Responsabilidad Social",
                "DEPARTMENT",
                "PRES-DGE-APOYO",
                20,
            ),

            (
                "PRES-DGE-ASISP",
                "Unidad Asistencia al Personal",
                "UNIT",
                "PRES-DGE",
                40,
            ),

            (
                "PRES-DGE-ASISP-BP",
                "Dpto. Bienestar del Personal",
                "DEPARTMENT",
                "PRES-DGE-ASISP",
                10,
            ),

            # ======================================================
            # DIRECCIÓN DE PROYECTOS Y OBRAS
            # ======================================================

            (
                "PRES-DPO",
                "Dirección de Proyectos y Obras",
                "DIRECTORATE",
                "PRES",
                110,
            ),

            (
                "PRES-DPO-AL",
                "Unidad de Administración y Logística",
                "UNIT",
                "PRES-DPO",
                10,
            ),

            (
                "PRES-DPO-PP",
                "Unidad de Programación y Planificación",
                "UNIT",
                "PRES-DPO",
                20,
            ),

            # ======================================================
            # DIRECCIÓN DE COMUNICACIÓN
            # ======================================================

            (
                "PRES-COM",
                "Dirección de Comunicación",
                "DIRECTORATE",
                "PRES",
                120,
            ),

            (
                "PRES-COM-GC",
                "Unidad de Gestión y Control",
                "UNIT",
                "PRES-COM",
                10,
            ),

            (
                "PRES-COM-MKT",
                "Unidad de Marketing Institucional",
                "UNIT",
                "PRES-COM",
                20,
            ),

            (
                "PRES-COM-CIEI",
                "Dpto. de Comunicación Interna y Enlace Interinstitucional",
                "DEPARTMENT",
                "PRES-COM",
                30,
            ),

            (
                "PRES-COM-PGA",
                "Dpto. de Producción Gráfica y Audiovisual",
                "DEPARTMENT",
                "PRES-COM",
                40,
            ),

            (
                "PRES-COM-PRENSA",
                "Dpto. de Prensa",
                "DEPARTMENT",
                "PRES-COM",
                50,
            ),

            # ======================================================
            # DIRECCIÓN DE TRANSPARENCIA
            # ======================================================

            (
                "PRES-TRANS",
                "Dirección de Transparencia",
                "DIRECTORATE",
                "PRES",
                130,
            ),

            (
                "PRES-TRANS-GC",
                "Unidad de Gestión y Control",
                "UNIT",
                "PRES-TRANS",
                10,
            ),

            (
                "PRES-TRANS-DEN",
                "Dpto. de Investigación y Seguimientos de Denuncias",
                "DEPARTMENT",
                "PRES-TRANS",
                20,
            ),

            (
                "PRES-TRANS-AI",
                "Dpto. de Acceso a la Información",
                "DEPARTMENT",
                "PRES-TRANS",
                30,
            ),

            (
                "PRES-TRANS-TAI",
                "Dpto. de Transparencia Activa Institucional",
                "DEPARTMENT",
                "PRES-TRANS",
                40,
            ),

            # ======================================================
            # GERENCIA GENERAL
            # ======================================================

            (
                "GG",
                "Gerencia General",
                "GENERAL_MANAGEMENT",
                "PRES",
                140,
            ),

            # ======================================================
            # GERENCIA DE PLANTA VILLA ELISA
            # ======================================================

            (
                "GG-GPVE",
                "Gerencia de Planta Villa Elisa",
                "MANAGEMENT",
                "GG",
                10,
            ),

            (
                "GG-GPVE-OP",
                "Gerencia de Operaciones y Proceso",
                "MANAGEMENT",
                "GG-GPVE",
                10,
            ),

            (
                "GG-GPVE-OP-OP",
                "Dpto. Operaciones en Planta",
                "DEPARTMENT",
                "GG-GPVE-OP",
                10,
            ),

            (
                "GG-GPVE-OP-DIST",
                "Dpto. Distribución",
                "DEPARTMENT",
                "GG-GPVE-OP",
                20,
            ),

            (
                "GG-GPVE-OP-GLP",
                "Dpto. Operaciones GLP",
                "DEPARTMENT",
                "GG-GPVE-OP",
                30,
            ),

            (
                "GG-GPVE-OP-JP",
                "Dpto. de Jefatura de Planta",
                "DEPARTMENT",
                "GG-GPVE-OP",
                40,
            ),

            (
                "GG-GPVE-CP",
                "Gerencia Control de Producto",
                "MANAGEMENT",
                "GG-GPVE",
                20,
            ),

            (
                "GG-GPVE-CP-CCVE",
                "Dpto. Control de Calidad Planta Villa Elisa",
                "DEPARTMENT",
                "GG-GPVE-CP",
                10,
            ),

            (
                "GG-GPVE-CP-CC",
                "Dpto. Control de Cantidad",
                "DEPARTMENT",
                "GG-GPVE-CP",
                20,
            ),

            (
                "GG-GPVE-CP-GC",
                "Dpto. Gestión de la Calidad",
                "DEPARTMENT",
                "GG-GPVE-CP",
                30,
            ),

            (
                "GG-GPVE-CP-CCE",
                "Dpto. Control de Calidad Plantas Externas y EESS",
                "DEPARTMENT",
                "GG-GPVE-CP",
                40,
            ),

            (
                "GG-GPVE-CP-SIE",
                "Dpto. Sistema de la Información y Estadísticas",
                "DEPARTMENT",
                "GG-GPVE-CP",
                50,
            ),

            (
                "GG-GPVE-MANT",
                "Gerencia de Mantenimiento de Planta",
                "MANAGEMENT",
                "GG-GPVE",
                30,
            ),

            (
                "GG-GPVE-MANT-FOCE",
                "Unidad de Fiscalización de Obras y Cálculos Estructurales",
                "UNIT",
                "GG-GPVE-MANT",
                10,
            ),

            (
                "GG-GPVE-MANT-PE",
                "Unidad de Proyectos Electromecánicos",
                "UNIT",
                "GG-GPVE-MANT",
                20,
            ),

            (
                "GG-GPVE-MANT-POC",
                "Unidad de Proyectos de Obras Civiles",
                "UNIT",
                "GG-GPVE-MANT",
                30,
            ),

            (
                "GG-GPVE-MANT-MCM",
                "Departamento Mantenimiento Civil y Mecánico",
                "DEPARTMENT",
                "GG-GPVE-MANT",
                40,
            ),

            (
                "GG-GPVE-MANT-OBRAS",
                "Departamento de Obras",
                "DEPARTMENT",
                "GG-GPVE-MANT",
                50,
            ),

            (
                "GG-GPVE-GC",
                "Unidad de Gestión y Control",
                "UNIT",
                "GG-GPVE",
                40,
            ),

            # ======================================================
            # GERENCIA PLANTA INDUSTRIAL M. J. TROCHE
            # ======================================================

            (
                "GG-GPIMJT",
                "Gerencia Planta Industrial M. J. Troche",
                "MANAGEMENT",
                "GG",
                20,
            ),

            (
                "GG-GPIMJT-RST",
                "Oficina de Responsabilidad Social y Transparencia",
                "OFFICE",
                "GG-GPIMJT",
                10,
            ),

            (
                "GG-GPIMJT-GC",
                "Unidad de Gestión y Control",
                "UNIT",
                "GG-GPIMJT",
                20,
            ),

            (
                "GG-GPIMJT-PROD",
                "Gerencia de Producción",
                "MANAGEMENT",
                "GG-GPIMJT",
                30,
            ),

            (
                "GG-GPIMJT-PROD-DP",
                "Dpto. de Producción",
                "DEPARTMENT",
                "GG-GPIMJT-PROD",
                10,
            ),

            (
                "GG-GPIMJT-PROD-CC",
                "Dpto. Control de Calidad",
                "DEPARTMENT",
                "GG-GPIMJT-PROD",
                20,
            ),

            (
                "GG-GPIMJT-PA",
                "Dpto. de Planificación Agrícola",
                "DEPARTMENT",
                "GG-GPIMJT",
                40,
            ),

            (
                "GG-GPIMJT-PA-ADM",
                "Dpto. de Administración",
                "DEPARTMENT",
                "GG-GPIMJT-PA",
                10,
            ),

            (
                "GG-GPIMJT-MANT",
                "Gerencia de Mantenimiento",
                "MANAGEMENT",
                "GG-GPIMJT",
                50,
            ),

            (
                "GG-GPIMJT-MANT-DM",
                "Dpto. de Mantenimiento",
                "DEPARTMENT",
                "GG-GPIMJT-MANT",
                10,
            ),

            (
                "GG-GPIMJT-MANT-AP",
                "Dpto. de Apoyo de Planta",
                "DEPARTMENT",
                "GG-GPIMJT-MANT",
                20,
            ),

            # ======================================================
            # DIRECCIÓN NUEVOS NEGOCIOS
            # DEPENDE DIRECTAMENTE DE GERENCIA GENERAL
            # ======================================================

            (
                "GG-DNN",
                "Dirección Nuevos Negocios",
                "DIRECTORATE",
                "GG",
                30,
            ),

            (
                "GG-DNN-AVI",
                "Unidad Aviación",
                "UNIT",
                "GG-DNN",
                10,
            ),

            # ======================================================
            # SECRETARÍA GENERAL
            # ======================================================

            (
                "GG-SG",
                "Secretaría General",
                "OTHER",
                "GG",
                40,
            ),

            (
                "GG-SG-PROC",
                "Dpto. de Procesamiento",
                "DEPARTMENT",
                "GG-SG",
                10,
            ),

            (
                "GG-SG-TEC",
                "Dpto. Técnico",
                "DEPARTMENT",
                "GG-SG",
                20,
            ),

            # ======================================================
            # GERENCIA COMERCIO EXTERIOR
            # ======================================================

            (
                "GG-GCE",
                "Gerencia Comercio Exterior",
                "MANAGEMENT",
                "GG",
                50,
            ),

            (
                "GG-GCE-CON",
                "Unidad Gestión de Contratos",
                "UNIT",
                "GG-GCE",
                10,
            ),

            (
                "GG-GCE-CON-AI",
                "Dpto. Abastecimiento e Inspección",
                "DEPARTMENT",
                "GG-GCE-CON",
                10,
            ),

            (
                "GG-GCE-SUM",
                "Unidad Administración de Suministros",
                "UNIT",
                "GG-GCE",
                20,
            ),

            (
                "GG-GCE-SUM-LP",
                "Dpto. Logística Primaria",
                "DEPARTMENT",
                "GG-GCE-SUM",
                10,
            ),

            (
                "GG-GCE-GC",
                "Unidad de Gestión y Control",
                "UNIT",
                "GG-GCE",
                30,
            ),

            (
                "GG-GCE-GC-GA",
                "Dpto. Gestión Aduanera",
                "DEPARTMENT",
                "GG-GCE-GC",
                10,
            ),

            (
                "GG-GCE-PD",
                "Unidad de Planificación y Desarrollo",
                "UNIT",
                "GG-GCE",
                40,
            ),

            (
                "GG-GCE-PD-TAE",
                "Dpto. Técnico, Administrativo y Estadístico",
                "DEPARTMENT",
                "GG-GCE-PD",
                10,
            ),

            # ======================================================
            # MECIP
            # ======================================================

            (
                "GG-MECIP",
                "Unidad de Gestión y Control MECIP",
                "UNIT",
                "GG",
                60,
            ),

            (
                "GG-MECIP-DI",
                "Dpto. Diagnóstico e Implementación MECIP",
                "DEPARTMENT",
                "GG-MECIP",
                10,
            ),

            (
                "GG-MECIP-SM",
                "Dpto. Seguimiento y Mejoramiento MECIP",
                "DEPARTMENT",
                "GG-MECIP",
                20,
            ),

            # ======================================================
            # DIRECCIÓN OPERATIVA DE CONTRATACIONES
            # ======================================================

            (
                "GG-DOC",
                "Dirección Operativa de Contrataciones",
                "DIRECTORATE",
                "GG",
                70,
            ),

            (
                "GG-DOC-ADJ",
                "Dirección Adjunta",
                "DEPUTY_DIRECTORATE",
                "GG-DOC",
                10,
            ),

            (
                "GG-DOC-ADJ-GCP",
                "Unidad de Gestión y Control de Procesos",
                "UNIT",
                "GG-DOC-ADJ",
                10,
            ),

            (
                "GG-DOC-ADJ-GCP-CONV",
                "Dpto. Convocatorias",
                "DEPARTMENT",
                "GG-DOC-ADJ-GCP",
                10,
            ),

            (
                "GG-DOC-ADJ-PP",
                "Unidad Planificación de Procesos",
                "UNIT",
                "GG-DOC-ADJ",
                20,
            ),

            (
                "GG-DOC-ADJ-PP-PROG",
                "Dpto. Programación",
                "DEPARTMENT",
                "GG-DOC-ADJ-PP",
                10,
            ),

            (
                "GG-DOC-ADJ-VE",
                "Unidad de Verificación de Ejecución",
                "UNIT",
                "GG-DOC-ADJ",
                30,
            ),

            (
                "GG-DOC-ADJ-VE-CG",
                "Dpto. Contratos y Garantías",
                "DEPARTMENT",
                "GG-DOC-ADJ-VE",
                10,
            ),

            # ======================================================
            # DIRECCIÓN FINANCIERA
            # ======================================================

            (
                "GG-DF",
                "Dirección Financiera",
                "DIRECTORATE",
                "GG",
                80,
            ),

            (
                "GG-DF-GP",
                "Unidad de Gestión Patrimonial",
                "UNIT",
                "GG-DF",
                10,
            ),

            (
                "GG-DF-GP-PAT",
                "Dpto. Patrimonio",
                "DEPARTMENT",
                "GG-DF-GP",
                10,
            ),

            (
                "GG-DF-GP-ALM",
                "Dpto. Almacenes",
                "DEPARTMENT",
                "GG-DF-GP",
                20,
            ),

            (
                "GG-DF-GC",
                "Unidad de Gestión Contable",
                "UNIT",
                "GG-DF",
                20,
            ),

            (
                "GG-DF-GC-PRES",
                "Dpto. Presupuesto",
                "DEPARTMENT",
                "GG-DF-GC",
                10,
            ),

            (
                "GG-DF-GC-SICO",
                "Dpto. SICO",
                "DEPARTMENT",
                "GG-DF-GC",
                20,
            ),

            (
                "GG-DF-GC-CC",
                "Dpto. Contabilidad y Costos",
                "DEPARTMENT",
                "GG-DF-GC",
                30,
            ),

            (
                "GG-DF-GC-IMP",
                "Dpto. Dpto. Impuesto",
                "DEPARTMENT",
                "GG-DF-GC",
                40,
            ),

            (
                "GG-DF-GA",
                "Unidad de Gestión Administrativa",
                "UNIT",
                "GG-DF",
                30,
            ),

            (
                "GG-DF-GA-EGR",
                "Dpto. Egresos",
                "DEPARTMENT",
                "GG-DF-GA",
                10,
            ),

            (
                "GG-DF-GA-ING",
                "Dpto. Ingresos",
                "DEPARTMENT",
                "GG-DF-GA",
                20,
            ),

            (
                "GG-DF-GA-CGC",
                "Dpto. Crédito y Gestión de Cobranzas",
                "DEPARTMENT",
                "GG-DF-GA",
                30,
            ),

            # ======================================================
            # DIRECCIÓN COMERCIAL
            # ======================================================

            (
                "GG-DC",
                "Dirección Comercial",
                "DIRECTORATE",
                "GG",
                90,
            ),

            # ------------------------------------------------------
            # SUB-GERENCIA RETAIL
            # ------------------------------------------------------

            (
                "GG-DC-RETAIL",
                "Sub-Gerencia Retail",
                "SUB_MANAGEMENT",
                "GG-DC",
                10,
            ),

            (
                "GG-DC-RETAIL-EO",
                "Unidad EESS de Operadores",
                "UNIT",
                "GG-DC-RETAIL",
                10,
            ),

            (
                "GG-DC-RETAIL-EO-PFO",
                "Dpto. Proyectos y Fiscalización de Obras",
                "DEPARTMENT",
                "GG-DC-RETAIL-EO",
                10,
            ),

            (
                "GG-DC-RETAIL-EO-AEO",
                "Dpto. Administración de EESS con Operadores",
                "DEPARTMENT",
                "GG-DC-RETAIL-EO",
                20,
            ),

            (
                "GG-DC-RETAIL-EO-RCS",
                "Representante Comercial Senior",
                "OTHER",
                "GG-DC-RETAIL-EO",
                30,
            ),

            (
                "GG-DC-RETAIL-EP",
                "Unidad EESS Propias",
                "UNIT",
                "GG-DC-RETAIL",
                20,
            ),

            (
                "GG-DC-RETAIL-EP-ADM",
                "Dpto. Administración de EESS Propias",
                "DEPARTMENT",
                "GG-DC-RETAIL-EP",
                10,
            ),

            (
                "GG-DC-RETAIL-LUB",
                "Unidad Lubricantes",
                "UNIT",
                "GG-DC-RETAIL",
                30,
            ),

            (
                "GG-DC-RETAIL-GLP",
                "Unidad GLP",
                "UNIT",
                "GG-DC-RETAIL",
                40,
            ),

            # ------------------------------------------------------
            # SUB-GERENCIA GRANDES CONSUMIDORES
            # ------------------------------------------------------

            (
                "GG-DC-GC",
                "Sub-Gerencia Grandes Consumidores",
                "SUB_MANAGEMENT",
                "GG-DC",
                20,
            ),

            (
                "GG-DC-GC-CC",
                "Unidad Cuentas Corporativas",
                "UNIT",
                "GG-DC-GC",
                10,
            ),

            (
                "GG-DC-GC-CC-AC",
                "Dpto. Atención al Cliente",
                "DEPARTMENT",
                "GG-DC-GC-CC",
                10,
            ),

            (
                "GG-DC-GC-CC-ADC",
                "Dpto. Administración de Contratos",
                "DEPARTMENT",
                "GG-DC-GC-CC",
                20,
            ),

            (
                "GG-DC-GC-CC-OS",
                "Dpto. Operación de Sistemas",
                "DEPARTMENT",
                "GG-DC-GC-CC",
                30,
            ),

            (
                "GG-DC-GC-BUNKER",
                "Unidad de Bunker",
                "UNIT",
                "GG-DC-GC",
                20,
            ),

            (
                "GG-DC-GC-GCC",
                "Unidad Gestión y Control Comercial",
                "UNIT",
                "GG-DC-GC",
                30,
            ),

            (
                "GG-DC-GC-GCC-CS",
                "Dpto. Contratos y Suministros",
                "DEPARTMENT",
                "GG-DC-GC-GCC",
                10,
            ),

            (
                "GG-DC-GC-GCC-V",
                "Dpto. Ventas",
                "DEPARTMENT",
                "GG-DC-GC-GCC",
                20,
            ),

            (
                "GG-DC-GC-GCC-PSP",
                "Dpto. Provisión Sector Privado y Otros",
                "DEPARTMENT",
                "GG-DC-GC-GCC",
                30,
            ),
        ]

        created_count = 0
        updated_count = 0

        with transaction.atomic():

            units_by_code = {}

            for code, name, unit_type, parent_code, order in structure:

                parent = None

                if parent_code:
                    parent = units_by_code.get(parent_code)

                    if parent is None:
                        try:
                            parent = OrganizationalUnit.objects.get(
                                code=parent_code
                            )
                        except OrganizationalUnit.DoesNotExist as exc:
                            raise RuntimeError(
                                f"No se encontró la dependencia superior "
                                f"{parent_code} para {code}."
                            ) from exc

                unit, created = OrganizationalUnit.objects.update_or_create(
                    code=code,
                    defaults={
                        "name": name,
                        "unit_type": unit_type,
                        "parent": parent,
                        "order": order,
                        "is_active": True,
                    },
                )

                units_by_code[code] = unit

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
                    f"Proceso finalizado. "
                    f"Creadas: {created_count} | "
                    f"Actualizadas: {updated_count} | "
                    f"Total procesadas: {len(structure)}"
                )
            )