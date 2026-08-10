(function () {
    "use strict";

    console.log("[PWA] script cargado");

    let installPrompt = null;
    const installButton = document.getElementById("pwaInstallButton");
    const pushNotificationButton =
        document.getElementById("pushNotificationButton");

    console.log(
        pushNotificationButton
            ? "[PWA] botón encontrado"
            : "[PWA] botón push no encontrado"
    );

    function urlBase64ToUint8Array(base64String) {
        const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
        const base64 = (base64String + padding)
            .replace(/-/g, "+")
            .replace(/_/g, "/");

        const rawData = window.atob(base64);

        return Uint8Array.from(
            [...rawData].map((char) => char.charCodeAt(0))
        );
    }

    function getCookie(name) {
        const cookies = document.cookie ? document.cookie.split(";") : [];

        for (const cookie of cookies) {
            const trimmed = cookie.trim();

            if (trimmed.startsWith(name + "=")) {
                return decodeURIComponent(
                    trimmed.substring(name.length + 1)
                );
            }
        }

        return "";
    }

    async function savePushSubscription(subscription) {
        console.log("[PWA] enviando suscripción");

        const response = await fetch(
            "/notificaciones/push/suscribir/",
            {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "X-CSRFToken": getCookie("csrftoken"),
                },
                credentials: "same-origin",
                body: JSON.stringify(subscription.toJSON()),
            }
        );

        console.log(`[PWA] backend respondió ${response.status}`);

        if (!response.ok) {
            throw new Error(
                "No se pudo guardar la suscripción Push."
            );
        }

        return response.json();
    }

    async function subscribeToPush() {
        if (
            !("serviceWorker" in navigator) ||
            !("PushManager" in window) ||
            !("Notification" in window)
        ) {
            throw new Error(
                "Este navegador no admite notificaciones Push."
            );
        }

        const vapidPublicKey =
            window.NovaDeskPWA?.vapidPublicKey || "";

        if (!vapidPublicKey) {
            throw new Error(
                "La clave pública VAPID no está configurada."
            );
        }

        let permission = Notification.permission;

        console.log(`[PWA] permiso actual: ${permission}`);

        if (permission === "default") {
            permission = await Notification.requestPermission();
            console.log(`[PWA] permiso solicitado: ${permission}`);
        }

        if (permission !== "granted") {
            throw new Error(
                "El permiso de notificaciones no fue concedido."
            );
        }

        const registration =
            await navigator.serviceWorker.ready;

        console.log("[PWA] service worker listo");

        let subscription =
            await registration.pushManager.getSubscription();

        if (!subscription) {
            subscription =
                await registration.pushManager.subscribe({
                    userVisibleOnly: true,
                    applicationServerKey:
                        urlBase64ToUint8Array(vapidPublicKey),
                });
            console.log("[PWA] suscripción creada");
        } else {
            console.log("[PWA] suscripción encontrada");
        }

        await savePushSubscription(subscription);

        return subscription;
    }

    window.NovaDeskPWA = {
        ...(window.NovaDeskPWA || {}),
        subscribeToPush,
    };

    if (pushNotificationButton) {
        pushNotificationButton.addEventListener(
            "click",
            async function () {
                console.log("[PWA] clic activar notificaciones");
                pushNotificationButton.disabled = true;

                try {
                    await subscribeToPush();

                    pushNotificationButton.title =
                        "Notificaciones activadas";

                    pushNotificationButton.setAttribute(
                        "aria-label",
                        "Notificaciones activadas"
                    );

                    pushNotificationButton.innerHTML =
                        '<i class="bi bi-bell-fill"></i>';
                } catch (error) {
                    console.error(
                        "[PWA] no se pudieron activar las notificaciones:",
                        error
                    );

                    alert(
                        error.message ||
                        "No se pudieron activar las notificaciones."
                    );
                } finally {
                    pushNotificationButton.disabled = false;
                }
            }
        );
    }
    if ("serviceWorker" in navigator) {
        window.addEventListener("load", function () {
            navigator.serviceWorker
                .register("/service-worker.js")
                .catch(function (error) {
                    console.error(
                        "No se pudo registrar el Service Worker:",
                        error
                    );
                });
        });
    }

    window.addEventListener(
        "beforeinstallprompt",
        function (event) {
            event.preventDefault();
            installPrompt = event;

            if (installButton) {
                installButton.hidden = false;
            }
        }
    );

    if (installButton) {
        installButton.addEventListener(
            "click",
            async function () {
                if (!installPrompt) {
                    return;
                }

                installPrompt.prompt();
                await installPrompt.userChoice;

                installPrompt = null;
                installButton.hidden = true;
            }
        );
    }

    window.addEventListener(
        "appinstalled",
        function () {
            installPrompt = null;

            if (installButton) {
                installButton.hidden = true;
            }
        }
    );
})();
