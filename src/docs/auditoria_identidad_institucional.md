# Auditoría de identidad institucional y organización

Fecha: 14 de octubre de 2026. Rama: `develop`.

## Alcance y límites de la evidencia

Auditoría previa a implementación. No se modificó código, esquema ni datos de
negocio. Se revisaron Accounts (modelos, Admin, formularios, vistas, señales,
presentación, sincronización y plantillas), todos los servicios y políticas de
Directory, modelos/Admin/carga de estructura de Institution, Department y
categorías de Core, creación/detalle/contexto de Tickets, Printing (responsables,
formularios, vistas, Admin y plantillas), Inventory (modelos, formularios, vistas,
servicios, Admin y actas), documentación y pruebas relacionadas.

La copia comenzó en `main`; se cambió a `develop`, solicitado por el usuario.
Ambas ramas tenían el mismo contenido versionado. Los elementos sin seguimiento
en el directorio superior se preservaron.

La evidencia de fuentes externas es el contrato implementado por los conectores
y las pruebas. No se interrogó producción ni se verificó el significado real de
`Ubicacion` con RR.HH. La base SQLite local se consultó en modo de solo lectura:
3 sedes activas, 158 dependencias, 0 asignaciones institucionales. Los nombres
`Dpto. Técnico` y `Unidad de Gestión y Control` aparecen respectivamente 2 y 8
veces. Estos recuentos no describen necesariamente producción.

## 1. Arquitectura actual

### Cuenta, persona y organización

`accounts.User` es la cuenta de autenticación y autorización. Tiene identificador
local UUID, `id_personal` RR.HH. único, legajo único, datos personales y tres
relaciones separadas: `branch`, `organizational_unit` y `department`.

`accounts.Branch` identifica sedes físicas por UUID, código único y nombre único.
`institution.OrganizationalUnit` contiene código único, nombre no único, tipo,
parent y estado activo. Su relación opcional `operational_department` no convierte
la dependencia en un equipo de soporte. `core.Department` contiene el equipo
operativo, SLA, categorías y reglas de atención. `inventory.OrganizationalLocation`
es una ubicación física dentro de una sede; no es OrganizationalUnit.

`InstitutionalIdentityAssignment` ya permite una asignación explícita de persona
a dependencia por IdPersonal, correo y/o username. No tiene sede, código de
dependencia de RR.HH. ni correspondencia entre catálogos de fuentes.

### Fuentes y consumidores

RR.HH. lee `dbo.FuncionariosFotosVista`: IdPersonal, LegajoNro, nombre completo,
Ubicacion, teléfono, correo, estado, vínculo, fecha de desvinculación y cargo.
No entrega CI, nombres separados, código de dependencia ni código de sede.

AD consulta displayName, givenName, sn, mail, sAMAccountName, UPN,
userAccountControl y distinguishedName. Los adaptadores no devuelven
distinguishedName ni datos de dependencia/sede. No consultan department,
employeeID ni physicalDeliveryOfficeName. Una OU de AD no debe interpretarse
automáticamente como dependencia institucional.

Directory tiene contratos legacy y común, consolidación RR.HH./AD, enlaces con
cuentas locales, selección firmada por contexto y enriquecimiento organizacional.
Las fotos se resuelven por legajo en `media/funcionarios`, con mapping CSV para
tercerizados y prioridad de la imagen local cargada. No se copian a profile_image.

La sincronización de Accounts completa cuatro campos vacíos tras login y guardado
Admin. Reconstruye el plan con User bloqueado en transacción, conserva valores
locales y registra ActivityLog solo cuando guarda cambios. Las excepciones no
bloquean el flujo principal. No hay botón ni endpoint de sincronización manual.

Tickets conserva requester local para permisos. El contexto distingue solicitante,
usuario detectado y custodio del activo. Printing ya admite un snapshot de identidad
sin cuenta local y un responsible_user opcional. Inventory sigue usando cuentas
locales para custodios, receptores y prestatarios, además de actores de operación.

## 2. Problemas encontrados

### Mezcla de conceptos

1. `accounts/user_presentation.py`: display_location toma Department o
   identity.location; `user_list.html` lo muestra en Equipo de atención. Una
   ubicación/dependencia de RR.HH. puede aparecer como equipo operativo.
2. `directory/identity_policies.py::account_form_values`: busca Department por
   nombre igual a identity.location y propone su FK. Aunque la coincidencia sea
   exacta, la correspondencia es semánticamente incorrecta.
3. `directory/identity_services.py::_normalize_local_user`: location contiene
   Department. Esto permite que el equipo operativo se propague como ubicación
   institucional y participe en conflictos o fusiones de identidades.
4. `integrations/technical_context.py::PERSON_KEYS`: la etiqueta Dependencia se
   guarda como department. `tickets/context_snapshot.py`, JS y plantilla usan
   esa clave; la dependencia institucional termina etiquetada como departamento.
5. `tickets/views.py`: requester_profile.location contiene Department en el
   fallback local y Ubicacion en el fallback RR.HH. El mismo campo cambia de
   significado. El detalle consulta directamente RR.HH. y evita el contrato
   consolidado.
6. Inventory: Asset.department es texto libre y se incorpora a full_location;
   StockDelivery y StockMovement usan Department operativo bajo el rótulo
   genérico Departamento. No hay una relación institucional equivalente. No
   corresponde reinterpretar esos datos históricos ni convertirlos en FK.

### Resolución, seguridad e inconsistencias de contrato

7. `_enrich_with_organizational_unit` resuelve por prioridad IdPersonal, correo,
   username y `.first()`. No verifica que las evidencias disponibles concuerden,
   ni detecta identificadores contradictorios entre asignaciones. Filtra la
   asignación activa, pero no la dependencia activa. La prioridad está incluso
   codificada en una prueba actual; debe sustituirse por prueba de conflicto.
8. La ruta parent no tiene protección contra ciclos. El modelo tampoco valida
   ciclos. Una estructura mal cargada puede bloquear la construcción de ruta.
9. `_normalize_local_user` no aporta la dependencia local ni la sede; el
   enriquecimiento posterior puede devolver dependencia nula aunque User tenga
   una relación. Los consumidores no disponen de una política común para
   relación local versus mapping institucional.
10. `search_common_identities` usa `_merge_linked_identities`, pero no aplica
    directamente la consolidación RR.HH./AD que usa el directorio. Sin User local
    pueden quedar dos candidatos donde el directorio muestra una sola persona
    confirmada. Technical context consolida otra vez por su cuenta.
11. `resolve_institutional_identity` devuelve el primer correo exacto entre
    resultados de búsqueda general y `get_ad_user_by_email` limita a uno. No
    demuestran unicidad. Resolver por IdPersonal tampoco comprueba conflicto con
    el correo de la cuenta. No son equivalentes al matching seguro de sync.
12. Directory legacy y contrato común difieren: id_personal/rrhh_id,
    name/full_name, vínculo textual/código, fuentes/etiqueta y estado. El común
    omite status/source_label y no dispone de branch. Los adaptadores deben
    converger sin ampliar las whitelists de permisos indiscriminadamente.
13. `enrich_user_list` enlaza por IdPersonal o correo único del listado, sin
    validar todos los conflictos de legajo/username/teléfono que sync valida.
    Tampoco filtra explícitamente identidades inactivas. Su lectura no escribe,
    pero puede mostrar datos de una asociación no confirmada por el mismo criterio.
14. La columna Usuario solo muestra el nombre local y Vínculo solo el vínculo
    local; no aprovechan nombre/vínculo confirmado cuando corresponde. El perfil
    solo presenta profile_image y no la referencia de foto institucional.
15. Directory home/API filtran actividad al final; otros servicios devuelven
    candidatos inactivos y la política de selección rechaza inactividad conocida.
    Debe conservarse la información de estado para validar, y aplicar una regla
    consistente a la presentación de personas activas. No asumir activo cuando
    el estado sea desconocido.
16. Printing guarda nombre/correo como snapshot mínimo y no los refresca en GET,
    correctamente. Sin embargo, sus vistas no consumen resolve_persisted_identity
    para presentar dependencia/sede actual; el resolver existe pero no está
    integrado al listado/detalle. La ubicación física del equipo es otro dato.
17. Inventory no puede representar una persona sin User: Asset.assigned_user,
    StockMovement.recipient, StockDelivery.recipient y ToolLoan.borrower son FK
    locales; los formularios y servicios también exigen User. Los snapshots
    históricos de nombres no contienen un identificador institucional reutilizable.
18. `CustomUserAdmin.institutional_lookup` fija el dominio petropar.gov.py,
    mientras los servicios comunes usan DIRECTORY_AD_DOMAIN. La documentación
    de identidad fase 1 todavía afirma que solo Accounts usa el componente y
    permite el autocompletado de Department; está desactualizada frente a Printing
    y frente a la separación solicitada.

### Rendimiento y sincronización

19. `_enrich_with_organizational_unit` realiza hasta tres búsquedas por identidad
    y recorre padres con consultas. Para 5000 personas, cargar fuentes una vez
    no elimina este N+1 de base local. `_common_identity` repite enriquecimiento.
20. La búsqueda común consulta enlaces User por candidato; el contrato legacy
    carga usuarios sin todas las relaciones usadas por normalización. Hay N+1
    adicional de cuentas y Department. La vista del listado Accounts sí usa
    select_related para sus tres FK.
21. Directory home carga todo el directorio para KPI y, con búsqueda, vuelve a
    consultar fuentes. Technical context busca correo y username separadamente;
    su caché evita solo repetir la misma combinación, no búsquedas solapadas.
22. Sync no enriquece organizational_unit ni branch. Su atajo de cuatro campos
    completos impediría intentar llenar nuevas FK vacías. Extenderlo requiere
    cuidar idempotencia y revalidación del mapping dentro de la transacción.
23. El User bloqueado que sync guarda no actualiza la instancia ya en memoria
    del login/Admin. Consumidores de esa instancia pueden observar datos anteriores
    durante la misma solicitud. Las restricciones únicas y el manejo de errores
    conservan seguridad de escritura, pero deben probarse carreras de identificadores.

## 3. Datos realmente disponibles y correspondencias

| Destino | Fuente disponible | Correspondencia segura actual |
| --- | --- | --- |
| id_personal/legajo/teléfono/cargo | RR.HH.; claves de cuenta AD como evidencia | Reglas conservadoras actuales de sync |
| Nombre/vínculo/estado | RR.HH., AD y cuenta local según contrato | Presentación con identidad confirmada; no sobreescritura automática de cuenta |
| Foto | Archivo por legajo o mapping de tercerizados | Referencia de lectura; nunca profile_image |
| organizational_unit | InstitutionalIdentityAssignment y catálogo local | Identificadores exactos consistentes y dependencia activa |
| Ruta institucional | parent/code/type del catálogo local | Recorrido validado, sin ciclos |
| branch | Catálogo local y FK locales ingresadas explícitamente | No existe fuente externa implementada ni mapping de persona a sede |
| department | Department y User.department | Solo asignación operativa local |

No hay códigos comunes de sede/dependencia expuestos por los conectores. Los
códigos de OrganizationalUnit son locales, cargados por comando, no demostrados
como códigos de RR.HH. Ubicacion es texto libre; su semántica no se ha verificado.
No se usará como sede. Un nombre exactamente igual no acredita equivalencia
semántica entre catálogos, y los nombres repetidos impiden inferencia inequívoca.

## 4. Automatización segura

- Mantener sync personal, matching, permisos, campos protegidos y auditoría.
- Completar organizational_unit vacío cuando una identidad confirmada tenga una
  asignación explícita única, consistente y activa. Conservar una FK distinta e
  informar conflicto. No derivar Department de esa relación.
- Separar las tres columnas; conservar sede solo desde User.branch, equipo solo
  desde User.department y dependencia desde FK/mapping institucional confirmado.
- Reutilizar el contrato consolidado en lectura para Directory, Accounts, contexto
  de Tickets y responsables Printing, con carga por lotes y referencias de foto.
- Mantener requester y actores locales para permisos; enriquecer contexto sin
  cambiar propiedad de tickets/activos ni conceder roles.

## 5. Lo que no puede automatizarse todavía

No puede llenarse branch desde RR.HH./AD con el contrato actual. Tampoco pueden
asignarse dependencias desde nombres o Ubicacion sin un mapping autorizado.
La base local no contiene asignaciones explícitas para activar ese camino.

Se recomienda una fuente institucional con identificador estable de sede y de
dependencia, más un mapping central fuente+código externo -> código local. Cuando
la fuente no tenga códigos, la clave textual exacta debe ser un mapping explícito
aprobado y contextualizado, no una regla de similitud. Un mismo código/texto con
múltiples destinos debe bloquear asignación. No inferir sede desde la jerarquía
institucional ni introducir reglas personales.

Las personas de Inventory sin cuenta no pueden persistirse correctamente con el
esquema actual. No se crearán cuentas ficticias ni se guardará su identidad en
notes para evitar una migración.

## 6. Archivos previstos

- Directory: identity_services.py, identity_policies.py, identity_selection.py,
  views.py y tests; nuevo servicio central de resolución organizacional por lotes.
- Accounts: institutional_sync.py, user_presentation.py, views.py, admin.py,
  tests; conservar hooks signals.py/apps.py salvo ajustes necesarios de instancia.
- Institution: servicio de mapping y validación jerárquica; models.py/admin.py y
  migraciones únicamente si se aprueba extender el mapping persistente.
- Templates: accounts/user_list.html, accounts/profile.html, directory/home.html.
- Tickets/Integrations: integrations/ip_lookup.py, technical_context.py,
  automatic_context.py, tickets/context_snapshot.py, tickets/views.py,
  static/tickets/js/technical_context.js, templates/tickets/context_snapshot_detail.html
  y ticket_detail.html; pruebas Python/JS correspondientes.
- Printing: vistas/servicio de presentación, modelos solo para propiedades de
  lectura si conviene, plantillas de detalle/listado y pruebas de responsable.
- Inventory: models.py, forms.py, admin.py, views.py, servicios stock/tool_loans,
  actas y plantillas implicadas, tests y migraciones para referencias de personas.
- Documentación de los tres contratos y compatibilidad de snapshots históricos.

## 7. Migraciones necesarias y punto de detención

Las correcciones de presentación, contrato, consultas y sync de dependencia
explícita pueden hacerse sin migración. El cierre integral de Inventory sí requiere
esquema: referencias institucionales opcionales para custodio/receptor/prestatario,
FK local opcional cuando corresponde, y validación de que exista una persona válida.
Los actores que registran, autorizan o completan operaciones seguirán siendo User.
Los flujos de autoservicio seguirán requiriendo vínculo local confirmado.

Recomendación: reutilizar el formato de referencia institucional mínimo de Printing,
mantener snapshots históricos de actas y conservar las FK existentes. Agregar campos
sin backfill inferido; hacer nullable las FK de receptor/prestatario que hoy son
obligatorias y agregar las restricciones correspondientes. No crear un nuevo modelo
persistente de persona si la referencia actual satisface estos usos.

Un mapping persistente de fuente a Branch también requiere esquema nuevo o extender
InstitutionalIdentityAssignment. Antes debe confirmarse qué fuente y clave son
autoritativas para sede; ninguna de las presentes permite decidirlo.

Se detiene antes de modificar código o crear migraciones por la instrucción expresa:
«Si se requiere migración, detenerse antes de crearla y explicar por qué».
No se ejecutó ninguna migración contra la base de negocio. Las pruebas crean su
base aislada y aplican allí las migraciones ya existentes.

## 8. Plan único de implementación

1. Resolver la fuente autoritativa de sede y aprobar el diseño de referencias
   institucionales en Inventory. Si no existe fuente de sede, dejar branch vacío
   y documentar esa limitación; no impedir las demás mejoras por ese dato faltante.
2. Centralizar resolución de organización con carga de assignments/unidades por
   lotes, comprobación de todos los identificadores, actividad, ambigüedad y ciclos.
   Mantener decisiones de matching personales actuales; no introducir fuzzy matching.
3. Unificar el contrato de persona y sus adaptadores legacy/común sin ampliar permisos.
   Usar consolidación segura en todos los consumidores y evitar consultas redundantes.
4. Ampliar sync solo con FK autorizadas, vacías y revalidadas en la transacción.
   Conservar excepciones aisladas, idempotencia y ActivityLog solo por cambios.
5. Corregir Accounts/perfil y las tres columnas; fotos por referencia y fallbacks
   exclusivamente dentro del mismo concepto. No modificar correo/username automáticamente.
6. Corregir Tickets/contexto/detalle usando contrato común: dependencia separada de
   equipo y sede, requester local inalterado, UI CLIENT simple y detalle técnico
   solo bajo permisos actuales. No reinterpretar snapshots department antiguos;
   manejar versión/compatibilidad en la lectura.
7. Integrar lectura institucional en Printing sin modificar ubicación del equipo,
   guardar solo selección explícita validada y no crear cuentas. Aislar fallos de fuentes.
8. Aplicar cambios mínimos aprobados de Inventory, conservar historial/FK, registrar
   referencia institucional por selección validada y mantener User para actores/permisos.
9. Crear pruebas de todos los escenarios pedidos: contrato completo, legajo/foto,
   teléfono/cargo, mapping seguro/ambiguo/inactivo/contradictorio, branch sin fuente,
   department nunca inferido, columnas, login/Admin/idempotencia, fallos RR.HH./AD,
   conflictos/auditoría/rollback, Tickets, Printing, persona versus cuenta y GET sin
   escrituras. Medir consultas con múltiples personas y jerarquías profundas.
10. Ejecutar suites relevantes y JS, check, makemigrations --check y diff --check;
    entregar diff/status y resumen. Sin commit, push ni operaciones de producción.

## Validación de línea de base

Se usó `C:\NovaDeskPro\venv\Scripts\python.exe`; el comando `python` del PATH
apunta al alias de Microsoft Store.

- Primera ejecución: 511 pruebas, OK, en 93,741 segundos. Incluye apps.accounts,
  apps.directory, apps.institution, apps.integrations.test_technical_context,
  apps.integrations.test_ip_lookup, apps.tickets.test_technical_context,
  apps.tickets.test_context_snapshot, apps.tickets.test_automatic_context,
  apps.printing.test_responsible_identity y apps.inventory.
- Ejecución adicional corregida: 176 pruebas, OK, en 68,678 segundos. Incluye
  apps.tickets.tests, apps.printing.tests, apps.integrations.test_glpi y
  apps.core.tests. Total de las dos ejecuciones correctas: 687 pruebas.
- Una invocación intermedia incluyó por error apps.integrations.tests, que no
  existe: 145 pruebas reales pasaron y hubo un error de importación del label.
  La ejecución adicional corregida indicada arriba pasó íntegramente.
- `manage.py check`: sin problemas. `makemigrations --check`: sin cambios.
- `git diff --check`: sin errores. No hay diff de código; el único archivo nuevo
  de esta tarea es este informe, que Git todavía muestra sin seguimiento.

Las pruebas son línea de base del comportamiento existente, no validación de una
implementación nueva. Algunas pruebas actuales afirman los fallbacks y prioridades
incorrectos descritos arriba; que pasen no prueba la arquitectura solicitada.
