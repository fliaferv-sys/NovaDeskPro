# Contexto técnico revisado en Tickets

`apps.integrations.technical_context.resolve_technical_context` sigue siendo el
servicio de lectura compartido. Reutiliza GLPIClient (GET-only), búsqueda por IP,
identidad institucional consolidada y activos locales por serie exacta. Separa
solicitante local, identidad institucional, usuario detectado y custodio local.
No escribe en GLPI, RR.HH., AD, User o Asset.

## Consulta y revisión

Al abrir el alta, ADMIN/TECHNICIAN reciben una consulta automática por solicitante.
La búsqueda manual IP/hostname permanece en «Consulta técnica avanzada», plegada.
CLIENT recibe solo su ficha sencilla y el nombre del equipo seguro, incluso en
móvil; no recibe candidatos ajenos, IP, MAC, GLPI ID ni confianza técnica.
La ficha avanzada de escritorio sigue oculta en móvil. Edición no inicia consultas.

La ficha ofrece secciones compactas y candidatos seleccionables. Se prepara
automáticamente solo un equipo único con una relación local inequívoca mediante
Asset.assigned_user, o una coincidencia única de serie con ese activo. El contacto
GLPI aislado continúa PROBABLE y exige revisión explícita por ADMIN/TECHNICIAN.
La confianza de asociación local CONFIRMADA se almacena separada de la confianza
de red/inventario: nunca se promueve PROBABLE a CONFIRMADA para la red.
El botón «Seleccionar equipo e incluir contexto revisado» confirma explícitamente
el equipo y las opciones elegidas. «Quitar contexto» elimina la selección.
No modifica description, asset, requester, responsable ni asignación.
«Quitar contexto» impide también la asociación automática al enviar.

`resolve_automatic_context` reutiliza resolve_technical_context y añade activos
ya asignados al solicitante, sin inferir personas por nombre. Múltiples dispositivos
con la misma serie no se eligen. Si existen varios equipos, CLIENT continúa sin
snapshot; ADMIN/TECHNICIAN pueden seleccionar. Ningún resultado implica custodia nueva.

El endpoint propio `/tickets/contexto-automatico/` requiere autenticación y rol
ADMIN/TECHNICIAN/CLIENT (o superusuario). CLIENT solo recibe su nombre y el del equipo
único asociable, la selección segura y su referencia firmada. El endpoint manual
conserva exactamente los permisos previos; CLIENT no puede consultarlo.

El resultado automático se cachea 60 segundos por usuario en la caché configurada.
La creación siempre resuelve otra vez, sin caché de interacción. Si no llega JS,
el backend busca un equipo inequívoco; si recibe una selección firmada, cualquier
cambio del resultado descarta el snapshot. No acepta nombres, correos o datos del
equipo enviados por JS como evidencia. Metadata distingue AUTOMATICA de REVISADA.

El endpoint autenticado `/tickets/contexto-tecnico/` valida IPv4/hostname, no cachea
la respuesta y emite una referencia firmada que contiene exclusivamente la consulta,
el identificador del actor y un hash del resultado. No contiene el resultado GLPI
ni datos personales completos. Caduca en 30 minutos.

Al crear, el servidor verifica firma, actor y caducidad, vuelve a resolver con el
usuario autenticado y compara el resultado con el hash revisado. Verifica índices
explícitos y construye el JSON con whitelist, sin aceptar snapshots enviados por JS.
Si cambian los datos, hay un índice inválido o falla una fuente, crea el ticket sin
snapshot y avisa. Este mecanismo prioriza evitar asociaciones no revisadas; incluso
un cambio de orden de candidatos puede exigir repetir la consulta.

## Snapshot histórico

Migración `tickets.0022_ticket_technical_context_snapshot`: único JSONField opcional,
`null=True`, `blank=True`, `editable=False`. Aplicar mediante el procedimiento normal
de despliegue antes de utilizar el código; no hay backfill de tickets históricos.

Estructura: `requester_identity`, `detected_user`, `device`, `novadesk_asset`, `metadata`.
Personas: nombre, username, correo, teléfono, cargo, dependencia, ubicación, legajo,
vínculo, fuentes y confianza cuando el resolver los proporciona. Equipo: tipo,
nombre, hostname, IP, MAC, serie, ID GLPI, ubicación, fuentes y confianza. Activo:
ID/código y responsable observado, sin alterar el FK asset del ticket. Metadata:
actor revisor, fecha de validación/creación, versión y advertencias sanitizadas.
Los campos no disponibles permanecen null; no se inventa legajo ni vínculo. La
whitelist específica de Tickets permite legajo/vínculo sin ampliar la consulta por IP.

El detalle muestra un desplegable únicamente cuando hay snapshot. No lo refresca
contra las fuentes. La edición normal no incluye el campo ni lo recalcula.
`requester` permanece el FK local para permisos, notificaciones y autorizaciones.

Se retiró el botón que añadía `NOVADESK_TECHNICAL_CONTEXT_V1` a description. Los textos
históricos existentes se conservan intactos; no hay limpieza automática.

## Límites

La búsqueda por hostname consulta Computer.name, sin afirmar que sea FQDN/DNS.
No escanea la red. Contacto GLPI, usuario detectado y responsable NovaDesk no son
equivalentes. Las fuentes pueden no aportar teléfono, legajo o vínculo. La revisión
requiere un equipo seleccionado; una consulta sin equipo no genera snapshot.
El snapshot se mantiene durante edición normal, pero no constituye almacenamiento
inmutable frente a administradores de base de datos o actualizaciones ORM directas.

Rendimiento: normalmente una búsqueda filtrada Computer.contact y otra
Printer.contact (más paginación y apertura/cierre de sesión GLPI). No se descargan
inventarios ni colecciones de red. Las consultas institucionales exactas se realizan
para username/correo del solicitante y cada contacto distinto; se reutilizan los
contactos repetidos durante la misma resolución. Los activos por serie se consultan
en lote y la custodia del solicitante en una consulta adicional. Cada envío repite
la resolución para revalidar; repetir la carga automática dentro de 60 segundos
no repite fuentes externas. Un proceso de caché local no comparte resultados entre
workers; la configuración de producción puede usar su backend de caché habitual.

La búsqueda por contacto no recorre users_id como vía inversa y no obtiene IP/MAC
si no estaban en la respuesta disponible. Un solo contacto sin activo local no
se asocia automáticamente: se presenta para revisión al técnico. No se inventan
datos de red ni se consulta NetworkPort/NetworkName/IPAddress masivamente.

Pruebas: creación real con/sin snapshot, firma/actor/cambios, candidatos múltiples,
fallos de fuentes, permisos, separación de personas, whitelist, ausencia de escrituras
en fuentes/activos y JS con detección automática y sin alteración de descripción/custodia.
