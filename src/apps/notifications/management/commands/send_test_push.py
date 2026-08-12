from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from apps.notifications.services import send_web_push_to_user


class Command(BaseCommand):
    help = "Envía un Web Push de prueba a las suscripciones activas de un usuario."

    def add_arguments(self, parser):
        parser.add_argument("username")

    def handle(self, *args, **options):
        User = get_user_model()
        username = options["username"]

        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist as error:
            raise CommandError("No existe un usuario con ese username.") from error

        result = send_web_push_to_user(
            user=user,
            title="Prueba de NovaDesk Pro",
            body="Las notificaciones Web Push están funcionando.",
            url="/notificaciones/",
            tag="novadesk-test-push",
        )

        if result["sent"]:
            self.stdout.write(
                self.style.SUCCESS(
                    "Push de prueba procesado: "
                    f"enviados={result['sent']}, "
                    f"fallidos={result['failed']}, "
                    f"desactivados={result['deactivated']}."
                )
            )
        else:
            self.stdout.write(
                self.style.WARNING(
                    "No se envió ningún Push: "
                    f"fallidos={result['failed']}, "
                    f"desactivados={result['deactivated']}."
                )
            )
