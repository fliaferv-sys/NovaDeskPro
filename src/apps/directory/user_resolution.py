"""Read-only batched sources replayed through the individual account matcher."""
from django.conf import settings

from .ad_services import search_ad_users_batch
from .services import DirectoryDatabaseError, search_directory_employees_batch


class _NeedsAD(Exception):
    pass


class UserResolutionSources:
    def __init__(self):
        self.rrhh = {}
        self.ad = {}

    def load_rrhh(self, terms):
        terms = list(dict.fromkeys(terms))
        if not terms:
            return
        try:
            self.rrhh.update(search_directory_employees_batch(terms))
        except DirectoryDatabaseError as exc:
            self.rrhh.update({term: exc for term in terms})

    @staticmethod
    def _read(results, value, field):
        result = results.get((str(value).strip(), field))
        if result is None:
            raise ValueError("La fuente batch no cubre esta evidencia.")
        if isinstance(result, Exception):
            raise result
        return result

    def search_rrhh(self, value, *, search_field, **kwargs):
        return self._read(self.rrhh, value, search_field)

    def search_ad(self, value, *, search_field, **kwargs):
        return self._read(self.ad, value, search_field)

    @classmethod
    def load(cls, users):
        from apps.accounts.institutional_sync import resolve_sync_identity
        sources = cls()
        terms = []
        for user in users:
            for value, field in ((user.id_personal, "rrhh_id"), (user.employee_number, "employee_number")):
                if value is not None and str(value).strip():
                    terms.append((str(value).strip(), field))
            email = (user.email or "").strip().casefold()
            if ("@" in email and email.rsplit("@", 1)[1] == settings.DIRECTORY_AD_DOMAIN.casefold()
                    and user.username.strip().casefold() == email.split("@", 1)[0]):
                terms.append((email, "email"))
        sources.load_rrhh(terms)
        bridges = []
        def needs_ad(*args, **kwargs):
            raise _NeedsAD
        for user in users:
            try:
                resolve_sync_identity(user, rrhh_search=sources.search_rrhh, ad_search=needs_ad)
            except _NeedsAD:
                bridges.append(user)
            except Exception:
                # Replayed again by the central resolver, which falls back locally.
                pass
        if bridges:
            ad_terms = [(value.strip().casefold(), field) for user in bridges
                        for value, field in ((user.email, "email"), (user.username, "username"))]
            sources.ad = search_ad_users_batch(ad_terms)
            names = []
            for user in bridges:
                rows = sources.ad.get((user.email.strip().casefold(), "email"))
                if isinstance(rows, list) and len(rows) == 1 and rows[0].get("name") and user.phone:
                    names.append((str(rows[0]["name"]).strip(), "name"))
            sources.load_rrhh(names)
        return sources
