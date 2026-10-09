# Importación Excel de impresoras al Printing existente

## Modelo y restricciones

Se usa `apps.printing.models.PrintingDevice`, administrado por
`PrintingDeviceAdmin`. Las vistas existentes son dashboard, listado por modelo y
detalle; `PrintingTicketStockUsageForm` registra consumibles y no crea impresoras.
El formulario de equipos lo genera el ModelAdmin a partir del modelo.

Relaciones: asset opcional OneToOne a Inventory.Asset; branch a Accounts.Branch;
organizational_location a Inventory.OrganizationalLocation; responsible_user a
Accounts.User. No existe department directo. PrintingContract.devices relaciona
contratos con equipos, pero el importador no consulta ni modifica esa relacion. PrintingDeviceNetworkDetection guarda observaciones
de red con fecha, no una configuración IP importable del equipo.

La clave del importador es Serie, comparada sin distinguir mayúsculas y tras
normalizar espacios. `serial_number` NO tiene unique=True. `photocopier_id` sí es
único. ID origen se mapea a photocopier_id tras validación; Calcomanía no se usa como ID.
La relación asset también es única. Branch tiene code/name únicos; Location tiene
unicidad (branch, code); Contract tiene contract_number único. Nombres de ubicaciones
y diferencias solo de mayúsculas pueden ser ambiguos y no se asocian arbitrariamente.

Si serial_number está vacío, también se busca effective_serial_number del activo
ya vinculado, para evitar crear otra impresora para el mismo equipo.

## Mapeo Excel -> NovaDesk

| Excel | Destino / regla |
|---|---|
| N° origen | Texto de trazabilidad en notes; no es el UUID del modelo |
| ID origen | photocopier_id si es valido, libre y compatible; se conserva copia en notes |
| Serie | PrintingDevice.serial_number; clave de importación |
| Modelo | PrintingDevice.model; marca Lexmark solo para familias aprobadas |
| Sede | PrintingDevice.branch, aliases aprobados o code/name exactos normalizados de una sede activa |
| Dependencia | organizational_location, solo code/name/full_path exactos dentro de la sede activa; si no existe equivalencia, se usa UBICACION-PENDIENTE de la sede cuando no hay una ubicación existente válida; la Dependencia original se conserva íntegra en notes |
| Responsable | responsible_user, solo correo o username exacto de una cuenta activa y aprobada, con una única coincidencia; en otro caso texto en notes |
| IP anterior | IP validada y normalizada en notes |
| IP actual | IPv4 validada en PrintingDevice.ip_address y notes; no crea una detección de red |
| Conexión | Texto en notes; no se traduce a supports_network por suposición |
| Calcomanía | Texto en notes; no se presume photocopier_id |
| Nombre impresora | Texto en notes; el modelo no tiene ese campo |
| Contrato | Ignorado: no se guarda en notes ni se resuelve o vincula PrintingContract |
| Tipo servicio | Texto en notes; no se presume ownership_type ni contract_type |
| Estado validación | REVISAR ignora la fila; otros valores se conservan en notes |
| Observaciones | Texto dentro del bloque de importación de notes |

Las columnas declaradas deben estar todas presentes en la primera fila de
IMPORTACION_PRINTING. Su orden puede variar y se normalizan espacios/case de
encabezados. Los valores pueden estar vacíos; el modelo determina los requisitos.
No se crean sedes, ubicaciones, activos, responsables ni contratos.

## Uso

Desde el entorno Django y directorio con manage.py:

```powershell
python manage.py import_printers 'RUTA\Impresoras_NovaDesk_Importacion_Limpia.xlsx' --dry-run
python manage.py import_printers 'RUTA\Impresoras_NovaDesk_Importacion_Limpia.xlsx' --dry-run --brand 'MARCA_CONFIRMADA'
```

Para aplicar, revisar el resultado y usar el mismo comando sin `--dry-run` en el
entorno autorizado. La preparación de este comando no autoriza ejecutarlo contra
producción. El archivo con datos personales debe mantenerse fuera de Git.

La marca Lexmark se infiere exclusivamente para MX622, MX611, MX521, MX632,
MX711, MX722, CX622 y CX725, con sufijos de letras opcionales. Se admite prefijo
Lexmark. Otros modelos se RECHAZAN con aviso REVISAR, sin modificar el Excel.
--brand se conserva por compatibilidad como confirmacion opcional Lexmark; no
permite eludir la whitelist ni una marca existente incompatible.

Aliases aprobados: Villa Elisa y Viila Elisa -> PLANTA-VILLA-ELISA;
Centro -> OFICINA-CENTRAL; Troche -> PLANTA-MAURICIO-JOSE-TROCHE.
No hay busqueda aproximada. Los destinos deben existir y estar activos.

Para nuevas impresoras sin ubicacion exacta se usa exclusivamente la ubicacion
activa con codigo UBICACION-PENDIENTE dentro de la sede resuelta. Se conserva una
ubicacion existente valida en esa sede. No se crean datos maestros desde el
importador. Las ubicaciones provisionales fueron aprobadas para este lote; las
notas mantienen integro el texto original de Dependencia.

El modelo exige marca, modelo, sede y ubicacion para tercerizados sin activo.
No desactivar is_outsourced para esquivar esa regla.

Los campos no incluidos mantienen sus valores actuales o defaults del modelo
para equipos nuevos (PRINTER, LASER, MONOCHROME, OWNED, is_outsourced=True,
supports_network=True, is_active=True). Esos defaults NO se deducen del Excel.
Revisar especialmente ownership_type y capacidades de equipos nuevos; el archivo
no permite confirmar esas propiedades con las equivalencias actualmente conocidas.

## Validación y resultados

- Serie debe ser texto, no vacía, con identificación válida y máximo 150 caracteres. Se rechazan marcadores S/N, SIN SERIE, etc. Las celdas numéricas se rechazan para no inventar ceros iniciales.
- IP actual requiere IPv4; IP anterior admite IPv4/IPv6 y queda en notes. Una IP no vacía inválida rechaza solo esa fila con aviso REVISAR, sin abortar otras filas.
- Las fórmulas se rechazan; convertirlas a valores antes de importar. Las filas totalmente vacías no se procesan. Límite: 50.000 filas.
- Una serie repetida en el Excel rechaza todas sus filas procesables. Las filas REVISAR no cuentan como duplicados ni se validan.
- Varias impresoras existentes con la misma serie normalizada producen RECHAZADO; el comando no elige una ni borra registros.
- Valores vacíos no borran campos estructurados existentes, excepto IP actual: una celda vacía deja ip_address=NULL. Asociaciones no resueltas se conservan como texto pendiente sin reemplazar asociaciones actuales.
- NUEVO / ACTUALIZADO / SIN CAMBIOS / RECHAZADO / IGNORADO se reportan por número de fila, con resumen final y cantidad de filas pendientes. No se imprime el contenido personal de Responsable.

Las notas manuales se preservan. El bloque entre
`[[NOVADESK_IMPORT_PRINTERS_V1]]` y `[[/NOVADESK_IMPORT_PRINTERS_V1]]` se reemplaza
idempotentemente. No editar sus marcadores. Un bloque dañado rechaza la fila.
Las notas pueden contener datos personales, visibles según los permisos actuales
sobre el equipo; no exponerlas públicamente ni versionar archivos de origen.

--dry-run solo consulta/valida: no llama save ni escribe relaciones.
La aplicación real usa una sola transaction.atomic y bloquea equipos existentes.
Los errores de fila permiten importar las filas válidas. Los errores críticos de
lectura/esquema cancelan antes de guardar; errores críticos durante guardado hacen
rollback de toda la importación. El resumen de éxito solo
se emite después de confirmar la transacción.

IMPORTANTE: sin restricción única en la base no hay garantía de unicidad frente a
dos importadores o altas manuales concurrentes. Ejecutar con un único escritor y
sin altas simultáneas. No se agrega esa restricción porque no se autorizaron
migraciones. Tampoco se modifica la IP estructurada del historial de red.

## Tests

```powershell
python manage.py check
python manage.py test apps.printing
python manage.py test apps.printing.test_import_printers
git diff --check
```

Los tests crean Excel sintéticos en un directorio temporal y verifican dry-run sin
INSERT/UPDATE/DELETE, importación y actualización real, idempotencia, relaciones,
duplicados, IP, REVISAR, columnas, fórmulas y rollback.

## Preparacion reproducible de datos maestros

Antes de simular/importar en un entorno autorizado:

```powershell
python manage.py prepare_printing_master_data --dry-run
python manage.py prepare_printing_master_data
python manage.py import_printers 'RUTA\Impresoras_NovaDesk_Importacion_Limpia.xlsx' --dry-run
```

La preparacion valida todo el conjunto antes de guardar y usa transaction.atomic.
Crea solo las tres sedes aprobadas que falten y una ubicacion provisional activa
por sede con codigo UBICACION-PENDIENTE, tipo OTHER y sin parent. La sede Villa
Elisa se reutiliza tanto con nombre Planta Villa Elisa como Sede Villa Elisa.
Oficina Central se crea como OFFICE; una existente HEADQUARTERS tambien es
compatible. Las dos plantas requieren INDUSTRIAL_PLANT. No modifica registros
existentes ni crea equipos, activos, contratos o usuarios. --dry-run no escribe.

Codigos o nombres reservados duplicados/incompatibles, estado inactivo, tipo
incorrecto o ubicacion provisional incompatible abortan sin sobrescribir. Las
restricciones existentes de code y (branch, code) protegen contra duplicados;
una colision concurrente aborta y revierte. Los errores criticos de guardado
revierten todo el lote. No hay migraciones ni dependencia del Excel para preparar
estos maestros. La importacion de equipos sigue siendo un paso separado.

## Contratos pendientes de validacion oficial y limpieza

Los contratos no se importan hasta validacion oficial. La columna Contrato del
Excel se ignora, incluso si coincide con un PrintingContract existente. No se
crean, consultan ni vinculan contratos desde este importador. El valor
PR/PR N° 012/22 de la planilla puede ser de prueba y no es un dato confirmado.

Para retirar ese valor de notas generadas anteriormente:

```powershell
python manage.py clean_printer_import_contract_notes --dry-run
python manage.py clean_printer_import_contract_notes
```

La ejecucion real debe hacerse solo en un entorno autorizado, despues de revisar
el dry-run. Esta preparacion no ejecuta limpieza real en produccion.

El comando elimina exclusivamente la linea Contrato: PR/PR N° 012/22 dentro
del bloque delimitado por [[NOVADESK_IMPORT_PRINTERS_V1]] y su cierre. Preserva
notas manuales, dependencia, responsable, IPs y todas las otras lineas. No toca
contratos ni relaciones existentes. Marcadores incompletos, duplicados o en orden
incorrecto se reportan como ERROR; la limpieza real aborta sin cambios.

--dry-run no escribe y muestra cuantos equipos serian limpiados. Sin ese flag se
usa transaction.atomic y se actualizan solo notes y updated_at de los registros
afectados. Repetirla produce SIN CAMBIOS para equipos ya limpiados. Un error
critico de guardado revierte toda la limpieza. Los reportes usan UUID y estado,
sin imprimir el contenido de las notas.

## IP actual estructurada y migracion desde notas

La migracion printing.0017_printingdevice_ip_address agrega un campo opcional
GenericIPAddressField(protocol="IPv4", null=True, blank=True). Debe aplicarse
antes de usar el codigo nuevo. No incluye migracion automatica de datos.
El listado muestra exclusivamente device.ip_address o una raya si esta vacio.
El admin mantiene su formulario explicito sin agregar edicion manual de IP.

El importador guarda una IPv4 actual valida en ip_address y mantiene su copia en
notes por trazabilidad. IP anterior permanece en notes. Una celda IP actual vacia
establece NULL, incluso en una actualizacion. Una celda invalida/IPv6 rechaza la
fila con aviso REVISAR sin detener el resto. No usa web_interface_url ni crea
PrintingDeviceNetworkDetection.

Despues de aplicar la migracion de esquema en el entorno autorizado:

```powershell
python manage.py migrate_printer_ips_from_notes --dry-run
python manage.py migrate_printer_ips_from_notes
```

La ejecucion real requiere autorizacion para ese entorno. El comando solo toma
IP actual de un unico bloque [[NOVADESK_IMPORT_PRINTERS_V1]] bien delimitado.
IP ausente/vacia o ya igual -> SIN CAMBIOS; IPv4 valida con campo vacio ->
ACTUALIZADO; IPv4 invalida, varias lineas IP actual o conflicto con una IP ya
almacenada -> REVISAR, sin sobrescribir. Bloques danados -> ERROR, abortando la
ejecucion real antes de guardar. Un fallo critico revierte todo el lote.

--dry-run no escribe. La ejecucion real usa transaction.atomic y bloquea los
equipos existentes; solo actualiza ip_address, sin alterar notes, updated_at,
relaciones u otros campos. Es idempotente y no crea detecciones de red. Los
reportes muestran UUID/estado/motivo, sin imprimir notas ni direcciones IP.

## ID de fotocopiadora desde ID origen

El importador usa exclusivamente ID origen para photocopier_id. Nunca genera IDs
ni utiliza N° origen como reemplazo. ID vacio mantiene el identificador existente.
ID invalido, incompatible o duplicado rechaza la fila con aviso REVISAR; no se
elige arbitrariamente una fila ganadora. REVISAR del Excel sigue ignorandose.

Validacion compartida: texto/entero, 1-50 caracteres ASCII, empieza por letra o
digito y contiene solo letras, digitos, guion, guion bajo o barra /. Se quitan espacios
externos, se conservan ceros iniciales y no se aceptan decimales, booleanos,
espacios internos, marcadores sin identificacion o valores solo de ceros.
Duplicados se comparan sin distinguir mayusculas, incluyendo equipos sin bloque
de importacion y equipos inactivos. La restriccion unique de BD permanece como
proteccion final frente a escrituras concurrentes.

Para equipos ya importados, despues de revisar la simulacion en el entorno
correspondiente:

```powershell
python manage.py migrate_printer_ids_from_notes --dry-run
python manage.py migrate_printer_ids_from_notes
```

La ejecucion real requiere autorizacion y no se realiza como parte de esta
preparacion. El comando procesa solo equipos con el marcador de apertura del
bloque importado y extrae una unica linea ID origen. No lee IDs de notas manuales.
Ausente/vacio o ya coincidente -> SIN CAMBIOS; valido y campo vacio -> ACTUALIZADO;
invalido, varias lineas ID origen, ID ocupado, duplicado en lote o ID existente
distinto -> REVISAR con motivo. Bloques danados -> ERROR, abortando el lote real.

El dry-run no escribe. La ejecucion real usa transaction.atomic, valida todas
las colisiones antes de guardar y actualiza exclusivamente photocopier_id,
sin modificar notes, updated_at, serial, responsables, IP o relaciones. Un error
critico de guardado revierte toda la transaccion. Repetir no modifica equipos ya
migrados. No hay migraciones de esquema ni nuevas entidades.

IDs como 55/BK son validos y conservan exactamente la barra /. Los marcadores
S/N y N/A siguen siendo invalidos, sin distinguir mayusculas.
