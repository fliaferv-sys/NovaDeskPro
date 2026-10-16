# Recuperación de IP Lexmark: descubrimiento y aplicación

La recuperación se ejecuta por comandos separados. No cambia el monitor TCP,
su periodicidad, dashboard, templates ni otros módulos. No se instala ningún job.
No se realizaron pruebas contra impresoras reales ni cambios en producción.

## Recuperación individual

```powershell
C:\NovaDeskPro\venv\Scripts\python.exe manage.py recover_printer_ip --photocopier-id 21 --subnet 10.11.42.0/24 --timeout 1 --dry-run
C:\NovaDeskPro\venv\Scripts\python.exe manage.py recover_printer_ip --photocopier-id 21 --subnet 10.11.42.0/24 --timeout 1 --apply
```

También acepta --id o --serial, mutuamente excluyentes. La subred IPv4 /24 debe
ser explícita y canónica; se valida con ip_network(strict=True). El comando sigue
siendo read-only sin --apply. --apply y --dry-run no pueden combinarse.
La ejecución individual no está limitada por el cooldown automático.

El descubrimiento individual sigue siendo secuencial y conserva el timeout
predeterminado de 0,4 segundos. Puede usarse --timeout 1 para el caso validado;
el máximo admitido es tres segundos. Se recorren las 254 direcciones utilizables,
sin network/broadcast, incluso después de una coincidencia: hay que descartar que
una misma MAC aparezca en dos IPs. source continúa siendo LEXMARK_EWS.

Los resultados read-only conservan sus campos; se agrega match_count para que
la aplicación exija una coincidencia única explícita. Un host HTTP genérico no
es evidencia de identidad. responsive_hosts cuenta identidades EWS válidas.

## Aplicación atómica

Antes del descubrimiento se captura IP, MAC y todos los campos de la única
detección actual de la impresora activa. La evidencia debe ser FOUND, sin error,
con recorrido completo de 254 hosts y match_count=1. La MAC encontrada debe
coincidir exactamente con la esperada. La IP debe ser IPv4 válida, utilizable y
pertenecer al /24 solicitado. No se acepta hostname, marca ni modelo como prueba.

Dentro de transaction.atomic se bloquean las filas de PrintingDevice en orden
estable y se relee/bloquea la detección actual. El bloqueo de dispositivos
serializa las aplicaciones de recuperación que podrían proponer la misma IP
libre para dos impresoras distintas. No se mantienen bloqueos durante HTTP.
Se vuelve a comprobar actividad, IP de inicio, detección completa, MAC y ausencia
de otra impresora activa con la IP propuesta. La recuperación masiva también
revalida su reserva de intento y elegibilidad OFFLINE.

Si algo cambió, la aplicación no escribe. Si la IP es la misma, tampoco escribe
historial ni campos de conectividad. Si se cambia:

1. La detección anterior pasa a is_current=False, conservando todo su contenido.
2. Se crea una detección actual con IP nueva, MAC exacta, origen
   LEXMARK_EWS_AUTO_RECOVERY y una nota breve con IP anterior/nueva y motivo.
3. Se actualiza PrintingDevice.ip_address y se deja connection_status=UNKNOWN,
   monitored_ip=None, monitor_method="", monitor_error="" y monitor_evidence={}.
4. Se conserva last_online_at y last_checked_at como historia; se actualiza
   last_status_change_at cuando corresponde y updated_at.

Si falla cualquier escritura, se revierte todo, incluida la detección anterior.
effective_status() muestra UNKNOWN hasta que el monitor TCP mida la nueva IP.
El historial de detecciones es la auditoría de cada cambio; Printing no tenía
una integración propia de ActivityLog aplicable a estos comandos. No se crean
eventos por host ni se guardan respuestas JSON, credenciales o excepciones.

## Proceso masivo separado

```powershell
C:\NovaDeskPro\venv\Scripts\python.exe manage.py recover_offline_printers --dry-run --timeout 1 --limit 20
C:\NovaDeskPro\venv\Scripts\python.exe manage.py recover_offline_printers --apply --timeout 1 --limit 20
```

Sin --apply, también es read-only. El límite predeterminado es 20 impresoras
elegibles, no 20 subredes. Solo selecciona impresoras activas, supports_network=True,
connection_status=OFFLINE, IP válida y una sola detección actual con MAC válida.
Excluye NO_IP, DUPLICATE_IP, duplicación real de IP incluso con registros
inactivos y dispositivos dentro del cooldown.

Deriva únicamente el /24 de cada IP registrada. Agrupa los candidatos y escanea
cada subred una sola vez por ejecución, con ocho workers HTTP como máximo y
timeout predeterminado de un segundo por host. No se accede a la base de datos
desde los threads ni por cada host. El mapa MAC -> lista de IP/hostname conserva
duplicados; dos direcciones con la misma MAC producen AMBIGUOUS.

Un error inesperado o recorrido incompleto invalida la subred entera: no se
aplica ninguna recuperación de ese grupo. Los timeouts/errores HTTP ordinarios
son respuestas no utilizables, esperables durante el descubrimiento. Una IP
propuesta ya asignada a otra impresora activa se informa como conflicto.
La comparación de identidad sigue usando el EWS read-only existente, sin
redirecciones, proxies, POST, SNMP o modificaciones sobre impresoras.

## Cooldown y migración

La migración 0020 agrega exclusivamente
PrintingDevice.last_recovery_attempt_at: DateTimeField nullable, blank y
editable=False. No contiene backfill, cambios destructivos ni alteración de
datos existentes. Se revisó manualmente; se aplicó solo en la DB de tests.

Hace falta registrar también intentos NOT_FOUND, AMBIGUOUS y fallidos. El historial
de detecciones no sirve para ello sin inventar detecciones o alterar auditoría.
Por eso se utiliza este único campo nullable, en lugar de una caché de proceso
que no coordinaría ejecuciones distintas.

Con --apply, cada intento automático se reserva bajo bloqueo antes de escanear;
no puede volver a reservarse durante 30 minutos. Incluso si no hay cambio de IP
o falla el descubrimiento, queda la fecha del intento para evitar repeticiones.
Esta es la única escritura de un intento que no termina en cambio de IP; no
genera detecciones ni cambia conectividad. Si el cambio atómico falla, su historial
se revierte y se conserva la reserva previa. Sin --apply no se reservan intentos.

El mecanismo coordina ejecuciones automáticas sobre la misma impresora. El
programador externo debe además impedir instancias solapadas del lote para no
repetir escaneos de una misma subred para distintos grupos de dispositivos.
Los comandos no se programan ni activan automáticamente en esta entrega.

## Límites

La identidad depende de la MAC reportada por EWS y la MAC guardada. No es una
prueba criptográfica frente a un host que suplante deliberadamente ambas.
Las verificaciones transaccionales protegen las escrituras de recuperación;
las operaciones administrativas externas deben respetar los mismos controles de
asignación de IP. No se agrega una restricción unique global, dado que el sistema
admite y detecta registros históricos con IP duplicada.
