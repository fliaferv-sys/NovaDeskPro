# Contexto técnico revisado en Tickets

`apps.integrations.technical_context.resolve_technical_context` sigue siendo el
servicio de lectura compartido. Reutiliza GLPIClient (GET-only), búsqueda por IP,
identidad institucional consolidada y activos locales por serie exacta. Separa
solicitante local, identidad institucional, usuario detectado y custodio local.
No escribe en GLPI, RR.HH., AD, User o Asset.

## Consulta y revisión

El panel aparece solo en alta de escritorio para ADMIN, TECHNICIAN o superusuario.
No consulta al abrir: exige IP/hostname y un clic. CLIENT y edición mantienen el
flujo existente; en móvil el panel está oculto y no inicia peticiones.

La ficha ofrece secciones compactas y candidatos seleccionables. Ningún equipo,
persona o activo se selecciona automáticamente, incluso si solo existe uno.
El botón «Seleccionar equipo e incluir contexto revisado» confirma explícitamente
el equipo y las opciones elegidas. «Quitar contexto» elimina la selección.
No modifica description, asset, requester, responsable ni asignación.

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
Los campos no disponibles permanecen null; no se inventa legajo ni vínculo.

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

Pruebas: creación real con/sin snapshot, firma/actor/cambios, candidatos múltiples,
fallos de fuentes, permisos, separación de personas, whitelist, ausencia de escrituras
en fuentes/activos y JS sin consulta inicial ni alteración de descripción/custodia.
