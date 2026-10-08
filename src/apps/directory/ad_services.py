from contextlib import contextmanager
import ssl
import sys

from django.conf import settings
from ldap3 import ALL, Connection, Server, Tls
from ldap3.core.exceptions import LDAPBindError, LDAPException, LDAPSizeLimitExceededResult
from ldap3.utils.conv import escape_filter_chars


class ActiveDirectoryError(Exception):
    pass


_REQUIRED_AD_CONFIGURATION = (
    "DIRECTORY_AD_HOST",
    "DIRECTORY_AD_BASE_DN",
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
    _has_explicit_ad_credentials()


def _has_explicit_ad_credentials():
    username = str(getattr(settings, "DIRECTORY_AD_USER", "") or "").strip()
    password = str(getattr(settings, "DIRECTORY_AD_PASSWORD", "") or "").strip()
    if bool(username) != bool(password):
        raise ActiveDirectoryError(
            "Configuración incompleta de credenciales de Active Directory."
        )
    return bool(username and password)


def _is_windows():
    return sys.platform == "win32"


def _use_windows_integrated_authentication():
    _validate_ad_configuration()
    if _has_explicit_ad_credentials():
        return False
    if _is_windows():
        return True
    raise ActiveDirectoryError(_GENERIC_AD_ERROR)


def _open_ad_connection():
    _validate_ad_configuration()
    if not _has_explicit_ad_credentials():
        raise ActiveDirectoryError(_GENERIC_AD_ERROR)

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


def _load_win32_client():
    try:
        from win32com import client
    except ImportError as exc:
        raise ActiveDirectoryError(_GENERIC_AD_ERROR) from exc
    return client


def _close_com_object(com_object, method_name):
    if com_object is None:
        return
    try:
        getattr(com_object, method_name)()
    except Exception:
        pass


def _open_windows_ad_connection():
    _validate_ad_configuration()
    if not _is_windows():
        raise ActiveDirectoryError(_GENERIC_AD_ERROR)

    connection = None
    try:
        win32_client = _load_win32_client()
        connection = win32_client.Dispatch("ADODB.Connection")
        connection.Provider = "ADsDSOObject"
        connection.Open("Active Directory Provider")
        return connection
    except ActiveDirectoryError:
        _close_com_object(connection, "Close")
        raise
    except Exception as exc:
        _close_com_object(connection, "Close")
        raise ActiveDirectoryError(_GENERIC_AD_ERROR) from exc


def _windows_record_value(recordset, attribute):
    value = recordset.Fields(attribute).Value
    if isinstance(value, (list, tuple)):
        value = value[0] if value else ""
    return "" if value is None else value


def _windows_record_to_user(recordset):
    def value(attribute):
        try:
            return _windows_record_value(recordset, attribute)
        except Exception:
            return ""

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


def _windows_search(search_filter, limit, attributes=_AD_USER_ATTRIBUTES):
    connection = None
    command = None
    recordset = None
    try:
        win32_client = _load_win32_client()
        connection = _open_windows_ad_connection()
        command = win32_client.Dispatch("ADODB.Command")
        command.ActiveConnection = connection
        command.CommandText = (
            f"<LDAP://{settings.DIRECTORY_AD_BASE_DN}>;"
            f"{search_filter};{','.join(attributes)};subtree"
        )
        execution = command.Execute()
        recordset = execution[0] if isinstance(execution, (tuple, list)) else execution

        users = []
        while not recordset.EOF and len(users) < limit:
            users.append(_windows_record_to_user(recordset))
            recordset.MoveNext()
        return users
    except ActiveDirectoryError:
        raise
    except Exception as exc:
        raise ActiveDirectoryError(_GENERIC_AD_ERROR) from exc
    finally:
        _close_com_object(recordset, "Close")
        _close_com_object(connection, "Close")


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
    if _use_windows_integrated_authentication():
        _windows_search(
            "(&(objectCategory=person)(objectClass=user))",
            1,
            attributes=("distinguishedName",),
        )
        return True

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

    if _use_windows_integrated_authentication():
        users = _windows_search(search_filter, 1)
        return users[0] if users else None

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


def search_ad_users(query, limit=20, *, exact_email=False, search_field=None, exact=False):
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

    if search_field is not None:
        field_attributes = {"email": "mail", "username": "sAMAccountName", "name": "displayName"}
        if search_field not in field_attributes:
            raise ValueError("Campo de búsqueda AD inválido.")
        attribute = field_attributes[search_field]
        term = escaped_query if exact else f"*{escaped_query}*"
        search_filter = f"(&(objectCategory=person)(objectClass=user)({attribute}={term}))"
    elif exact_email:
        search_filter = (
            "(&(objectCategory=person)(objectClass=user)"
            f"(mail={escaped_query}))"
        )

    if _use_windows_integrated_authentication():
        return _windows_search(search_filter, limit)

    try:
        with _bound_ad_connection() as connection:
            try:
                connection.search(
                    search_base=settings.DIRECTORY_AD_BASE_DN,
                    search_filter=search_filter,
                    attributes=_AD_USER_ATTRIBUTES,
                    size_limit=limit,
                )
            except LDAPSizeLimitExceededResult:
                # Two exact matches already prove ambiguity, even if AD has more.
                if not (exact_email or search_field is not None) or len(connection.entries) < limit:
                    raise
            return [
                _entry_to_user(entry)
                for entry in connection.entries[:limit]
            ]
    except LDAPException as exc:
        raise ActiveDirectoryError(_GENERIC_AD_ERROR) from exc


def authenticate_windows_credentials(identifier, password):
    if not isinstance(identifier, str):
        raise ValueError("identifier debe ser una cadena no vacía.")
    identifier = identifier.strip()
    if not identifier:
        raise ValueError("identifier debe ser una cadena no vacía.")

    if not isinstance(password, str) or password == "":
        raise ValueError("password debe ser una cadena no vacía.")

    if not _is_windows():
        return False

    try:
        import pywintypes
        import win32security
    except ImportError:
        return False

    if "@" in identifier:
        username = identifier
        domain = None
    elif "\\" in identifier:
        domain, username = identifier.split("\\", 1)
        if not domain or not username:
            return False
    else:
        username = identifier
        domain = (
            getattr(settings, "DIRECTORY_AD_NETBIOS_DOMAIN", "PETROPAR")
            or "PETROPAR"
        )

    token = None
    try:
        token = win32security.LogonUser(
            username,
            domain,
            password,
            win32security.LOGON32_LOGON_NETWORK,
            win32security.LOGON32_PROVIDER_DEFAULT,
        )
    except pywintypes.error:
        return False
    except Exception:
        return False

    try:
        return True
    finally:
        try:
            token.Close()
        except Exception:
            pass


def authenticate_ad_credentials(identifier, password):
    if not isinstance(identifier, str):
        raise ValueError("identifier debe ser una cadena no vacía.")
    identifier = identifier.strip()
    if not identifier:
        raise ValueError("identifier debe ser una cadena no vacía.")

    if not isinstance(password, str) or password == "":
        raise ValueError("password debe ser una cadena no vacía.")

    _validate_ad_configuration()

    bind_user = (
        identifier
        if "@" in identifier
        else f"{identifier}@{settings.DIRECTORY_AD_DOMAIN}"
    )
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

    connection = None
    try:
        tls = Tls(**tls_options)
        server = Server(
            host=settings.DIRECTORY_AD_HOST,
            port=settings.DIRECTORY_AD_PORT,
            use_ssl=settings.DIRECTORY_AD_USE_SSL,
            tls=tls,
            get_info=ALL,
        )
        connection = Connection(
            server,
            user=bind_user,
            password=password,
            auto_bind=True,
            raise_exceptions=True,
        )
        return True
    except LDAPBindError:
        return False
    except LDAPException as exc:
        raise ActiveDirectoryError(_GENERIC_AD_ERROR) from exc
    finally:
        if connection is not None:
            try:
                connection.unbind()
            except LDAPException:
                pass
