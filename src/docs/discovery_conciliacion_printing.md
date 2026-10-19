# Discovery autorizado y conciliación de Printing

## Alcance

`network_map.py` contiene 29 redes autorizadas: 21 de Villa Elisa y ocho de Oficina
Central. Las etiquetas son exclusivamente evidencia de sede/sector de red. No
modifican Branch, OrganizationalUnit, Department ni ubicación RRHH. Las cuatro
redes PENDIENTE_CONFIRMAR se pueden consultar sin asignar ubicación. La red
10.16.32.0/24 conserva la etiqueta especial Piso 1.

No se expande la regla 10.<X>.32.0/24 a pisos no enumerados. Redes core, /16,
/8, IPv6 o redes fuera del mapa se rechazan antes de cualquier conexión.

No hay tabla nueva, migración ni creación automática de PrintingDevice.
No se modifican los comandos monitor_printers ni recover_offline_printers.
El sistema no instala jobs ni consulta redes reales durante las pruebas.

## Adaptadores y discovery

`network_discovery.py` valida todas las subredes solicitadas, elimina duplicados
y recorre cada /24 una sola vez. No incluye network/broadcast. Las subredes se
procesan secuencialmente; cada una usa entre uno y ocho workers HTTP. El timeout
predeterminado es un segundo por consulta y el máximo tres segundos.

Los workers no usan ORM. `discovery_adapters.py` contiene el registro ADAPTERS;
solo LexmarkEWSAdapter está implementado. Otros fabricantes podrán incorporarse
con adaptadores reales y probados, sin cambiar la conciliación.

Lexmark reutiliza `fetch_network_identity()` sin modificarlo. Solo una respuesta
que cumple su contrato EthernetUAA/SetHostname se considera identidad Lexmark EWS
soportada. Un servidor HTTP genérico queda UNIDENTIFIED; un host sin respuesta se
descarta. No se considera impresora a cualquier servidor que acepte TCP o HTTP.

Después de identificar el EWS, intenta GET a:

`http://<ip>/webglue/rawcontent?c=DeviceInformation`

El lector opcional reconoce exclusivamente nodos explícitos SerialNumber,
ModelName y Manufacturer con referencias dinámicas a nodes.settings[id].val.
No usa IDs numéricos fijos ni extrae números de etiquetas genéricas, hostname o
HTML. Valores duplicados, desconocidos o inválidos se descartan. Un fabricante
declarado distinto de Lexmark genera conflicto. Un endpoint ausente, un formato
desconocido o una consulta fallida deja serial/modelo vacíos y permite usar la
MAC conocida; no inventa esos campos.

No se recibió ni se probó un payload DeviceInformation real de producción en esta
entrega. Firmware con otros esquemas o rutas requiere una muestra y una prueba de
parser antes de usar su serial como evidencia. La cobertura actual verifica el
esquema explícito descrito mediante respuestas simuladas.

Ambas consultas usan solamente GET, con respuestas acotadas a 1 MiB, sin
redirecciones ni proxies de entorno. No usan SNMP, POST, credenciales ni cambian
configuraciones. No se almacenan payloads completos o mensajes de excepciones.

## Conciliación

Se precargan PrintingDevice y sus detecciones actuales con dos consultas SQL.
La comparación posterior no hace SQL por hallazgo. Se consulta también identidad
de registros inactivos para evitar tratarlos como dispositivos nuevos.

La evidencia es serial exacto y/o MAC normalizada exacta. Solo se indexan MACs de
detecciones actuales; no se reutilizan automáticamente MACs históricas obsoletas.
IP, marca, modelo, hostname, sede y sector nunca sirven como identidad.

| Clasificación | Significado / acción |
|---|---|
| MATCHED | Identidad única, misma IP; ninguna escritura |
| IP_CHANGED | Identidad única, IP diferente y libre; se puede aplicar |
| NEW_DEVICE | Identidad soportada sin registro correspondiente; revisión, nunca alta automática |
| AMBIGUOUS | Identificador duplicado localmente/en red, varias detecciones actuales o varios hallazgos para un registro; revisión |
| UNIDENTIFIED | Host accesible sin identidad soportada suficiente; revisión |
| CONFLICT | Serial/MAC contradictorios, IP ocupada, registro inactivo, fabricante contradictorio o evidencia incompleta; revisión |

Un serial conocido no permite ignorar una MAC contradictoria. Si el serial
coincide con un equipo y la MAC con otro equipo, se bloquea la aplicación.
La búsqueda de duplicados considera todos los hallazgos de todas las subredes de
la ejecución. Una subred incompleta no aporta cambios aplicables.

## Aplicación y compatibilidad

Solo --apply aplica IP_CHANGED. Sin esa opción, incluida --dry-run, no se escribe
en la base de datos, aunque siempre se genera un reporte CSV.

`apply_discovery_change()` captura IP, serial y detecciones antes del discovery;
dentro de transaction.atomic vuelve a bloquear/releer registros y detecciones.
Repite la conciliación con los datos actuales y verifica ámbito autorizado,
evidencia única, ausencia de cambios concurrentes y disponibilidad de la IP.
Si cambia la identidad o la detección, aborta sin escribir.

Se reutiliza `_write_ip_change()` extraído de recovery_application.py: cierra la
detección anterior si existe, crea una detección con LEXMARK_EWS_DISCOVERY,
actualiza únicamente IP y campos de conectividad y deja estado UNKNOWN. Conserva
last_online_at y las fechas históricas de comprobación. Si existe serial exacto
pero nunca hubo detección, crea la primera detección solo para ese PrintingDevice
ya existente. No rellena automáticamente serial, modelo o ubicación locales.

El bloqueo ordenado de PrintingDevice se comparte con la recuperación existente
para serializar sus aplicaciones de IP. No se mantiene durante HTTP. Si falla
la escritura del historial o del dispositivo, se revierte toda la operación.
La extracción de la función compartida conserva el comportamiento de los comandos
de recuperación; sus tests de compatibilidad se ejecutan junto a discovery.

No se crea ActivityLog por host. La detección histórica es el registro del cambio
real de IP. Los cambios de identidad desde otras herramientas administrativas
deben respetar las mismas reglas de asignación de IP.

## Comando y CSV

```powershell
python manage.py discover_printers_network --site VILLA_ELISA --dry-run --timeout 1
python manage.py discover_printers_network --site OFICINA_CENTRAL --dry-run --timeout 1
python manage.py discover_printers_network --all-authorized --dry-run --timeout 1
python manage.py discover_printers_network --subnet 10.11.42.0/24 --subnet 10.22.42.0/24 --dry-run --workers 8 --output C:\Reportes\printing.csv
```

Los selectores --site, --subnet y --all-authorized son excluyentes. --subnet se
puede repetir, pero solo admite entradas del mapa. --apply y --dry-run también
son excluyentes. Ninguno de estos ejemplos se ejecutó contra una red real.

Sin --output se crea un CSV con fecha UTC y sufijo único bajo
`~/NovaDeskProReports/Printing`, fuera del repositorio en esta instalación.
Se reserva el archivo antes del discovery/aplicación. Nunca sobrescribe un
archivo existente salvo --overwrite explícito. El CSV UTF-8 con BOM contiene los
campos requeridos de sede, sector, red, identidad, clasificación, registro local
y acción, además de motivo, error seguro y resultado de aplicación.
Las celdas que podrían ejecutarse como fórmulas al abrir en Excel se escapan.

Si una aplicación se aborta por cambios concurrentes, conserva la clasificación
del discovery y señala ACCION_PROPUESTA=ABORTED, MOTIVO y ACTUALIZADO=False.
El resumen muestra redes/hosts consultados, impresoras identificadas, las seis
clasificaciones, actualizaciones y errores. Fallos ordinarios de hosts que no
responden no generan un error por cada IP. Los CSV son reportes de revisión, no
instrucciones automáticas de alta o cambios institucionales.
