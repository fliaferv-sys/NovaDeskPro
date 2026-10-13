"""GET-only GLPI 9.5 REST client. Tokens live only in memory."""
import base64
from dataclasses import dataclass, field
import math
import os
import re
from urllib.parse import urlsplit

import requests


class GLPIError(Exception):
    """Safe error messages, never upstream bodies/URLs/credentials."""


@dataclass
class GLPIConfig:
    url: str
    app_token: str = field(repr=False)
    username: str = field(repr=False)
    password: str = field(repr=False)
    timeout: float = 15
    verify_tls: bool = True
    page_size: int = 100

    @classmethod
    def from_env(cls):
        values = {}
        for key in ("GLPI_API_URL", "GLPI_APP_TOKEN", "GLPI_USERNAME", "GLPI_PASSWORD"):
            value = os.environ.get(key, "")
            if not value.strip():
                raise GLPIError(f"Falta variable de entorno {key}")
            values[key] = value
        url = values["GLPI_API_URL"].strip().rstrip("/")
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise GLPIError("GLPI_API_URL debe ser una URL HTTP/HTTPS sin credenciales, query ni fragmento.")
        try:
            timeout = float(os.environ.get("GLPI_TIMEOUT", "15"))
            page_size = int(os.environ.get("GLPI_PAGE_SIZE", "100"))
            if not math.isfinite(timeout) or not 0 < timeout <= 300 or not 1 <= page_size <= 1000:
                raise ValueError
        except ValueError:
            raise GLPIError("GLPI_TIMEOUT o GLPI_PAGE_SIZE invalido.") from None
        tls = os.environ.get("GLPI_VERIFY_TLS", "true").casefold()
        if tls not in {"true", "false", "1", "0"}:
            raise GLPIError("GLPI_VERIFY_TLS debe ser true/false o 1/0.")
        return cls(url, values["GLPI_APP_TOKEN"], values["GLPI_USERNAME"], values["GLPI_PASSWORD"], timeout, tls in {"true", "1"}, page_size)


class GLPIClient:
    ALLOWED = re.compile(r"^(?:initSession|killSession|Printer|Computer|User|Location|NetworkPort|NetworkName|IPAddress|User/[0-9]+/UserEmail|(?:Printer|Computer|User|Location|NetworkPort|NetworkName|State)/[1-9][0-9]*)$")

    def __init__(self, config, session=None):
        self.config = config
        self.http = session or requests.Session()
        self.http.trust_env = False  # No implicit proxies or .netrc credentials.
        self.token = None
        self._secrets = [config.app_token, config.username, config.password,
                         base64.b64encode(f"{config.username}:{config.password}".encode()).decode()]

    def redact(self, value):
        text = str(value)
        for secret in sorted(filter(None, self._secrets), key=len, reverse=True):
            text = text.replace(secret, "[REDACTADO]")
        return text

    def request(self, endpoint, params=None, basic=False):
        if not self.ALLOWED.fullmatch(endpoint):
            raise GLPIError("Endpoint de lectura no permitido.")
        headers = {"App-Token": self.config.app_token, "Content-Type": "application/json", "Accept": "application/json"}
        if basic:
            headers["Authorization"] = "Basic " + self._secrets[3]
        elif self.token:
            headers["Session-Token"] = self.token
        else:
            raise GLPIError("No existe una sesion GLPI activa.")
        try:
            response = self.http.get(self.config.url + "/" + endpoint, headers=headers,
                params=params, timeout=self.config.timeout, verify=self.config.verify_tls,
                allow_redirects=False)
        except requests.RequestException:
            raise GLPIError("GLPI: error de conexion, TLS o timeout.") from None
        if response.status_code not in {200, 206, 416}:
            messages = {401: "autenticacion rechazada", 403: "permisos insuficientes",
                        404: "recurso no disponible", 500: "error del servidor"}
            reason = messages.get(response.status_code, "respuesta HTTP no permitida (redirecciones deshabilitadas)")
            raise GLPIError(f"GLPI HTTP {response.status_code}: {reason}.")
        return response

    @staticmethod
    def json(response):
        try:
            return response.json()
        except ValueError:
            raise GLPIError("GLPI devolvio JSON invalido.") from None

    def __enter__(self):
        try:
            response = self.request("initSession", basic=True)
            data = self.json(response)
            if response.status_code != 200 or not isinstance(data, dict) or not isinstance(data.get("session_token"), str) or not data["session_token"]:
                raise GLPIError("GLPI no devolvio un session_token valido.")
            self.token = data["session_token"]
            self._secrets.append(self.token)
            return self
        except Exception:
            self.http.close()
            raise

    def __exit__(self, exc_type, exc, traceback):
        try:
            response = self.request("killSession")
            if response.status_code != 200:
                raise GLPIError("No se pudo cerrar la sesion GLPI.")
        except GLPIError:
            if exc is None:
                raise
            raise GLPIError("Fallo la consulta GLPI y tambien el cierre de sesion.") from None
        finally:
            self.token = None
            self.http.close()

    def item(self, itemtype, identifier):
        if itemtype not in {"Printer", "Computer", "User", "Location", "NetworkPort", "NetworkName", "State"} or not re.fullmatch(r"[1-9][0-9]*", str(identifier)):
            raise GLPIError("Identificador o tipo de consulta no permitido.")
        response = self.request(f"{itemtype}/{identifier}", {"expand_dropdowns": "false", "get_hateoas": "false"})
        data = self.json(response)
        if response.status_code != 200 or not isinstance(data, dict) or str(data.get("id")) != str(identifier):
            raise GLPIError("GLPI devolvio un objeto incompatible con el identificador solicitado.")
        return data

    def items(self, endpoint, *, expand=False, filters=None):
        rows, seen, start, total = [], set(), 0, None
        for _ in range(10000):
            params = {"range": f"{start}-{start + self.config.page_size - 1}",
                "sort": "id", "order": "ASC", "expand_dropdowns": str(expand).lower(), "get_hateoas": "false"}
            if filters:
                if endpoint != "IPAddress" or set(filters) != {"name"}:
                    raise GLPIError("Filtro de lectura no permitido.")
                params["searchText[name]"] = filters["name"]
            response = self.request(endpoint, params)
            content_range = response.headers.get("Content-Range", "").strip()
            if response.status_code == 416:
                empty = re.fullmatch(r"(?:\w+\s+)?\*/(\d+)", content_range)
                if empty and start >= int(empty[1]) and (total is None or total == int(empty[1])):
                    return rows
                raise GLPIError("GLPI rechazo el rango; no se asume inventario completo.")
            page = self.json(response)
            if isinstance(page, dict) and all(str(key).isdigit() for key in page):
                page = list(page.values())
            if not isinstance(page, list) or any(not isinstance(row, dict) or row.get("id") is None for row in page):
                raise GLPIError("GLPI devolvio una coleccion invalida.")
            match = re.fullmatch(r"(?:\w+\s+)?(\d+)-(\d+)/(\d+|\*)", content_range)
            if content_range and not match:
                raise GLPIError("Content-Range GLPI invalido.")
            if match:
                left, right = int(match[1]), int(match[2])
                current_total = None if match[3] == "*" else int(match[3])
                if total is not None and total != current_total:
                    raise GLPIError("El inventario GLPI cambio durante la paginacion; repetir diagnostico.")
                total = current_total
                if not page:
                    if total == start:
                        return rows
                    raise GLPIError("Pagina GLPI vacia antes del fin del inventario.")
                if left != start or right < left or right - left + 1 != len(page) or (total is not None and right >= total):
                    raise GLPIError("Rango GLPI inconsistente; diagnostico incompleto.")
            elif response.status_code == 206 or total is not None:
                raise GLPIError("Respuesta parcial GLPI sin Content-Range.")
            for row in page:
                identifier = str(row["id"])
                if identifier in seen:
                    raise GLPIError("GLPI repitio objetos entre paginas; diagnostico incompleto.")
                seen.add(identifier)
            rows.extend(page)
            if not page:
                return rows
            start += len(page)
            if total is not None and start == total:
                return rows
            # Even a short page without a range needs a final empty page: server caps vary.
        raise GLPIError("Limite de paginacion alcanzado; diagnostico incompleto.")
