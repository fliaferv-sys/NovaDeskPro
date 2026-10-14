# Implementación integral de identidad institucional

14 de octubre de 2026, rama `develop`. Implementación de la auditoría aprobada
en `docs/auditoria_identidad_institucional.md`.

## Arquitectura resultante

| Concepto | Representación | Uso |
| --- | --- | --- |
| Persona | Contrato consolidado Directory y referencia institucional mínima | Datos personales, selección y custodia, con o sin cuenta |
| Cuenta | accounts.User | Autenticación, permisos, roles y actores de operaciones |
| Sede | accounts.Branch | Relación física explícita; nunca inferida desde RR.HH. |
| Dependencia | institution.OrganizationalUnit | Organigrama con código, tipo, parent y ruta |
| Equipo de atención | core.Department | Soporte, tickets, categorías, SLA y asignaciones |
| Ubicación física | inventory.OrganizationalLocation | Ubicación dentro de una sede; no dependencia institucional |

`institution.identity_organization` centraliza los mappings ya existentes de
InstitutionalIdentityAssignment. Indexa IdPersonal, correo y username exactos;
varias asignaciones coincidentes o identificadores contradictorios no eligen un
ganador por prioridad. Unidades inactivas, padres inactivos y ciclos no producen
una ruta válida. El índice se carga una vez por resolución y se comparte entre
adaptadores anidados. No existe caché persistente que pueda conservar mappings
modificados entre solicitudes.

Las relaciones locales existentes se conservan para presentación. Una discrepancia
con el mapping se informa como conflicto y no autoriza sobreescritura. El resolver
no traduce Ubicacion, cargo, nombre ni operational_department en FK institucionales.

No se creó un catálogo nuevo de personas ni cuentas ficticias. Se reutiliza el
patrón de referencia mínima de Printing: locator, fuente, nombre, correo, username
y, cuando existe un enlace seguro, local_user_id. Las referencias firmadas de
selección se verifican en el servidor y se vinculan al actor, módulo y objeto.

## Accounts y automatización

- Eliminados location RR.HH. -> display_location/equipo de atención y location ->
  Department en el autocompletado Admin.
- El listado presenta branch, dependencia y equipo por separado. El enriquecimiento
  de persona rechaza actividad no confirmada y conflictos de identificadores,
  username, correo, teléfono y legajo. Nombre y vínculo se presentan desde datos
  locales o institucionales confirmados según su campo.
- El perfil resuelve la foto institucional por referencia y presenta teléfono,
  cargo y dependencia enriquecidos. No guarda archivos en profile_image.
- Sync mantiene sus reglas personales, permisos y cuatro campos anteriores. Agrega
  solamente organizational_unit_id desde una asignación exacta, única, coherente y
  activa. No modifica una dependencia local distinta.
- La aplicación vuelve a consultar las fuentes y mappings con User bloqueado,
  y bloquea las filas del mapping/unidades dentro de la transacción. No confía en
  planes enviados o calculados anteriormente.
- Se preservan login sync, Admin save sync, idempotencia y aislamiento de fallos.
  Un usuario con campos personales completos puede recibir una nueva dependencia
  explícita; sin mapping no se repiten lecturas externas innecesarias.
- ActivityLog solo se crea cuando se guardan cambios. La instancia User en memoria
  recibe los campos guardados después de que la auditoría de actividad tuvo éxito.
- Se utiliza DIRECTORY_AD_DOMAIN en el endpoint legacy del Admin.

## Directory

- El contrato común consolida RR.HH. + AD también sin User local y revalida los
  enlaces consolidados de una selección firmada. Duplicados y contradicciones
  permanecen como candidatos ambiguos.
- El enlace local no puede ocultar contradicciones entre identificadores de fuentes.
  Se preservan los locators de fuentes y las etiquetas de procedencia.
- branch, status, sources y source_label se incorporan al contrato común; el
  adaptador legacy de búsqueda agrega branch opcional. Una sede ausente permanece
  nula y se presenta como Sin asignar.
- Las cuentas locales ya no aportan Department como location institucional.
  Su dependencia local produce una ruta coherente mediante el mismo catálogo.
- El resolver legacy no elige el primer correo RR.HH. duplicado ni acepta IdPersonal
  y correo contradictorios. Las búsquedas individuales RR.HH./AD leen hasta dos
  registros y rechazan duplicados, en vez de ocultarlos con un límite de uno.
- Reemplazados los enlaces User por candidato por una consulta en lote. La resolución
  organizacional usa dos consultas locales por operación, sin consultas por padre.
  Una prueba con 50 personas verifica tres consultas totales para el listado
  (catálogo, mappings y cuentas ancla), independientemente de la cantidad de personas.
- Se mantiene el filtro de personas activas del directorio. El texto Ubicacion se
  rotula Referencia RR.HH., separado de dependencia y sede.

## Tickets y contexto técnico

- Dependencia del contrato institucional se normaliza como organizational_unit,
  no department. La clave department representa exclusivamente el equipo operativo.
- Los snapshots nuevos usan resolver_version 2 y claves separadas para dependencia,
  equipo y sede. No se migran ni reescriben snapshots existentes.
- Los snapshots históricos se rotulan como referencia histórica de dependencia;
  no se reinterpretan automáticamente como un equipo de atención.
- El detalle usa el resolver central y matching confirmado del usuario. No hace
  la consulta paralela directa a RR.HH. que sobrescribía el perfil sin comprobar
  contradicciones. Los datos locales personales poblados se conservan.
- Requester, permisos, propiedad de activos y reglas de asociación no se modifican.
  La UI CLIENT sigue mostrando únicamente su resumen sencillo; el detalle técnico
  conserva las restricciones existentes.
- El custodio de un activo puede aparecer como persona institucional sin cuenta;
  eso no concede can_select ni acceso a autoservicio. Se mantienen los enlaces
  locales explícitos para selección automática y autorización.

## Printing

- Se conservan responsible_identity y responsible_user, su selección explícita y
  la posibilidad de una persona sin cuenta local.
- Listado/detalle enriquecen la dependencia de la persona desde el servicio central
  en una carga por lote y sin escrituras. Fallos de fuentes conservan los datos
  históricos de nombre/correo y relaciones locales.
- Sede de la persona y sede/ubicación física del equipo se presentan por separado.
  El detalle usa effective_branch/effective_location para la ubicación del equipo,
  sin sustituirla por la dependencia o equipo operativo del responsable.

## Inventory y compatibilidad

| Modelo | Campo nuevo | FK histórica conservada |
| --- | --- | --- |
| Asset | custodian_identity | assigned_user |
| StockDelivery | recipient_identity | recipient |
| StockMovement | recipient_identity | recipient |
| ToolLoan | borrower_identity | borrower |

- Cuatro campos JSON con default=dict, blank=True, editable=False. Un registro
  anterior sigue funcionando con referencia vacía y su FK User existente.
- StockDelivery.recipient y ToolLoan.borrower ahora permiten null/blank. Las FK
  permanecen presentes con PROTECT. assigned_user conserva SET_NULL y StockMovement
  mantiene su FK opcional. No se alteran las FK de actores.
- Formularios de activos, entregas y préstamo rápido, y Admin de esos modelos,
  reutilizan el selector firmado central con contextos y permisos propios.
  El servidor vuelve a leer la fuente; no acepta un snapshot de persona enviado
  por el navegador. Una selección sin User no crea cuentas.
- No puede cambiarse una FK local mientras queda una referencia institucional
  diferente: se exige reselección o quitarla explícitamente. Receptor/prestatario
  deben tener cuenta o referencia válida; custodio de un activo puede quedar vacío.
- La entrega conserva recipient_name/department_name históricos al prepararse,
  y propaga recipient_identity al movimiento de stock. La operación sigue siendo
  atómica y los movimientos/entregas completados conservan su inmutabilidad.
- El préstamo conserva borrower_name histórico y delivered_by/received_by locales.
  Las reglas de permisos de los técnicos siguen usando la FK borrower; una identidad
  institucional no amplía el acceso a préstamos ajenos.
- Activos con persona institucional sin User se consideran asignados en listados,
  filtros y clasificación de custodia. Los actores de autoservicio siguen siendo
  cuentas locales. El área textual histórica del activo se muestra como área
  descriptiva, sin fallback desde el equipo operativo del usuario.
- La transferencia de custodia existente de Deliveries actualiza/quita la referencia
  actual del activo de forma explícita, preservando todas las actas históricas.
  No hay backfill de custodios ni inferencia de vínculos por nombres.
- Abrir GET de un formulario no valida selecciones externas ni modifica referencias.
  El enriquecimiento de listados/detalles es solamente de lectura.

## Migración revisada

`apps/inventory/migrations/0020_asset_custodian_identity_and_more.py` contiene:

1. Cuatro AddField para las referencias opcionales.
2. Dos AlterField que permiten nulos en recipient de StockDelivery y borrower de
   ToolLoan, conservando destino, related_name y PROTECT.

Se revisó manualmente. No contiene RemoveField, DeleteModel, RunPython, RunSQL,
backfill, eliminación ni modificación masiva de registros. No se aplicó a la base
de negocio ni a producción; Django la aplica únicamente en la base aislada de tests.
La migración debe aplicarse mediante el despliegue autorizado antes de usar los
campos nuevos sobre una base existente.

## Pendientes reales

- No existe fuente ni mapping confiable de sede. branch no se sincroniza y permanece
  Sin asignar cuando no hay FK local. La resolución organizacional central y el
  campo opcional branch del contrato permiten incorporar en el futuro un mapping
  explícito, con identificadores autoritativos y revalidación; no se cargó ninguno.
- La auditoría encontró cero mappings institucionales en la base local. La capacidad
  de sync de dependencia está implementada, pero solo se activa con assignments
  explícitos que la institución mantenga. No se infieren desde Ubicacion.
- No se inventan CI, nombres separados RR.HH., atributos organizacionales AD ni
  estados de fuentes desconocidos. Las reglas de elegibilidad actuales se preservan.
- Se mantienen los límites de búsqueda y las consultas externas distintas necesarias
  para verificar evidencias. No se promete una sola llamada externa para todos los
  escenarios; se eliminaron los N+1 locales principales y las lecturas por padre.

## Validación

Se usa `C:\NovaDeskPro\venv\Scripts\python.exe`.

- `manage.py check`: sin problemas.
- `manage.py makemigrations --check`: sin cambios adicionales.
- `git diff --check`: sin errores de whitespace.
- `node --check static/tickets/js/technical_context.js`: OK.
- Pruebas JS de selección institucional y contexto de Tickets: 28 OK.
- Suite Django completa (`manage.py test`): **947 tests OK**, 299,643 segundos.

La primera ejecución completa encontró fixtures nuevos incompletos y una prueba
de Reports que dependía de un manifiesto de estáticos de producción. Se corrigieron
los fixtures y se aplicó a esa clase de pruebas el almacenamiento de prueba ya
existente. No se cambió la configuración de estáticos de la aplicación.

No se hicieron commit, push, despliegue ni operaciones sobre producción.

## Archivos modificados o creados en esta implementación

- `apps/accounts/admin.py`
- `apps/accounts/institutional_sync.py`
- `apps/accounts/test_institutional_sync.py`
- `apps/accounts/test_user_presentation.py`
- `apps/accounts/tests.py`
- `apps/accounts/user_presentation.py`
- `apps/accounts/views.py`
- `apps/deliveries/views.py`
- `apps/directory/ad_services.py`
- `apps/directory/identity_policies.py`
- `apps/directory/identity_services.py`
- `apps/directory/services.py`
- `apps/directory/tests.py`
- `apps/directory/views.py`
- `apps/institution/models.py`
- `apps/integrations/automatic_context.py`
- `apps/integrations/ip_lookup.py`
- `apps/integrations/technical_context.py`
- `apps/inventory/admin.py`
- `apps/inventory/forms.py`
- `apps/inventory/models.py`
- `apps/inventory/services/stock.py`
- `apps/inventory/views.py`
- `apps/printing/test_responsible_identity.py`
- `apps/printing/views.py`
- `apps/reports/tests.py`
- `apps/tickets/context_snapshot.py`
- `apps/tickets/test_context_snapshot.py`
- `apps/tickets/tests.py`
- `apps/tickets/views.py`
- `static/tickets/js/technical_context.js`
- `templates/accounts/profile.html`
- `templates/accounts/user_list.html`
- `templates/directory/home.html`
- `templates/inventory/asset_form.html`
- `templates/inventory/asset_list.html`
- `templates/inventory/partials/asset_user.html`
- `templates/inventory/stock_delivery_detail.html`
- `templates/inventory/stock_delivery_form.html`
- `templates/inventory/stock_delivery_list.html`
- `templates/inventory/tool_loans/_dashboard_loan_list.html`
- `templates/inventory/tool_loans/active_list.html`
- `templates/inventory/tool_loans/detail.html`
- `templates/inventory/tool_loans/quick_create.html`
- `templates/inventory/tool_loans/tool_list.html`
- `templates/inventory/used_asset_list.html`
- `templates/printing/printing_device_detail.html`
- `templates/printing/printing_devices_by_model.html`
- `templates/tickets/context_snapshot_detail.html`
- `templates/tickets/ticket_detail.html`
- `apps/directory/person_references.py`
- `apps/directory/test_identity_organization.py`
- `apps/institution/identity_organization.py`
- `apps/inventory/migrations/0020_asset_custodian_identity_and_more.py`
- `apps/inventory/person_forms.py`
- `apps/inventory/test_person_identity.py`
- `docs/implementacion_identidad_institucional.md`
- `templates/admin/inventory/person_form.html`
- `templates/inventory/person_selector.html`

## Git status --short al cierre

```text
 M apps/accounts/admin.py
 M apps/accounts/institutional_sync.py
 M apps/accounts/test_institutional_sync.py
 M apps/accounts/test_user_presentation.py
 M apps/accounts/tests.py
 M apps/accounts/user_presentation.py
 M apps/accounts/views.py
 M apps/deliveries/views.py
 M apps/directory/ad_services.py
 M apps/directory/identity_policies.py
 M apps/directory/identity_services.py
 M apps/directory/services.py
 M apps/directory/tests.py
 M apps/directory/views.py
 M apps/institution/models.py
 M apps/integrations/automatic_context.py
 M apps/integrations/ip_lookup.py
 M apps/integrations/technical_context.py
 M apps/inventory/admin.py
 M apps/inventory/forms.py
 M apps/inventory/models.py
 M apps/inventory/services/stock.py
 M apps/inventory/views.py
 M apps/printing/test_responsible_identity.py
 M apps/printing/views.py
 M apps/reports/tests.py
 M apps/tickets/context_snapshot.py
 M apps/tickets/test_context_snapshot.py
 M apps/tickets/tests.py
 M apps/tickets/views.py
 M static/tickets/js/technical_context.js
 M templates/accounts/profile.html
 M templates/accounts/user_list.html
 M templates/directory/home.html
 M templates/inventory/asset_form.html
 M templates/inventory/asset_import.html
 M templates/inventory/asset_list.html
 M templates/inventory/partials/asset_user.html
 M templates/inventory/qr/index.html
 M templates/inventory/stock_delivery_detail.html
 M templates/inventory/stock_delivery_form.html
 M templates/inventory/stock_delivery_list.html
 M templates/inventory/tool_loans/_dashboard_loan_list.html
 M templates/inventory/tool_loans/active_list.html
 M templates/inventory/tool_loans/detail.html
 M templates/inventory/tool_loans/quick_create.html
 M templates/inventory/tool_loans/tool_list.html
 M templates/inventory/used_asset_list.html
 M templates/printing/printing_device_detail.html
 M templates/printing/printing_devices_by_model.html
 M templates/printing/psline_dashboard.html
 M templates/printing/register_ticket_consumable.html
 M templates/tickets/context_snapshot_detail.html
 M templates/tickets/ticket_detail.html
?? ../directory_sql_prod.txt
?? ../documentos/
?? ../respaldos/
?? apps/directory/person_references.py
?? apps/directory/test_identity_organization.py
?? apps/institution/identity_organization.py
?? apps/inventory/migrations/0020_asset_custodian_identity_and_more.py
?? apps/inventory/person_forms.py
?? apps/inventory/test_person_identity.py
?? docs/auditoria_identidad_institucional.md
?? docs/implementacion_identidad_institucional.md
?? templates/admin/inventory/
?? templates/inventory/person_selector.html
```

Los tres elementos sin seguimiento del directorio superior y el informe de auditoría
ya existían al comenzar esta implementación y se preservaron. Git también muestra
cuatro archivos restaurados sin diff de contenido (asset_import.html, qr/index.html,
psline_dashboard.html y register_ticket_consumable.html); sus hashes filtrados son
los de HEAD. No forman parte de los cambios funcionales listados arriba.
