import json
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from pywebpush import WebPushException

from apps.notifications.context_processors import notification_context
from apps.notifications.models import Notification, PushSubscription
from apps.notifications.services import (
    create_or_update_notification,
    send_web_push_to_user,
)


User = get_user_model()


class PushSubscriptionViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="push-user",
            email="push-user@example.test",
            password="ClaveSegura123",
        )
        self.other_user = User.objects.create_user(
            username="other-push-user",
            email="other-push-user@example.test",
            password="ClaveSegura123",
        )
        self.url = reverse("notifications:push_subscribe")
        self.payload = {
            "endpoint": "https://push.example.test/subscription-1",
            "keys": {
                "p256dh": "public-key",
                "auth": "auth-secret",
            },
        }

    def post_payload(self, payload):
        return self.client.post(
            self.url,
            data=json.dumps(payload),
            content_type="application/json",
        )

    def test_requires_authentication(self):
        response = self.post_payload(self.payload)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(PushSubscription.objects.count(), 0)

    def test_valid_post_creates_subscription_for_authenticated_user(self):
        self.client.force_login(self.user)

        response = self.post_payload(self.payload)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        subscription = PushSubscription.objects.get()
        self.assertEqual(subscription.user, self.user)
        self.assertEqual(subscription.endpoint, self.payload["endpoint"])
        self.assertEqual(subscription.p256dh, "public-key")
        self.assertEqual(subscription.auth, "auth-secret")
        self.assertTrue(subscription.is_active)

    def test_endpoint_is_required(self):
        self.client.force_login(self.user)
        payload = {**self.payload, "endpoint": ""}

        response = self.post_payload(payload)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(PushSubscription.objects.count(), 0)

    def test_p256dh_is_required(self):
        self.client.force_login(self.user)
        payload = {
            **self.payload,
            "keys": {"p256dh": "", "auth": "auth-secret"},
        }

        response = self.post_payload(payload)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(PushSubscription.objects.count(), 0)

    def test_auth_key_is_required(self):
        self.client.force_login(self.user)
        payload = {
            **self.payload,
            "keys": {"p256dh": "public-key", "auth": ""},
        }

        response = self.post_payload(payload)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(PushSubscription.objects.count(), 0)

    def test_existing_subscription_is_updated_and_associated_to_current_user(self):
        subscription = PushSubscription.objects.create(
            user=self.other_user,
            endpoint=self.payload["endpoint"],
            p256dh="old-public-key",
            auth="old-auth-secret",
            is_active=False,
        )
        self.client.force_login(self.user)

        response = self.post_payload(self.payload)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["created"])
        subscription.refresh_from_db()
        self.assertEqual(subscription.user, self.user)
        self.assertEqual(subscription.p256dh, "public-key")
        self.assertEqual(subscription.auth, "auth-secret")
        self.assertTrue(subscription.is_active)


@override_settings(
    WEBPUSH_VAPID_PUBLIC_KEY="test-public-key",
    WEBPUSH_VAPID_PRIVATE_KEY="test-private-key",
    WEBPUSH_VAPID_SUBJECT="mailto:push-test@example.test",
)
class WebPushServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="webpush-user",
            email="webpush-user@example.test",
            password="ClaveSegura123",
        )

    def create_subscription(self, suffix="1"):
        return PushSubscription.objects.create(
            user=self.user,
            endpoint=f"https://push.example.test/{suffix}",
            p256dh=f"public-key-{suffix}",
            auth=f"auth-secret-{suffix}",
        )

    @patch("apps.notifications.services.webpush")
    def test_successful_send(self, mocked_webpush):
        self.create_subscription()

        result = send_web_push_to_user(
            user=self.user,
            title="Título",
            body="Contenido",
            url="/notificaciones/",
            tag="test-tag",
        )

        self.assertEqual(result, {"sent": 1, "failed": 0, "deactivated": 0})
        mocked_webpush.assert_called_once()
        payload = json.loads(mocked_webpush.call_args.kwargs["data"])
        self.assertEqual(
            payload,
            {
                "title": "Título",
                "body": "Contenido",
                "url": "/notificaciones/",
                "tag": "test-tag",
            },
        )

    @patch("apps.notifications.services.webpush")
    def test_sends_to_multiple_active_devices(self, mocked_webpush):
        self.create_subscription("1")
        self.create_subscription("2")
        PushSubscription.objects.create(
            user=self.user,
            endpoint="https://push.example.test/inactive",
            p256dh="inactive-public-key",
            auth="inactive-auth",
            is_active=False,
        )

        result = send_web_push_to_user(
            user=self.user,
            title="Título",
            body="Contenido",
        )

        self.assertEqual(result["sent"], 2)
        self.assertEqual(mocked_webpush.call_count, 2)

    @patch("apps.notifications.services.webpush")
    def test_http_404_and_410_deactivate_subscriptions(self, mocked_webpush):
        first = self.create_subscription("404")
        second = self.create_subscription("410")
        mocked_webpush.side_effect = [
            WebPushException(
                "Not found",
                response=SimpleNamespace(status_code=404),
            ),
            WebPushException(
                "Gone",
                response=SimpleNamespace(status_code=410),
            ),
        ]

        result = send_web_push_to_user(
            user=self.user,
            title="Título",
            body="Contenido",
        )

        first.refresh_from_db()
        second.refresh_from_db()
        self.assertFalse(first.is_active)
        self.assertFalse(second.is_active)
        self.assertEqual(result, {"sent": 0, "failed": 2, "deactivated": 2})

    @patch("apps.notifications.services.webpush")
    def test_one_device_error_does_not_stop_the_others(self, mocked_webpush):
        self.create_subscription("first")
        self.create_subscription("second")
        mocked_webpush.side_effect = [RuntimeError("transport error"), None]

        result = send_web_push_to_user(
            user=self.user,
            title="Título",
            body="Contenido",
        )

        self.assertEqual(mocked_webpush.call_count, 2)
        self.assertEqual(result, {"sent": 1, "failed": 1, "deactivated": 0})

    @patch("apps.notifications.services.webpush")
    def test_user_without_subscriptions_is_a_noop(self, mocked_webpush):
        result = send_web_push_to_user(
            user=self.user,
            title="Título",
            body="Contenido",
        )

        self.assertEqual(result, {"sent": 0, "failed": 0, "deactivated": 0})
        mocked_webpush.assert_not_called()


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
            role=User.Role.ADMIN,
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

    def test_client_sees_only_own_notifications_without_executive_metrics(self):
        self.client.force_login(self.other_user)

        response = self.client.get(reverse("notifications:notification_list"))

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["show_executive_panel"])
        self.assertNotIn("total_count", response.context)
        self.assertContains(response, self.other_user_notification.title)
        self.assertNotContains(response, self.notification.title)
        self.assertNotContains(response, self.global_notification.title)
        self.assertNotContains(response, "Panel ejecutivo")
        self.assertNotContains(response, "Tipos más frecuentes")

    def test_client_cannot_access_another_users_notification(self):
        self.client.force_login(self.other_user)

        response = self.client.post(
            reverse(
                "notifications:notification_mark_read",
                args=[self.notification.pk],
            )
        )

        self.assertEqual(response.status_code, 404)

    def test_technician_sees_only_own_notifications(self):
        technician = User.objects.create_user(
            username="tecnico_notificaciones",
            email="tecnico_notificaciones@novadesk.local",
            password="ClaveSegura123",
            role=User.Role.TECHNICIAN,
        )
        own_notification = Notification.objects.create(
            recipient=technician,
            title="Trabajo asignado al técnico",
            message="Notificación laboral propia.",
            unique_key="test-technician-own-notification",
        )
        self.client.force_login(technician)

        response = self.client.get(reverse("notifications:notification_list"))

        self.assertFalse(response.context["show_executive_panel"])
        self.assertContains(response, own_notification.title)
        self.assertNotContains(response, self.notification.title)
        self.assertNotContains(response, self.global_notification.title)

    def test_admin_and_supervisor_keep_executive_panel(self):
        for role in (User.Role.ADMIN, User.Role.SUPERVISOR):
            with self.subTest(role=role):
                user = User.objects.create_user(
                    username=f"executive_{role.lower()}",
                    email=f"executive_{role.lower()}@novadesk.local",
                    password="ClaveSegura123",
                    role=role,
                )
                self.client.force_login(user)

                response = self.client.get(
                    reverse("notifications:notification_list")
                )

                self.assertTrue(response.context["show_executive_panel"])
                self.assertIn("total_count", response.context)
                self.assertContains(response, "Panel ejecutivo")
                self.assertContains(response, "Tipos más frecuentes")


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
            1,
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
