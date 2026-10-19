# Serial SNMPv2c en discovery de Printing

## Alcance

El lector independiente `apps/printing/snmp_identity.py` obtiene solamente
`1.3.6.1.2.1.43.5.1.1.17.1` mediante un GetRequest-PDU SNMPv2c a UDP/161.
No implementa SET, GETNEXT, walk, búsqueda de IPs, lectura de MAC ni escrituras
en base de datos. No utiliza expresiones regulares sobre respuestas binarias.

LexmarkEWSAdapter lo invoca exclusivamente después de recibir EthernetUAA y
SetHostname válidos del EWS y descartar contradicciones de fabricante.
La MAC se conserva exactamente del resultado normalizado de EthernetUAA.
DeviceInformation sigue aportando sus datos cuando están disponibles.

El serial SNMP válido enriquece el hallazgo con `serial_source=SNMPV2C`; el
origen principal sigue siendo LEXMARK_EWS, conservando la compatibilidad del
discovery y de su aplicación existente. Si EWS y SNMP dan seriales distintos,
se devuelve SERIAL_SOURCE_CONFLICT y no se aplica ningún cambio.

Después de obtener un serial se repite EWS y se exige que la MAC siga siendo la
misma. Si cambia o desaparece, se descarta el serial combinado y se informa
NETWORK_IDENTITY_CHANGED o NETWORK_IDENTITY_UNVERIFIED. identity_verified indica
continuidad de las lecturas realizadas, no autorización de escritura por sí sola.

Ante timeout, error de agente, paquete inválido o falta de configuración,
no se inventa serial: se conserva la información EWS previa. `snmp_error`
contiene exclusivamente un código seguro; nunca el paquete ni la comunidad.

## Configuración

| Variable de entorno | Valor predeterminado / límites |
|---|---|
| PRINTING_SNMP_COMMUNITY | Vacía: SNMP deshabilitado; configurar una comunidad de solo lectura mediante el mecanismo seguro del entorno |
| PRINTING_SNMP_TIMEOUT_SECONDS | 0.5 segundos; mayor que cero y máximo tres segundos |
| PRINTING_SNMP_RETRIES | 0; únicamente cero o un reintento |

La comunidad se expone internamente como el setting
`PRINTING_SNMP_COMMUNITY_SECRET`, cuyo nombre Django oculta en reportes técnicos.
También se marcan como sensibles las variables con comunidad/paquetes en las
funciones del lector. No hay comunidad de fábrica, pública o hardcodeada como
fallback. No se leen comunidades de otras impresoras por coincidencia de IP.
No introducir el valor real en código, archivos de Git, CSV o logs.

El timeout efectivo es el menor entre el presupuesto del discovery y el timeout
SNMP configurado. Solo se reintenta al vencer la espera de una respuesta, con
máximo dos envíos; errores de protocolo o del agente no se reintentan.
La concurrencia continúa limitada por los workers existentes del discovery.
No se consulta SNMP en GET de la interfaz ni desde el monitor TCP o recuperadores.

SNMPv2c no cifra su comunidad. El agente debe tener una comunidad de solo lectura
ya autorizada para el origen correspondiente. Esta implementación no modifica
impresoras, IIS, Fortinet, jobs ni configuraciones de MESATI/producción.

## Validación formal

Se utilizan el esquema SNMP ASN.1 de `pysnmp.proto.api.v2c` y el codec BER de
`pyasn1`, no un extractor de texto. Antes de decodificar se validan límites de
framing: máximo 4096 bytes, profundidad y cantidad de elementos acotadas,
longitudes definidas, ausencia de truncamiento/datos sobrantes y codificación
primitiva de tipos simples. Se admite BER definite-long, incluso con longitud
no mínima, como permite SNMP; se rechazan longitudes indefinidas.

Después de decodificar se exigen:

- versión wire 1 (SNMPv2c) y comunidad idéntica a la configurada;
- Response-PDU y request-id idéntico al generado aleatoriamente;
- error-status y error-index iguales a cero;
- exactamente un varbind con el OID solicitado;
- valor de tipo OCTET STRING, no excepciones noSuchObject/noSuchInstance/endOfMibView;
- serial ASCII imprimible, no vacío, sin controles y de hasta 150 bytes,
  compatible con PrintingDevice.serial_number; sin truncarlo ni extraer subcadenas.

El socket UDP está conectado únicamente a la IP IPv4 validada y al puerto 161,
para que el sistema operativo filtre datagramas de otros peers. No hay DNS,
redirecciones, ampliación de subred ni cambios de destino durante los reintentos.
Las excepciones de codecs/transporte se convierten en códigos de aplicación sin
mensajes de librerías, que podrían contener datos del paquete.

Referencias: [RFC 3416](https://www.rfc-editor.org/rfc/rfc3416.html),
[RFC 3417, sección 8](https://www.rfc-editor.org/rfc/rfc3417.html#section-8),
[Printer MIB v2, RFC 3805](https://www.rfc-editor.org/rfc/rfc3805.html).

## Conciliación y aplicación

Un serial físico exacto y único puede reconocer una impresora existente aunque
no tuviera MAC guardada. Con la misma IP, el resultado es MATCHED y no se escribe
la MAC observada. La IP por sí sola continúa sin ser evidencia de identidad.

Se mantienen las comprobaciones de serial/MAC duplicados en base y en la red,
serial/MAC apuntando a registros distintos, MAC guardada diferente, registro
inactivo, IP ocupada, escaneo incompleto y cambios concurrentes.

El discovery no incorpora enrolamiento automático de MAC. --apply exige siempre
serial ya registrado y una única detección actual con MAC confirmada. Una
identidad local incompleta bloquea la aplicación, incluso si el hallazgo pudo
clasificarse por uno de sus identificadores para revisión.

La vinculación inicial explícita se realiza por separado con
`bind_printer_identity --apply-bindings`; véase
[procedimiento y garantías](printing_vinculacion_inicial.md). No relaja --apply.

Inmediatamente antes de aplicar se vuelve a consultar exclusivamente la IP
propuesta, con la misma secuencia EWS/serial/EWS. La pareja debe coincidir con los
identificadores locales y el hallazgo original. Se hace sin bloqueos SQL; luego
la transacción comprueba de nuevo el inventario, la detección actual, unicidad,
contradicciones y ocupación de IP. Si la lectura tiene más de diez segundos al
llegar a la escritura, se aborta. Una IP distinta puede actualizarse solo dentro
de NovaDesk; nunca se envían SNMP SET, HTTP POST ni acciones de configuración.

Las consultas de red y una transacción SQL no pueden inmovilizar una asignación
DHCP externa. La protección combina continuidad de lecturas, coincidencia de
ambos identificadores locales inmutables y revalidación reciente. No equivale a
un bloqueo físico de la impresora ni a autenticación criptográfica de identidad.
Se bloquea el caso de mezcla MAC-A/serial-B con serial local ausente.

El CSV incorpora ESTADO_SNMP, ERROR_SNMP y ORIGEN_SERIAL del descubrimiento.
Si la revalidación previa a aplicar falla, ACCION_PROPUESTA=ABORTED y MOTIVO
indica el código seguro de rechazo. Ningún campo incluye la comunidad.

Nunca se crea PrintingDevice ni se altera su serial, marca, modelo o ubicación
automáticamente. Se refuerza únicamente la aplicación de discovery en
recovery_application.py; no cambian apply_recovery, el monitor TCP, comandos de
recuperación de IP, tareas programadas o interfaces de usuario.

## Dependencias y verificación

En PC601 desarrollo se verificaron mediante pip show las instalaciones existentes:

- pysnmp 7.1.30;
- pyasn1 0.6.4.

`apps/printing/requirements.txt` fija esa combinación de versiones probada.
El transporte utiliza socket de la biblioteca estándar; no requiere ejecutables
SNMP, compiladores, SDK nativo ni procesos externos. Las dependencias ASN.1 se
importan de forma diferida: sin comunidad configurada no se cargan ni se consulta
SNMP. Si faltan con SNMP habilitado se informa DEPENDENCY_UNAVAILABLE y se
conserva el discovery EWS.

No se instaló ningún paquete, no se ejecutó ninguna consulta de red real y no se
modificó producción. Las respuestas UDP y HTTP se simulan en los tests, incluida
una prueba integrada lector BER -> adaptador -> conciliación de serial existente.
No hay migraciones.
