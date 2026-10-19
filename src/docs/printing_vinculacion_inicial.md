# Vinculación inicial de MAC/UAA

Operación explícita sobre impresoras **existentes**. No es recuperación de IP ni
configuración física. No crea PrintingDevice ni cambia sus campos, incluyendo
serial, IP, monitoreo, sede y ubicación institucional. No requiere migraciones.

## Operación

Primero revisar el informe (sin escrituras en la base):

```powershell
C:\NovaDeskPro\venv\Scripts\python.exe manage.py bind_printer_identity --site VILLA_ELISA --dry-run --output C:\ruta-autorizada\vinculacion-revision.csv
```

Después de revisar, aplicar explícitamente con una nueva exploración y un nuevo
informe; no se importa ni se confía en un CSV anterior:

```powershell
C:\NovaDeskPro\venv\Scripts\python.exe manage.py bind_printer_identity --site VILLA_ELISA --apply-bindings --output C:\ruta-autorizada\vinculacion-aplicacion.csv
```

Ejemplos documentales: no fueron ejecutados contra impresoras reales durante la
implementación. También admite `--subnet` repetible y `--all-authorized`, siempre
limitados al mapa existente. Timeout predeterminado 1 s, máximo 3 s; workers máximo
8. Sin opción de aplicación, el modo predeterminado es solo informe. `--apply`
no pertenece a este comando. Los CSV existentes requieren `--overwrite`.

Reutiliza discovery, LexmarkEWSAdapter y el lector ASN.1/BER SNMPv2c existentes.
Requiere la comunidad configurada mediante PRINTING_SNMP_COMMUNITY; sin ella no
se vincula ninguna MAC. No incorpora dependencias nuevas respecto del lector SNMP.

## Condiciones de aceptación

- Serial físico SNMP válido, exacto y único entre todos los registros, incluso
  inactivos; equipo activo con soporte de red.
- MAC/UAA válida obtenida de EthernetUAA, con continuidad EWS → SNMP → EWS.
- Escaneo completo y sin seriales ni MAC repetidos entre sus hallazgos.
- MAC no asociada a otro equipo, incluso en detecciones históricas.
- Ninguna MAC histórica diferente, ninguna detección vigente incompatible ni
  IP observada asignada a otro registro.
- Una asociación ya existente no se reemplaza ni se duplica. Una MAC histórica
  igual también exige revisión para cualquier reactivación: no es vinculación inicial.

Antes de escribir, repite la identificación física completa en la misma IP y
exige el mismo serial y MAC. Después, en una transacción breve, bloquea inventario
y detecciones y compara todos los campos con la captura anterior al escaneo.
Cualquier cambio concurrente aborta. PostgreSQL utiliza además LOCK TABLE SHARE
ROW EXCLUSIVE para impedir inserciones fantasma de seriales o MAC durante la
comprobación. SQLite no implementa SELECT FOR UPDATE; su bloqueo de escritura
y fallo de actualización concurrente impiden aceptar una captura obsoleta. No se
hacen consultas de red dentro de la transacción. La prueba física expira en 10 s,
incluido el tiempo de espera de los bloqueos.

Solo se cierran detecciones vigentes sin MAC y se crea una nueva detección
vigente; se conservan todas las filas históricas y sus datos. Las notas nuevas
contienen JSON con ID interno, número de fotocopiadora, serial físico, MAC, IP
observada, fecha de validación, origen y resultado. No contienen comunidad SNMP,
contraseñas ni excepciones de red. La captura base del lote avanza exclusivamente
por las escrituras propias bajo bloqueo, nunca absorbiendo cambios externos.

## Resultados y separación de responsabilidades

El CSV distingue PENDING_INITIAL_BINDING, ALREADY_ASSOCIATED, BLOCKED y BOUND,
incluye motivos, estado SNMP y origen del serial. Los errores son códigos seguros.
Los valores CSV se protegen frente a fórmulas. Los conflictos bloquean la fila;
un escaneo incompleto bloquea todas las asociaciones del lote. Una falla posterior
no deshace vinculaciones anteriores ya confirmadas: cada asociación es atómica.

El discovery y su `--apply` mantienen sus reglas: MATCHED no registra una MAC;
IP_CHANGED solo puede actualizar el inventario con una MAC previamente confirmada
y la revalidación correspondiente. Vincular puede dejar detected_ip diferente de
PrintingDevice.ip_address: es deliberado. Una posterior recuperación conciliará la
IP del inventario por separado. No se modifica monitoreo ni tareas programadas.

Todas las consultas físicas son GET HTTP y GET SNMP. No hay POST, SET ni cambios
de IP, gateway, máscara o DNS. La continuidad de lecturas reduce el riesgo de
mezclar equipos por reasignación de IP, pero estos protocolos no autentican
criptográficamente el hardware ni inmovilizan DHCP. No sustituye revisión humana
ante dispositivos que falsifiquen identificadores o cambios rápidos de ida y vuelta.
