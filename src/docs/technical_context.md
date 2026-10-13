# Contexto técnico reutilizable y primera integración Tickets

Servicio: `apps.integrations.technical_context.resolve_technical_context`.
Entradas opcionales: requester (actor local), username/email, identity (solo
claves de búsqueda revalidadas), IPv4, hostname y Asset existente. No escribe.
El resultado separa requester, person, devices y warnings; cada ficha contiene
data, provenance y confidence. Los dispositivos separan detected_user y
novadesk_assets.responsible. Nunca equipara solicitante, contacto y custodio.

Reutiliza lookup_ip, institutional_people, contact_search_terms y la consolidación
AD/RRHH existente. Usa GLPIClient GET-only y whitelists institucionales existentes.
Los activos locales se buscan por serie trim/uppercase exacta; si hay varios,
ninguno se elige. El responsable local proviene de Asset.assigned_user, no GLPI.
Sin IP, la búsqueda GLPI por Computer.name o contact es exacta tras el filtro
parcial del servidor. Su confianza es PROBABLE; no inventa IP/MAC. No hay escaneo
de red, selección por similitud o refresh automático de activos.

Al buscar hostname se consulta Computer.name: no se afirma que sea FQDN/DNS.
La búsqueda inversa por persona consulta contact de Computer/Printer, no descubre
todos los equipos relacionados mediante users_id. Es una limitación de esta
primera iteración; la consulta por IP conserva el recorrido completo ya existente.
Si la fuente no está disponible, se devuelven advertencias y se permite carga manual.

Tickets: endpoint GET protegido `/tickets/contexto-tecnico/`, solo ADMIN,
TECHNICIAN o superusuario. El requester siempre es el usuario autenticado.
CLIENT no tiene acceso a datos de otras personas. La respuesta no se cachea.
No cambia ticket_create_view, TicketForm, requester, autoasignación, SLA,
QuickActions, adjuntos, comentarios o notificaciones.

Un panel opcional aparece solo en alta de escritorio para esos perfiles. La
consulta inicial sugiere datos del usuario actual; también permite revisar IP o
hostname. No altera campos al llegar respuestas tardías. Múltiples candidatos
aparecen por separado. El botón de selección de activo exige coincidencia local
única y que ese activo ya esté en el queryset autorizado del formulario, que
sigue limitado a equipos del solicitante. Los demás activos se muestran para
revisión y permanecen sin asociar. PrintingDevice sigue seleccionándose manualmente.

Los datos institucionales se precargan como información de consulta, no nuevos
campos del ticket. La asociación asset solo se rellena tras clic explícito.
Título, problema, prioridad, categoría, impresora, documentos y demás datos
operativos siguen bajo el flujo actual.

Historia: Ticket no tiene snapshot técnico estructurado. ActivityLog tampoco
es una ficha técnica inmutable. La alternativa menos invasiva en esta fase es
el botón «Añadir contexto revisado a descripción», que conserva el texto manual
y añade el bloque NOVADESK_TECHNICAL_CONTEXT_V1. Se guarda únicamente al enviar
el formulario normal; es texto revisado por el autor, no prueba firmada ni
historial inmutable. Los permisos/validación de FK existentes siguen vigentes.
La fecha del ticket sitúa temporalmente la descripción; no se inventa fecha de
inventario GLPI. No se crea migración.

Si se requiere snapshot independiente, inmutable, con auditoría y consulta por
campos, será necesaria una propuesta de modelo/migración futura aprobada.
No usar este bloque como prueba automática para cambiar custodia o identidades.

La UI móvil existente y edición no incorporan el panel. Los errores y resultados
usan mensajes seguros/whitelists, no respuestas completas ni credenciales.
Los tests utilizan mocks y comprueban ausencia de escrituras, responsables
distintos, selección explícita y protección de ediciones manuales.
