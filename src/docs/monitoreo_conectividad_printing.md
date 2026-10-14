# Conectividad de PrintingDevice

## Auditoría y decisión

El dashboard, el resumen por modelo y los filtros de Printing consultaban
`Asset.connection_status`. Sin Asset, la impresora quedaba UNKNOWN; por eso los
79 equipos tercerizados podían aparecer desconocidos independientemente de su IP.
El detalle también presentaba estado/IP del Asset.

`apps.monitoring` recibe heartbeats de agentes mediante POST autenticado por
token. DeviceHeartbeat requiere Asset y considera reciente una comunicación de
los últimos tres minutos. No es un sondeador de impresoras. Asset mantiene un
estado propio que también se puede editar/importar; no aporta evidencia TCP para
PrintingDevice.

Printing ya cuenta con IP operativa IPv4, network_port (9100 por defecto),
snmp_enabled y snmp_community. PrintingDeviceNetworkDetection registra evidencia
de red manual/externa (IP, MAC, switch, VLAN, origen); no ejecuta SNMP.
Los comandos existentes importan/concilian datos: no monitorean conectividad.
Las integraciones GLPI consultan inventario por HTTP; sus IPs pueden ser históricas.
No se encontró un cliente SNMP/ICMP, un sondeador TCP ni scheduler reutilizable.

Se usa socket TCP de la biblioteca estándar, sin dependencias adicionales.
SNMP/ICMP no se ejecutan: los campos SNMP existentes se conservan, pero no bastan
para implementar un cliente confiable. GLPI no participa en este monitoreo.

## Estado y evidencia

PrintingDevice conserva sus FK e IP existentes. La migración 0019 agrega:

| Campo | Propósito / inicialización |
|---|---|
| connection_status | ONLINE/OFFLINE/UNKNOWN; inicial UNKNOWN |
| monitored_ip | IPv4 utilizada en la medición; nullable |
| last_checked_at | Inicio de la última comprobación; nullable |
| last_online_at | Última comprobación exitosa; nullable |
| last_status_change_at | Última transición del estado persistido; nullable |
| monitor_method | TCP, o vacío si no se pudo sondear |
| monitor_error | Código seguro, sin mensajes de excepciones |
| monitor_evidence | JSON: puerto configurado, puertos intentados y alcance observado |

Todos los campos nuevos son editable=False. La migración contiene exclusivamente
ocho AddField: no RunPython, eliminación, reemplazo de IP ni backfill de estados
desde Asset. Los datos existentes conservan su validez. Se revisó manualmente la
migración; solo se aplicó dentro de la base de datos de tests.

ONLINE significa conexión TCP reciente exitosa al puerto configurado o a 443/80.
Se intenta primero network_port; si no responde, 443 y luego 80, sin repetir
puertos. La evidencia distingue host alcanzable de puerto de impresión accesible.
No se envía tráfico de aplicación, trabajos de impresión ni credenciales SNMP.
Un puerto abierto no garantiza que la impresora pueda completar un trabajo.

OFFLINE significa que una IP válida y no conflictiva no respondió en ninguno de
esos puertos dentro del timeout. Es ausencia de respuesta TCP desde el servidor
que ejecuta el comando: puede deberse a firewall, ruta, servicio o equipo apagado.

UNKNOWN significa sin IP, nunca comprobada, resultado inválido, IP conflictiva,
configuración de red inválida, fallo interno del sondeo o medición vencida. Se
rechazan IPv6, hostnames, rangos, loopback, multicast, link-local, dirección
indeterminada y broadcast global. Se contemplan IPs duplicadas incluso en
registros inactivos: requieren revisión manual.

La lectura muestra UNKNOWN si cambió la IP/puerto/capacidad de red después de la
medición, si existe duplicación o si la medición tiene más de 900 segundos.
No modifica el último estado persistido para hacerlo: dashboard, listado y
detalle solo leen. Asset.connection_status no participa.

Los GET no invocan sockets ni GLPI. La detección de duplicados se incluye mediante
Exists en la consulta de dispositivos, evitando consultas por fila.

## Ejecución y piloto

Desde el checkout autorizado, usando el entorno y base de staging:

```powershell
C:\NovaDeskPro\venv\Scripts\python.exe manage.py monitor_printers --serial 701824340HW75 --expected-ip 10.5.42.41 --dry-run
C:\NovaDeskPro\venv\Scripts\python.exe manage.py monitor_printers --id UUID --dry-run
C:\NovaDeskPro\venv\Scripts\python.exe manage.py monitor_printers --ip 10.5.42.41 --dry-run
```

Dry-run **realiza conexiones TCP**, pero no escribe ni crea ActivityLog. No se
ejecutó el piloto real como parte de esta implementación.

Para HW75 (Lexmark MX622ADHE), primero revisar serial, IP operativa registrada,
evidencia física y posibles duplicados. --expected-ip detiene el comando antes
del sondeo si la IP registrada difiere de la observada. No sustituye la IP.
Si el serial es ambiguo, se debe seleccionar por UUID. Una IP compartida produce
UNKNOWN/DUPLICATE_IP sin conexiones; seleccionar por serial no evita el control
global de duplicados. No se afirma la identidad física a partir de TCP.

Después de resolver manualmente inconsistencias, revisar el resultado dry-run y
repetir el mismo selector sin --dry-run para persistir únicamente ese equipo.
Comprobar detalle, timestamps, filtros y resumen antes de habilitar --all.

```powershell
C:\NovaDeskPro\venv\Scripts\python.exe manage.py monitor_printers --all --dry-run
C:\NovaDeskPro\venv\Scripts\python.exe manage.py monitor_printers --all
```

Sin selector ni --all explícito, el comando se rechaza. Solo se conectan las IPs
exactas registradas de PrintingDevice activo; no se enumeran rangos ni DNS.
Un fallo de sondeo no interrumpe los siguientes equipos. Antes de guardar se
verifica que la configuración no cambió y que no haya una medición más reciente.
Se vuelven a verificar duplicados. No se cambian Asset, IP operativa o permisos.
Las mediciones se guardan en los campos operativos, sin ActivityLog por sondeo.

## Periodicidad y límites

Programar `monitor_printers --all` cada cinco minutos desde el Programador de
tareas de Windows (o cron en Linux), con directorio de trabajo del checkout,
entorno correcto y una cuenta del sistema con acceso a DB y a esas IPs. Configurar
el programador para no iniciar otra instancia si la anterior sigue ejecutándose.
Esta implementación no instala ni activa tareas ni accede a producción.

`PRINTING_MONITOR_TIMEOUT_SECONDS`: variable de entorno, default 1 segundo por
puerto (máximo admitido 10). También existe --timeout para el piloto.
`PRINTING_MONITOR_MAX_AGE_SECONDS`: variable de entorno, default 900 segundos.
Mantener TTL mayor que el intervalo de ejecución y el tiempo del lote.

La ejecución es secuencial: concurrencia máxima uno. Para 79 impresoras sin
respuesta, el presupuesto de espera TCP es aproximadamente 237 segundos con
timeout de 1 segundo, más DB y overhead del sistema. Ajustar intervalo/timeout
según el piloto; no bloquear un worker web. Los firewalls pueden impedir TCP
aunque el dispositivo responda a otro protocolo. Una IP histórica que no esté
duplicada puede apuntar a otro host: la validación física sigue siendo necesaria.
