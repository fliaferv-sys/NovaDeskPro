from django.core.management.base import BaseCommand

from apps.notifications.generators import (
    generate_consumable_stock_notifications,
    generate_device_offline_notifications,
    generate_printing_contract_notifications,
    generate_ticket_sla_notifications,
)


class Command(BaseCommand):
    help = "Genera y actualiza las notificaciones automáticas de NovaDesk."

    def handle(self, *args, **options):
        self.stdout.write(
            self.style.NOTICE(
                "Generando notificaciones automáticas..."
            )
        )

        device_result = generate_device_offline_notifications()
        stock_result = generate_consumable_stock_notifications()
        contract_result = generate_printing_contract_notifications()
        sla_result = generate_ticket_sla_notifications()

        self.stdout.write("")
        self.stdout.write("Equipos fuera de línea:")
        self.stdout.write(
            f"  Creadas: {device_result['created']}"
        )
        self.stdout.write(
            f"  Actualizadas: {device_result['updated']}"
        )
        self.stdout.write(
            f"  Desactivadas: {device_result['deactivated']}"
        )

        self.stdout.write("")
        self.stdout.write("Stock de consumibles:")
        self.stdout.write(
            f"  Creadas: {stock_result['created']}"
        )
        self.stdout.write(
            f"  Actualizadas: {stock_result['updated']}"
        )
        self.stdout.write(
            f"  Desactivadas: {stock_result['deactivated']}"
        )

        self.stdout.write("")
        self.stdout.write("Contratos de impresión:")
        self.stdout.write(
            f"  Creadas: {contract_result['created']}"
        )
        self.stdout.write(
            f"  Actualizadas: {contract_result['updated']}"
        )
        self.stdout.write(
            f"  Desactivadas: {contract_result['deactivated']}"
        )

        total_created = (
            device_result["created"]
            + stock_result["created"]
            + contract_result["created"]
            + sla_result["created"]
        )

        total_updated = (
            device_result["updated"]
            + stock_result["updated"]
            + contract_result["updated"]
            + sla_result["updated"]
        )

        total_deactivated = (
            device_result["deactivated"]
            + stock_result["deactivated"]
            + contract_result["deactivated"]
            + sla_result["deactivated"]
        )

        self.stdout.write("")
        self.stdout.write("Resumen general:")
        self.stdout.write(
            f"  Total creadas: {total_created}"
        )
        self.stdout.write(
            f"  Total actualizadas: {total_updated}"
        )
        self.stdout.write(
            f"  Total desactivadas: {total_deactivated}"
        )

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                "Generación de notificaciones completada."
            )
        )
