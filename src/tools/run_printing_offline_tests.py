"""Isolated test runner: no .env, real DBs, migrations or network connections."""
import ast
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def guard(event, args):
    if event == "sqlite3.connect":
        name = str(args[0])
        if name != ":memory:" and not (name.startswith("file:memorydb_") and "mode=memory" in name):
            raise RuntimeError("REAL_DATABASE_FORBIDDEN_IN_OFFLINE_TESTS")
    if event in ("socket.connect", "socket.connect_ex", "socket.getaddrinfo", "socket.sendto"):
        raise RuntimeError("NETWORK_FORBIDDEN_IN_OFFLINE_TESTS")


def main():
    sys.addaudithook(guard)
    os.environ.pop("DJANGO_SETTINGS_MODULE", None)
    # Read the list as data; never import application settings or consume .env.
    tree = ast.parse((ROOT / "config/settings.py").read_text(encoding="utf-8-sig"))
    installed = next(ast.literal_eval(n.value) for n in tree.body
        if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "INSTALLED_APPS" for t in n.targets))
    from django.conf import settings
    settings.configure(SECRET_KEY="synthetic-offline-tests-only", DEBUG=False,
        BASE_DIR=ROOT, INSTALLED_APPS=installed,
        DATABASES={"default":{"ENGINE":"django.db.backends.sqlite3","NAME":":memory:","TEST":{"NAME":":memory:"}}},
        AUTH_USER_MODEL="accounts.User", USE_TZ=True, TIME_ZONE="UTC",
        AUTHENTICATION_BACKENDS=["apps.accounts.backends.ApprovedUserModelBackend"],
        PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
        ROOT_URLCONF="config.urls", ALLOWED_HOSTS=["testserver"],
        MIDDLEWARE=["django.contrib.sessions.middleware.SessionMiddleware",
                    "django.contrib.auth.middleware.AuthenticationMiddleware",
                    "django.contrib.messages.middleware.MessageMiddleware"],
        TEMPLATES=[{"BACKEND":"django.template.backends.django.DjangoTemplates",
            "DIRS":[ROOT/"templates"],"APP_DIRS":True,"OPTIONS":{"context_processors":[
                "django.template.context_processors.request","django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages"]}}],
        STORAGES={"default":{"BACKEND":"django.core.files.storage.InMemoryStorage"},
                  "staticfiles":{"BACKEND":"django.contrib.staticfiles.storage.StaticFilesStorage"}},
        STATIC_URL="/static/", MEDIA_URL="/media/", LOGIN_URL="/accounts/login/",
        PRINTING_MONITOR_TIMEOUT_SECONDS=0.1, PRINTING_MONITOR_MAX_AGE_SECONDS=900,
        PRINTING_IDENTITY_TIMEOUT_SECONDS=1,
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        DEFAULT_AUTO_FIELD="django.db.models.BigAutoField")
    import django
    django.setup()
    from django.apps import apps
    # Only synchronize synthetic in-memory tables; no migration modules are executed.
    settings.MIGRATION_MODULES = {app.label:None for app in apps.get_app_configs()}
    from django.test.runner import DiscoverRunner
    labels = sys.argv[1:]
    if not labels:
        raise SystemExit("Explicit tracked test labels are required; no batch tests selected by default.")
    return bool(DiscoverRunner(verbosity=1, interactive=False).run_tests(labels))


if __name__ == "__main__":
    sys.exit(main())
