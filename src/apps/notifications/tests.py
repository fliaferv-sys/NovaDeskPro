from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone

from apps.notifications.context_processors import notification_context
from apps.notifications.models import Notification
from apps.notifications.services import create_or_update_notification


User = get_user_model()


class NotificationModelTests(TestCase):
    """
    Pruebas del modelo Notification.
    """

    def setUp(self):
        self.user = User.objects.create_user(
            username="usuario_prueba",
            email="usuario_prueba@novadesk.local",
            password="ClaveSegura123",
            first_name="Usuario",
            last_name="Prueba",
        )

    def test_create_notification(self):
        """
        Comprueba que se pueda crear correctamente una notificación.
        """

        notification = Notification.objects.create(
            recipient=self.user,
            notification_type=Notification.TYPE_GENERAL,
            level=Notification.LEVEL_INFO,
            title="Notificación de prueba",
            message="Mensaje de prueba.",
            unique_key="test-create-notification",
        )

        self.assertEqual(Notification.objects.count(), 1)
        self.assertEqual(notification.title, "Notificación de prueba")
        self.assertFalse(notification.is_read)
        self.assertTrue(notification.is_active)

    def test_mark_notification_as_read(self):
        """
        Comprueba que una notificación se pueda marcar como leída.
        """

        notification = Notification.objects.create(
            recipient=self.user,
            notification_type=Notification.TYPE_GENERAL,
            level=Notification.LEVEL_INFO,
            title="Notificación pendiente",
            message="Esta notificación todavía no fue leída.",
            unique_key="test-mark-read",
        )

        notification.mark_as_read()
        notification.refresh_from_db()

        self.assertTrue(notification.is_read)
        self.assertIsNotNone(notification.read_at)

    def test_mark_notification_as_unread(self):
        """
        Comprueba que una notificación pueda volver a quedar pendiente.
        """

        notification = Notification.objects.create(
            recipient=self.user,
            notification_type=Notification.TYPE_GENERAL,
            level=Notification.LEVEL_INFO,
            title="Notificación leída",
            message="Esta notificación será marcada como no leída.",
            unique_key="test-mark-unread",
            is_read=True,
            read_at=timezone.now(),
        )

        notification.mark_as_unread()
        notification.refresh_from_db()

        self.assertFalse(notification.is_read)
        self.assertIsNone(notification.read_at)

    def test_resolve_method_stores_traceability(self):
        """
        Comprueba que resolve() guarde trazabilidad.
        """

        notification = Notification.objects.create(
            recipient=self.user,
            notification_type=Notification.TYPE_GENERAL,
            level=Notification.LEVEL_WARNING,
            title="Notificación a resolver",
            message="Prueba de resolución.",
            unique_key="test-resolve-traceability",
        )

        notification.resolve(user=self.user)
        notification.refresh_from_db()

        self.assertFalse(notification.is_active)
        self.assertTrue(notification.is_read)
        self.assertEqual(notification.resolved_by, self.user)
        self.assertIsNotNone(notification.resolved_at)

    def test_reopen_method_stores_traceability(self):
        """
        Comprueba que reopen() guarde trazabilidad.
        """

        notification = Notification.objects.create(
            recipient=self.user,
            notification_type=Notification.TYPE_GENERAL,
            level=Notification.LEVEL_WARNING,
            title="Notificación a reabrir",
            message="Prueba de reapertura.",
            unique_key="test-reopen-traceability",
            is_active=False,
            is_read=True,
            read_at=timezone.now(),
        )

        notification.reopen(user=self.user)
        notification.refresh_from_db()

        self.assertTrue(notification.is_active)
        self.assertFalse(notification.is_read)
        self.assertIsNone(notification.read_at)
        self.assertEqual(notification.reopened_by, self.user)
        self.assertIsNotNone(notification.reopened_at)


class NotificationServiceTests(TestCase):
    """
    Pruebas del servicio que crea o actualiza notificaciones.
    """

    def test_service_does_not_create_duplicates(self):
        """
        Comprueba que una misma unique_key no produzca duplicados.
        """

        notification_1, created_1 = create_or_update_notification(
            notification_type=Notification.TYPE_GENERAL,
            level=Notification.LEVEL_WARNING,
            title="Primera versión",
            message="Mensaje inicial.",
            link="/dashboard/",
            object_type="TestObject",
            object_id="1",
            unique_key="test-no-duplicates",
        )

        notification_2, created_2 = create_or_update_notification(
            notification_type=Notification.TYPE_GENERAL,
            level=Notification.LEVEL_DANGER,
            title="Versión actualizada",
            message="Mensaje actualizado.",
            link="/notificaciones/",
            object_type="TestObject",
            object_id="1",
            unique_key="test-no-duplicates",
        )

        self.assertTrue(created_1)
        self.assertFalse(created_2)
        self.assertEqual(Notification.objects.count(), 1)
        self.assertEqual(notification_1.pk, notification_2.pk)

        notification_2.refresh_from_db()

        self.assertEqual(notification_2.title, "Versión actualizada")
        self.assertEqual(notification_2.level, Notification.LEVEL_DANGER)
        self.assertEqual(notification_2.link, "/notificaciones/")


class NotificationViewTests(TestCase):
    """
    Pruebas de las vistas de notificaciones.
    """

    def setUp(self):
        self.user = User.objects.create_user(
            username="usuario_vistas",
            email="usuario_vistas@novadesk.local",
            password="ClaveSegura123",
            first_name="Usuario",
            last_name="Vistas",
        )

        self.other_user = User.objects.create_user(
            username="otro_usuario",
            email="otro_usuario@novadesk.local",
            password="ClaveSegura123",
            first_name="Otro",
            last_name="Usuario",
        )

        self.notification = Notification.objects.create(
            recipient=self.user,
            notification_type=Notification.TYPE_GENERAL,
            level=Notification.LEVEL_INFO,
            title="Notificación para vistas",
            message="Prueba de visualización.",
            unique_key="test-view-notification",
        )

        self.global_notification = Notification.objects.create(
            recipient=None,
            notification_type=Notification.TYPE_GENERAL,
            level=Notification.LEVEL_WARNING,
            title="Notificación global",
            message="Visible para todos.",
            unique_key="test-global-view-notification",
        )

        self.other_user_notification = Notification.objects.create(
            recipient=self.other_user,
            notification_type=Notification.TYPE_GENERAL,
            level=Notification.LEVEL_DANGER,
            title="Notificación privada ajena",
            message="No debe ser visible para otro usuario.",
            unique_key="test-other-user-notification",
        )

    def test_notification_list_requires_login(self):
        """
        Un usuario no autenticado debe ser enviado al inicio de sesión.
        """

        response = self.client.get(
            reverse("notifications:notification_list")
        )

        self.assertEqual(response.status_code, 302)

    def test_authenticated_user_can_open_notification_list(self):
        """
        Un usuario autenticado puede abrir la lista.
        """

        self.client.force_login(self.user)

        response = self.client.get(
            reverse("notifications:notification_list")
        )

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(
            response,
            "notifications/notification_list.html",
        )
        self.assertContains(response, "Notificación para vistas")

    def test_user_sees_own_and_global_notifications_only(self):
        """
        El usuario debe ver sus notificaciones y las globales,
        pero no las privadas de otros usuarios.
        """

        self.client.force_login(self.user)

        response = self.client.get(
            reverse("notifications:notification_list")
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Notificación para vistas")
        self.assertContains(response, "Notificación global")
        self.assertNotContains(response, "Notificación privada ajena")

    def test_mark_single_notification_as_read(self):
        """
        Comprueba el marcado individual como leído.
        """

        self.client.force_login(self.user)

        response = self.client.post(
            reverse(
                "notifications:notification_mark_read",
                args=[self.notification.pk],
            )
        )

        self.notification.refresh_from_db()

        self.assertEqual(response.status_code, 302)
        self.assertTrue(self.notification.is_read)
        self.assertIsNotNone(self.notification.read_at)

    def test_mark_all_notifications_as_read(self):
        """
        Comprueba que todas las notificaciones visibles activas
        se puedan marcar como leídas.
        """

        Notification.objects.create(
            recipient=self.user,
            notification_type=Notification.TYPE_GENERAL,
            level=Notification.LEVEL_WARNING,
            title="Segunda notificación",
            message="Segunda prueba.",
            unique_key="test-second-notification",
        )

        self.client.force_login(self.user)

        response = self.client.post(
            reverse("notifications:notification_mark_all_read")
        )

        unread_count_user_scope = Notification.objects.filter(
            pk__in=[
                self.notification.pk,
                self.global_notification.pk,
            ],
            is_active=True,
            is_read=False,
        ).count()

        self.other_user_notification.refresh_from_db()

        self.assertEqual(response.status_code, 302)
        self.assertEqual(unread_count_user_scope, 0)
        self.assertFalse(self.other_user_notification.is_read)

    def test_resolve_notification(self):
        """
        Comprueba que una notificación pueda resolverse manualmente
        y guardar trazabilidad.
        """

        self.client.force_login(self.user)

        response = self.client.post(
            reverse(
                "notifications:notification_resolve",
                args=[self.notification.pk],
            )
        )

        self.notification.refresh_from_db()

        self.assertEqual(response.status_code, 302)
        self.assertFalse(self.notification.is_active)
        self.assertTrue(self.notification.is_read)
        self.assertEqual(self.notification.resolved_by, self.user)
        self.assertIsNotNone(self.notification.resolved_at)

    def test_reopen_notification(self):
        """
        Comprueba que una notificación resuelta pueda reabrirse
        y guardar trazabilidad.
        """

        self.notification.resolve(user=self.user)

        self.client.force_login(self.user)

        response = self.client.post(
            reverse(
                "notifications:notification_reopen",
                args=[self.notification.pk],
            )
        )

        self.notification.refresh_from_db()

        self.assertEqual(response.status_code, 302)
        self.assertTrue(self.notification.is_active)
        self.assertFalse(self.notification.is_read)
        self.assertIsNone(self.notification.read_at)
        self.assertEqual(self.notification.reopened_by, self.user)
        self.assertIsNotNone(self.notification.reopened_at)

    def test_user_cannot_mark_other_user_notification_as_read(self):
        """
        Un usuario no debe poder operar sobre notificaciones ajenas.
        """

        self.client.force_login(self.user)

        response = self.client.post(
            reverse(
                "notifications:notification_mark_read",
                args=[self.other_user_notification.pk],
            )
        )

        self.other_user_notification.refresh_from_db()

        self.assertEqual(response.status_code, 404)
        self.assertFalse(self.other_user_notification.is_read)

    def test_user_cannot_resolve_other_user_notification(self):
        """
        Un usuario no debe poder resolver notificaciones ajenas.
        """

        self.client.force_login(self.user)

        response = self.client.post(
            reverse(
                "notifications:notification_resolve",
                args=[self.other_user_notification.pk],
            )
        )

        self.other_user_notification.refresh_from_db()

        self.assertEqual(response.status_code, 404)
        self.assertTrue(self.other_user_notification.is_active)

    def test_dashboard_metrics_are_visible_in_context(self):
        """
        Comprueba que los nuevos indicadores del dashboard
        estén presentes en el contexto.
        """

        yesterday = timezone.now() - timezone.timedelta(days=1)

        resolved_today = Notification.objects.create(
            recipient=self.user,
            notification_type=Notification.TYPE_DEVICE_OFFLINE,
            level=Notification.LEVEL_DANGER,
            title="Resuelta hoy",
            message="Prueba resuelta hoy.",
            unique_key="test-resolved-today",
            is_active=False,
            is_read=True,
            resolved_by=self.user,
            resolved_at=timezone.now(),
        )

        reopened_today = Notification.objects.create(
            recipient=self.user,
            notification_type=Notification.TYPE_LOW_STOCK,
            level=Notification.LEVEL_WARNING,
            title="Reabierta hoy",
            message="Prueba reabierta hoy.",
            unique_key="test-reopened-today",
            reopened_by=self.user,
            reopened_at=timezone.now(),
        )

        Notification.objects.create(
            recipient=self.user,
            notification_type=Notification.TYPE_CONTRACT_EXPIRING,
            level=Notification.LEVEL_WARNING,
            title="Reabierta antes",
            message="Prueba reabierta antes.",
            unique_key="test-reopened-before",
            reopened_by=self.user,
            reopened_at=yesterday,
        )

        self.client.force_login(self.user)

        response = self.client.get(
            reverse("notifications:notification_list")
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("resolved_today_count", response.context)
        self.assertIn("reopened_total_count", response.context)
        self.assertIn("reopened_today_count", response.context)
        self.assertIn("type_summary", response.context)
        self.assertIn("level_summary", response.context)

        self.assertGreaterEqual(
            response.context["resolved_today_count"],
            1,
        )
        self.assertGreaterEqual(
            response.context["reopened_total_count"],
            2,
        )
        self.assertGreaterEqual(
            response.context["reopened_today_count"],
            1,
        )

    def test_type_and_level_summary_include_expected_values(self):
        """
        Comprueba que los resúmenes por tipo y nivel
        incluyan datos esperados.
        """

        Notification.objects.create(
            recipient=self.user,
            notification_type=Notification.TYPE_DEVICE_OFFLINE,
            level=Notification.LEVEL_DANGER,
            title="Tipo dispositivo",
            message="Resumen por tipo.",
            unique_key="test-type-device-offline",
        )

        Notification.objects.create(
            recipient=self.user,
            notification_type=Notification.TYPE_DEVICE_OFFLINE,
            level=Notification.LEVEL_DANGER,
            title="Tipo dispositivo 2",
            message="Resumen por tipo 2.",
            unique_key="test-type-device-offline-2",
        )

        Notification.objects.create(
            recipient=self.user,
            notification_type=Notification.TYPE_LOW_STOCK,
            level=Notification.LEVEL_WARNING,
            title="Tipo stock",
            message="Resumen por tipo 3.",
            unique_key="test-type-low-stock",
        )

        self.client.force_login(self.user)

        response = self.client.get(
            reverse("notifications:notification_list")
        )

        self.assertEqual(response.status_code, 200)

        type_labels = [item["label"] for item in response.context["type_summary"]]
        level_labels = [item["label"] for item in response.context["level_summary"]]

        self.assertIn("Equipo fuera de línea", type_labels)
        self.assertIn("Consumible con stock bajo", type_labels)
        self.assertIn("Crítica", level_labels)
        self.assertIn("Advertencia", level_labels)


class NotificationContextProcessorTests(TestCase):
    """
    Pruebas del contador que se muestra en la campana.
    """

    def setUp(self):
        self.factory = RequestFactory()

        self.user = User.objects.create_user(
            username="usuario_contador",
            email="usuario_contador@novadesk.local",
            password="ClaveSegura123",
            first_name="Usuario",
            last_name="Contador",
        )

    def test_unread_notification_counter(self):
        """
        Comprueba que la campana cuente notificaciones
        privadas y generales pendientes.
        """

        Notification.objects.create(
            recipient=self.user,
            notification_type=Notification.TYPE_GENERAL,
            level=Notification.LEVEL_INFO,
            title="Notificación privada",
            message="Notificación dirigida al usuario.",
            unique_key="test-private-counter",
        )

        Notification.objects.create(
            recipient=None,
            notification_type=Notification.TYPE_GENERAL,
            level=Notification.LEVEL_WARNING,
            title="Notificación general",
            message="Notificación visible para todos.",
            unique_key="test-global-counter",
        )

        Notification.objects.create(
            recipient=self.user,
            notification_type=Notification.TYPE_GENERAL,
            level=Notification.LEVEL_SUCCESS,
            title="Notificación ya leída",
            message="Esta no debe contarse.",
            unique_key="test-read-counter",
            is_read=True,
            read_at=timezone.now(),
        )

        request = self.factory.get("/dashboard/")
        request.user = self.user

        context = notification_context(request)

        self.assertEqual(
            context["navbar_unread_notifications"],
            2,
        )

    def test_anonymous_user_counter_is_zero(self):
        """
        Un usuario anónimo no debe recibir un contador.
        """

        request = self.factory.get("/")
        request.user = AnonymousUser()

        context = notification_context(request)

        self.assertEqual(
            context["navbar_unread_notifications"],
            0,
        )