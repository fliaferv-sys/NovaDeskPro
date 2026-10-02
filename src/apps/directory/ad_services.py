from contextlib import contextmanager
import ssl

from django.conf import settings
from ldap3 import ALL, Connection, Server, Tls
from ldap3.core.exceptions import LDAPException
from ldap3.utils.conv import escape_filter_chars


class ActiveDirectoryError(Exception):
    pass


_REQUIRED_AD_CONFIGURATION = (
    "DIRECTORY_AD_HOST",
    "DIRECTORY_AD_BASE_DN",
    "DIRECTORY_AD_USER",
    "DIRECTORY_AD_PASSWORD",
)

_AD_USER_ATTRIBUTES = (
    "displayName",
    "givenName",
    "sn",
    "mail",
    "sAMAccountName",
    "userPrincipalName",
    "userAccountControl",
    "distinguishedName",
)

_GENERIC_AD_ERROR = "No fue posible consultar Active Directory."


def _validate_ad_configuration():
    missing = [
        name
        for name in _REQUIRED_AD_CONFIGURATION
        if not str(getattr(settings, name, "")).strip()
    ]
    if missing:
        raise ActiveDirectoryError(
            "Configuración incompleta de Active Directory: "
            + ", ".join(missing)
        )


def _open_ad_connection():
    _validate_ad_configuration()

    tls_options = {
        "validate": (
            ssl.CERT_REQUIRED
            if settings.DIRECTORY_AD_TLS_VALIDATE
            else ssl.CERT_NONE
        ),
    }
    ca_cert_file = getattr(settings, "DIRECTORY_AD_CA_CERT_FILE", "")
    if ca_cert_file:
        tls_options["ca_certs_file"] = ca_cert_file

    try:
        tls = Tls(**tls_options)
        server = Server(
            host=settings.DIRECTORY_AD_HOST,
            port=settings.DIRECTORY_AD_PORT,
            use_ssl=settings.DIRECTORY_AD_USE_SSL,
            tls=tls,
            get_info=ALL,
        )
        return Connection(
            server,
            user=settings.DIRECTORY_AD_USER,
            password=settings.DIRECTORY_AD_PASSWORD,
            auto_bind=True,
            raise_exceptions=True,
        )
    except LDAPException as exc:
        raise ActiveDirectoryError(_GENERIC_AD_ERROR) from exc


@contextmanager
def _bound_ad_connection():
    connection = _open_ad_connection()
    try:
        yield connection
    except LDAPException as exc:
        raise ActiveDirectoryError(_GENERIC_AD_ERROR) from exc
    finally:
        try:
            connection.unbind()
        except LDAPException:
            pass


def test_ad_connection():
    with _bound_ad_connection() as connection:
        if not connection.bound:
            raise ActiveDirectoryError(
                "No fue posible establecer la conexión con Active Directory."
            )
    return True


def _entry_to_user(entry):
    attributes = getattr(entry, "entry_attributes_as_dict", {}) or {}

    def value(attribute):
        result = attributes.get(attribute, "")
        if isinstance(result, (list, tuple)):
            result = result[0] if result else ""
        return "" if result is None else result

    account_control = value("userAccountControl")
    try:
        account_control = int(account_control or 0)
    except (TypeError, ValueError):
        account_control = 0

    return {
        "name": value("displayName"),
        "first_name": value("givenName"),
        "last_name": value("sn"),
        "email": value("mail"),
        "username": value("sAMAccountName"),
        "user_principal_name": value("userPrincipalName"),
        "is_active": not bool(account_control & 2),
    }


def get_ad_user_by_email(email):
    if not isinstance(email, str) or not email.strip():
        raise ValueError("email debe ser una cadena no vacía.")

    email = email.strip()
    search_filter = (
        "(&(objectCategory=person)(objectClass=user)"
        f"(mail={escape_filter_chars(email)}))"
    )

    try:
        with _bound_ad_connection() as connection:
            connection.search(
                search_base=settings.DIRECTORY_AD_BASE_DN,
                search_filter=search_filter,
                attributes=_AD_USER_ATTRIBUTES,
                size_limit=1,
            )
            if not connection.entries:
                return None
            return _entry_to_user(connection.entries[0])
    except LDAPException as exc:
        raise ActiveDirectoryError(_GENERIC_AD_ERROR) from exc


def search_ad_users(query, limit=20):
    if not isinstance(query, str):
        raise ValueError("query debe ser una cadena.")
    if (
        not isinstance(limit, int)
        or isinstance(limit, bool)
        or not 1 <= limit <= 100
    ):
        raise ValueError("limit debe ser un entero entre 1 y 100.")

    query = query.strip()
    if len(query) < 2:
        return []

    escaped_query = escape_filter_chars(query)
    search_filter = (
        "(&(objectCategory=person)(objectClass=user)(|"
        f"(displayName=*{escaped_query}*)"
        f"(mail=*{escaped_query}*)"
        f"(sAMAccountName=*{escaped_query}*)"
        f"(userPrincipalName=*{escaped_query}*)"
        "))"
    )

    try:
        with _bound_ad_connection() as connection:
            connection.search(
                search_base=settings.DIRECTORY_AD_BASE_DN,
                search_filter=search_filter,
                attributes=_AD_USER_ATTRIBUTES,
                size_limit=limit,
            )
            return [
                _entry_to_user(entry)
                for entry in connection.entries[:limit]
            ]
    except LDAPException as exc:
        raise ActiveDirectoryError(_GENERIC_AD_ERROR) from exc
