# Diagnóstico GLPI 9.5.5 → NovaDesk (fase de solo lectura)

Esta fase **no sincroniza ni escribe** en NovaDesk o en los objetos GLPI.
Solo usa GET para initSession, colecciones y killSession. La sesión API es
temporal; GLPI puede registrar el acceso y la apertura/cierre de sesión.
No genera usuarios, ubicaciones, activos, impresoras ni detecciones de red.

El cliente compartido está en `apps/integrations/glpi_client.py`, las comparaciones
en `glpi_diagnostics.py` y el comando en la aplicación instalada `apps.core`.
No requiere agregar una app, cambiar settings o crear migraciones.

Dependencia explícita (requests ya puede estar instalada por pywebpush):

```powershell
C:\NovaDeskPro\venv\Scripts\python.exe -m pip install -r apps/integrations/requirements.txt
```

Variables obligatorias: `GLPI_API_URL`, `GLPI_APP_TOKEN`, `GLPI_USERNAME`,
`GLPI_PASSWORD`. Definirlas en el entorno del proceso de desarrollo con el
mecanismo local de secretos aprobado. No versionar archivos .env ni pegar valores
en código, settings, informes, comandos compartidos o capturas.

Para introducirlas en PowerShell sin incluir valores en el historial:

```powershell
$env:GLPI_API_URL = Read-Host 'URL base de la API GLPI de desarrollo'
$env:GLPI_USERNAME = Read-Host 'Usuario API' -MaskInput
$env:GLPI_APP_TOKEN = Read-Host 'App-Token' -MaskInput
$env:GLPI_PASSWORD = Read-Host 'Contraseña API' -MaskInput
```

`-MaskInput` requiere PowerShell 7.1 o superior. En versiones anteriores usar
el gestor local de secretos; no escribir credenciales literales en la consola.
La URL base termina en `apirest.php`, con o sin barra final, sin credenciales
embebidas. No tiene valor por defecto. Ejemplo de formato:
`http://servidor-glpi/apirest.php`.

Opcionales: `GLPI_TIMEOUT` (segundos, default 15, máximo 300), `GLPI_PAGE_SIZE`
(default 100, 1–1000), `GLPI_VERIFY_TLS` (default true; false solo para una
configuración HTTPS autorizada). No se siguen redirecciones ni enlaces devueltos
por GLPI; no se usan proxies/.netrc implícitos. Solo se transmite Basic en
initSession; los demás GET usan App-Token y Session-Token. Nunca se muestran
cuerpos de error, headers, tokens o excepciones de transporte.

```powershell
C:\NovaDeskPro\venv\Scripts\python.exe manage.py sync_glpi --dry-run
C:\NovaDeskPro\venv\Scripts\python.exe manage.py sync_glpi --dry-run --section printers
C:\NovaDeskPro\venv\Scripts\python.exe manage.py sync_glpi --dry-run --section computers
C:\NovaDeskPro\venv\Scripts\python.exe manage.py sync_glpi --dry-run --section users
C:\NovaDeskPro\venv\Scripts\python.exe manage.py sync_glpi --dry-run --section printers --with-network
```

Sin `--dry-run` aborta antes de leer configuración, API o base. Sin variables,
indica el nombre de la variable faltante. Todas las secciones consultan Location;
`all` además consulta Printer, Computer y User. UserEmail se consulta por usuario
porque GLPI conserva los correos en una relación; implica llamadas adicionales.
La cantidad visible depende de los permisos y entidades de la cuenta GLPI.
No se cambia el perfil ni la entidad activa. Un recurso inaccesible aborta el
diagnóstico con ERROR=1; no se presenta como inventario vacío.

Las impresoras se comparan con PrintingDevice por serie (trim + uppercase), sin
eliminar espacios interiores, signos ni ceros. Las computadoras se comparan con
Asset de tipos DESKTOP/LAPTOP por serie; hostname y número de inventario se muestran
como evidencia, sin establecer asociaciones por esos datos todavía. Los grupos
duplicados se reportan por serie, no se elige uno. Los contadores de duplicados
cuentan grupos de series; los detalles incluyen todos sus registros. Series
vacías cuentan como REVISAR por registro.

El reporte de impresoras incluye modelo/nombre GLPI, IDs de ambos sistemas,
photocopier_id, IP NovaDesk, ubicación GLPI/NovaDesk, contact y responsable.
Si la migración anterior de responsible_identity no está aplicada localmente,
se usa la FK local de responsable sin leer esa columna; no se migra el esquema.

Usuarios: correo exacto (UserEmail), o username exacto cuando no hay correo,
mediante `identity_services.search_common_identities`. Puede coincidir una
identidad sin User local. Búsquedas incompletas, ambiguas, inactivas o no elegibles
requieren revisión. El nombre se usa solo como pista para revisión. No se
enlazan fuentes por un correo coincidente fuera de las reglas compartidas.

Ubicaciones: siempre propuestas para revisión; todavía no existe un mapa
aprobado de entidades/sedes GLPI a Branch. No confundir una sede GLPI genérica
con una dependencia organizacional específica. No se crean ubicaciones.

Red es opcional: NetworkPort → NetworkName → IPAddress se sigue por los
identificadores y tipos de relación, nunca por similitud de nombres o IP.
Solo se reportan direcciones válidas; no se identifica una impresora por ellas.
Si no se solicita red, el reporte indica IP_GLPI_NO_CONSULTADA. Diferencias
IP_DIFERENTE o UBICACION_DIFERENTE son evidencia para revisión, no actualizaciones.

La paginación valida Content-Range, avanza por el rango realmente devuelto y
detecta IDs repetidos, cambios de total y respuestas parciales incompletas. Sin
header, exige una página final vacía. No es una foto transaccional de GLPI;
conviene repetir el diagnóstico si el inventario cambia durante la consulta.

El informe contiene datos institucionales: manejarlo como información interna.
No se escribe automáticamente a archivos ni se persiste session_token.

Pruebas sin servidor real:

```powershell
C:\NovaDeskPro\venv\Scripts\python.exe manage.py test apps.integrations.test_glpi
```

Referencia de protocolo:
[API REST GLPI 9.5.5](https://github.com/glpi-project/glpi/blob/9.5.5/apirest.md).
