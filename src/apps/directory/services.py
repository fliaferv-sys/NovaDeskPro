from contextlib import closing

import pyodbc
from django.conf import settings


class DirectoryDatabaseError(Exception):
	pass


_MAX_DIRECTORY_LIMIT = 5000

_REQUIRED_CONFIGURATION = (
	"DIRECTORY_SQL_HOST",
	"DIRECTORY_SQL_DATABASE",
	"DIRECTORY_SQL_USER",
	"DIRECTORY_SQL_PASSWORD",
)

_DIRECTORY_COLUMNS = (
	"LegajoNro",
	"NombresApellidos",
	"IdPersonal",
	"Ubicacion",
	"Telefono",
	"Mail",
	"Estado",
	"Vinculo",
	"DesvinculacionFecha",
	"Cargo",
)


def _validate_directory_configuration():
	missing = [
		name
		for name in _REQUIRED_CONFIGURATION
		if not str(getattr(settings, name, "")).strip()
	]
	if missing:
		raise DirectoryDatabaseError(
			"Configuración incompleta de SQL Server para el directorio: "
			+ ", ".join(missing)
		)


def _odbc_value(value):
	return "{" + str(value).replace("}", "}}") + "}"


def _open_directory_connection():
	_validate_directory_configuration()
	server = (
		f"{settings.DIRECTORY_SQL_HOST},"
		f"{settings.DIRECTORY_SQL_PORT}"
	)

	connection_string = ";".join(
		(
			f"DRIVER={_odbc_value(settings.DIRECTORY_SQL_DRIVER)}",
			f"SERVER={_odbc_value(server)}",
			f"DATABASE={_odbc_value(settings.DIRECTORY_SQL_DATABASE)}",
			f"UID={_odbc_value(settings.DIRECTORY_SQL_USER)}",
			f"PWD={_odbc_value(settings.DIRECTORY_SQL_PASSWORD)}",
			"Encrypt=yes",
			"TrustServerCertificate=yes",
			"ApplicationIntent=ReadOnly",
		)
	)

	try:
		return pyodbc.connect(connection_string, timeout=5)
	except pyodbc.Error as exc:
		raise DirectoryDatabaseError(
			"No fue posible conectar con la base de datos del directorio."
		) from exc


def test_directory_connection():
	try:
		connection = _open_directory_connection()
		with closing(connection):
			with closing(connection.cursor()) as cursor:
				cursor.execute("SELECT 1")
				cursor.fetchone()
		return True
	except pyodbc.Error as exc:
		raise DirectoryDatabaseError(
			"No fue posible probar la conexión del directorio."
		) from exc


def get_directory_employees(limit=50):
	if (
		not isinstance(limit, int)
		or isinstance(limit, bool)
		or not 1 <= limit <= _MAX_DIRECTORY_LIMIT
	):
		raise ValueError(
			f"limit debe ser un entero entre 1 y {_MAX_DIRECTORY_LIMIT}."
		)

	columns = ", ".join(_DIRECTORY_COLUMNS)
	query = (
		f"SELECT TOP ({limit}) {columns} "
		"FROM dbo.FuncionariosFotosVista "
		"ORDER BY NombresApellidos"
	)

	try:
		connection = _open_directory_connection()
		with closing(connection):
			with closing(connection.cursor()) as cursor:
				cursor.execute(query)
				rows = cursor.fetchall()

		return [
			dict(zip(_DIRECTORY_COLUMNS, row))
			for row in rows
		]
	except pyodbc.Error as exc:
		raise DirectoryDatabaseError(
			"No fue posible consultar el directorio institucional."
		) from exc


def search_directory_employees(query="", limit=100):
	if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 200:
		raise ValueError("limit debe ser un entero entre 1 y 200.")

	query = (query or "").strip()
	columns = ", ".join(_DIRECTORY_COLUMNS)
	sql = (
		f"SELECT TOP ({limit}) {columns} "
		"FROM dbo.FuncionariosFotosVista "
	)
	parameters = ()
	if query:
		sql += (
			"WHERE CAST(LegajoNro AS NVARCHAR(255)) LIKE ? "
			"OR NombresApellidos LIKE ? "
			"OR Ubicacion LIKE ? "
			"OR Mail LIKE "
			"? "
		)
		search_term = f"%{query}%"
		parameters = (search_term,) * 4
	sql += "ORDER BY NombresApellidos"

	try:
		connection = _open_directory_connection()
		with closing(connection):
			with closing(connection.cursor()) as cursor:
				cursor.execute(sql, *parameters)
				rows = cursor.fetchall()

		return [
			dict(zip(_DIRECTORY_COLUMNS, row))
			for row in rows
		]
	except pyodbc.Error as exc:
		raise DirectoryDatabaseError(
			"No fue posible consultar el directorio institucional."
		) from exc


def get_directory_employee_by_id_personal(id_personal):
	if isinstance(id_personal, bool):
		raise ValueError("IdPersonal debe ser un entero positivo.")

	if isinstance(id_personal, int):
		validated_id = id_personal
	elif isinstance(id_personal, str):
		id_text = id_personal.strip()
		if not id_text or not id_text.isascii() or not id_text.isdecimal():
			raise ValueError("IdPersonal debe ser un entero positivo.")
		try:
			validated_id = int(id_text)
		except ValueError as exc:
			raise ValueError("IdPersonal debe ser un entero positivo.") from exc
	else:
		raise ValueError("IdPersonal debe ser un entero positivo.")

	if validated_id <= 0:
		raise ValueError("IdPersonal debe ser un entero positivo.")

	columns = ", ".join(_DIRECTORY_COLUMNS)
	sql = (
		f"SELECT {columns} "
		"FROM dbo.FuncionariosFotosVista "
		"WHERE IdPersonal = ?"
	)

	try:
		connection = _open_directory_connection()
		with closing(connection):
			with closing(connection.cursor()) as cursor:
				cursor.execute(sql, validated_id)
				row = cursor.fetchone()

		if row is None:
			return None
		return dict(zip(_DIRECTORY_COLUMNS, row))
	except pyodbc.Error as exc:
		raise DirectoryDatabaseError(
			"No fue posible consultar el funcionario en el directorio."
		) from exc
