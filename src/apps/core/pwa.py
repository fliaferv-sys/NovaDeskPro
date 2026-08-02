from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.cache import never_cache


@never_cache
def web_app_manifest(request):
    return JsonResponse(
        {
            "name": "NovaDesk Pro",
            "short_name": "NovaDesk",
            "description": "Gestión institucional de soporte y activos TI",
            "id": "/",
            "start_url": "/",
            "scope": "/",
            "display": "standalone",
            "background_color": "#f4f6f9",
            "theme_color": "#0a1a3a",
            "lang": "es-PY",
            "icons": [
                {
                    "src": "/static/icons/novadesk-pwa.svg",
                    "sizes": "any",
                    "type": "image/svg+xml",
                    "purpose": "any maskable",
                }
            ],
        }
    )


@never_cache
def service_worker(request):
    response = render(
        request,
        "pwa/service-worker.js",
        content_type="application/javascript",
    )
    response["Service-Worker-Allowed"] = "/"
    return response
