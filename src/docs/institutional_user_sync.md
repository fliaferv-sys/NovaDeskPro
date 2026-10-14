# Sincronización institucional individual de usuarios

La sincronización se ejecuta individualmente tras un login exitoso mediante
user_logged_in, y después del guardado normal de User en Admin (save_related).
Se retiraron el botón «Sincronizar datos», su formulario POST y la URL manual.
No hay sincronización masiva ni escrituras al abrir listados, Directorio o Tickets.
El navegador no envía propuestas de sincronización ni valores institucionales.
El login actúa sobre su propia cuenta; Admin mantiene la política ADMIN/SUPERVISOR
o superusuario del servicio existente para actuar sobre otra cuenta.

`apps.accounts.institutional_sync` separa resolución, propuesta y aplicación.
`build_user_institutional_sync_plan` es de lectura; `apply_user_institutional_sync`
descarta propuestas previas, bloquea el User y recalcula inmediatamente antes de
guardar, dentro de transaction.atomic.
El wrapper try_sync_user_institutional_data captura los fallos fuera de esa
transacción/savepoint: no impide autenticación ni revierte el guardado normal
del administrador. Mensajes de log fijos, sin datos personales ni excepciones crudas.

Campos admitidos: id_personal, employee_number, phone y position. Solo se llenan
valores null o vacíos; no se truncan datos demasiado largos. Se verifica que
IdPersonal/legajo no estén asociados a otro User y se conservan sus constraints.
La auditoría ActivityLog comparte la transacción: actor, usuario afectado, nombres
de campos y fecha, sin valores personales. Un fallo de auditoría revierte el User.

Evidencia: IdPersonal exacto y único; legajo exacto y único; correo institucional
exacto y único en RR.HH. con username compatible con ese correo. Si no existe ese
enlace, una cuenta AD activa única por correo Y username puede enlazarse a RR.HH.
por nombre exacto normalizado Y teléfono exacto normalizado, sin ambigüedad. Nombre
local existente debe ser compatible con AD. Nunca se enlaza solo por nombre/teléfono.
Se reutilizan search_directory_employees, search_ad_users y el normalizador RR.HH.;
esta política de escritura no modifica la consolidación utilizada por otras vistas.

Se bloquean identificadores contradictorios, correo/teléfono contradictorios,
identidades inactivas, resultados truncados, fuentes no disponibles y valores
inválidos. Un cargo local diferente se conserva, se informa como conflicto y no
impide completar otros campos seguros. Las diferencias de nombres solo se usan
como protección en el enlace adicional AD-nombre-teléfono, nunca como prueba única.

Protegidos: email, username, role, approval_status, password, is_superuser,
is_staff, is_active, grupos, permisos, profile_image y todas las relaciones.
No se infieren branch, department ni organizational_unit por nombres, ni se cambia
employment_type (su default no constituye un campo vacío). No se crea ningún User.

La foto no se copia ni se almacena: employee_number persistido permite que el
helper get_user_photo_url encuentre la foto institucional existente.

Auditoría: en login el actor es el usuario autenticado; en Admin es el administrador.
Solo se registra la sincronización cuando hubo cambios reales. La auditoría normal
de autenticación existente se conserva independientemente. Un fallo de auditoría
revierte todos los campos sincronizados; el flujo normal continúa.

Rendimiento: solo los hooks individuales consultan fuentes. Se reutilizan búsquedas
repetidas dentro de la misma resolución. Hasta dos búsquedas RR.HH. por identificador,
una por correo y, solo como fallback, dos búsquedas AD y una RR.HH. por nombre.
No se recorren todos los usuarios ni todo AD. Se toman hasta 100 filas por búsqueda;
un resultado saturado se rechaza. AD conserva el límite de su servicio existente.
Si los cuatro campos ya están completos se omite incluso la consulta institucional.
Si aún faltan campos no disponibles, el siguiente login/guardado puede volver a
consultar, pero no genera UPDATE ni ActivityLog de sincronización sin cambios.
La ejecución es síncrona y está sujeta a los timeouts existentes de RR.HH./AD.
No se utiliza post_save: evita recursión y sincronización desde guardados ajenos.

Caso Roberto: probado mediante fixtures sintéticas, no mediante cambios en datos
reales. El resultado real depende del correo/username AD y teléfono/nombre RR.HH.
Si esas evidencias no existen o son contradictorias, requiere revisión manual.
No se buscan teléfonos globalmente porque la integración RR.HH. actual no ofrece
ese campo de búsqueda. Un enlace explícito debe materializarse como IdPersonal o
legajo local para actuar como identificador en esta primera versión.
