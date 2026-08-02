const CACHE_NAME = "novadesk-shell-v1";
const STATIC_ASSETS = [
    "/static/icons/novadesk-pwa.svg"
];

self.addEventListener("install", (event) => {
    event.waitUntil(
        caches.open(CACHE_NAME).then((cache) => cache.addAll(STATIC_ASSETS))
    );
    self.skipWaiting();
});

self.addEventListener("activate", (event) => {
    event.waitUntil(
        caches.keys().then((keys) => Promise.all(
            keys
                .filter((key) => key !== CACHE_NAME)
                .map((key) => caches.delete(key))
        ))
    );
    self.clients.claim();
});

// Las páginas autenticadas siempre se solicitan a Django para evitar mostrar
// información desactualizada o perteneciente a otra sesión del dispositivo.
self.addEventListener("fetch", (event) => {
    if (event.request.method !== "GET") {
        return;
    }

    const requestUrl = new URL(event.request.url);
    if (requestUrl.origin !== self.location.origin) {
        return;
    }

    if (requestUrl.pathname.startsWith("/static/")) {
        event.respondWith(
            caches.match(event.request).then(
                (cached) => cached || fetch(event.request)
            )
        );
    }
});

self.addEventListener("push", (event) => {
    let payload = {};
    try {
        payload = event.data ? event.data.json() : {};
    } catch (error) {
        payload = { body: event.data ? event.data.text() : "" };
    }

    event.waitUntil(
        self.registration.showNotification(
            payload.title || "NovaDesk Pro",
            {
                body: payload.body || "Tiene una nueva notificación.",
                icon: "/static/icons/novadesk-pwa.svg",
                badge: "/static/icons/novadesk-pwa.svg",
                data: { url: payload.url || "/notificaciones/" },
                tag: payload.tag || undefined,
            }
        )
    );
});

self.addEventListener("notificationclick", (event) => {
    event.notification.close();
    const targetUrl = event.notification.data?.url || "/notificaciones/";

    event.waitUntil(
        self.clients.matchAll({ type: "window", includeUncontrolled: true })
            .then((windows) => {
                const existingWindow = windows.find(
                    (windowClient) => new URL(windowClient.url).pathname === targetUrl
                );
                if (existingWindow) {
                    return existingWindow.focus();
                }
                return self.clients.openWindow(targetUrl);
            })
    );
});
