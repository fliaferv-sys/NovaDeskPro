# Componente común de identidad institucional — fase 1

Solo Añadir/Editar Usuario adopta el componente en esta fase. Los demás módulos
conservan sus formularios, endpoints y reglas actuales.

## API y políticas

- POST `directory:identity_search_api`: JSON con `context`, `object_id` (solo edición), `q` y `field`.
- POST `directory:identity_resolve_api`: JSON con `context`, `object_id` y `reference`.
- Campos de búsqueda: `email`, `username`, `employee_number`, `document_number`, `name`.
- Contextos habilitados: `accounts.add` y `accounts.change`. Ambos requieren sesión activa, acceso al Admin y el permiso correspondiente. Edición exige un usuario existente y verifica el permiso del ModelAdmin sobre ese objeto.
- CSRF es obligatorio. Las consultas usan POST para no colocar CI en URL/query string. El código no registra búsquedas ni datos personales. No configurar proxies o instrumentación para registrar cuerpos de estas solicitudes.
- La política del servidor fija los campos de resumen, identidad y valores de formulario. Se rechazan listas arbitrarias de campos y parámetros desconocidos. Un contexto enviado por el navegador no otorga permisos.
- Máximo 20 candidatos. Una consulta incompleta o truncada no permite autocompletar automáticamente.

Respuesta de búsqueda: `resolved`, `candidates`, `not_found` o `unavailable`, con
`incomplete` para advertir consultas parciales. Una coincidencia parcial requiere
selección explícita. La resolución de candidatos devuelve `resolved` o HTTP 409
si la referencia no puede validarse.

## Identificadores y fuentes

`reference` es una selección firmada con vigencia de 30 minutos, vinculada al
administrador, contexto y usuario editado. Contiene claves de fuente y una huella
de identificadores, nunca un snapshot del CI. Se vuelve a leer la fuente al
resolver y al guardar el formulario; referencias alteradas, vencidas o cuyo
vínculo cambió se rechazan. Se puede quitar la selección y continuar manualmente.

- `rrhh_id`: IdPersonal RRHH; no es el UUID de User.
- `local_user_id`: UUID de una cuenta local cuando existe; puede ser null.
- `source`: RRHH, ACTIVE_DIRECTORY, LOCAL o TERCERIZADOS.

Compartir correo no basta para fusionar fuentes. RRHH y una cuenta local solo
se asocian mediante IdPersonal explícito sin conflicto de correo/legajo/CI. AD
y una cuenta local requieren coincidencia de correo y username, sin conflictos.
Los registros duplicados dentro de una fuente permanecen ambiguos. El mapeo de
tercerizados se asocia con AD únicamente cuando sus claves coinciden de forma
inequívoca. Los selectores de módulos todavía no migrados conservan su contrato.

## Contrato y datos faltantes

La identidad puede incluir name/full_name, first_name, last_name, email,
username, document_number, employee_number, phone, position, location,
organizational_unit/path, employment_relationship, employment_type, photo_url,
source, local_user_id y rrhh_id. Los valores ausentes no se inventan.

RRHH actualmente expone nombre completo y no CI ni nombres separados. Buscar
por CI cubre cuentas locales y el mapeo de tercerizados; no garantiza cobertura
RRHH. Las búsquedas amplias de CI no generan una consulta AD por cada candidato.

El adaptador de Usuarios devuelve un username sugerido a partir del correo;
el contrato conserva el username real de la fuente. Departamento y dependencia
solo se completan ante equivalencias locales inequívocas. Ubicación institucional
no se interpreta como ubicación física de un activo.

## Integración frontend gradual

Incluir `components/institutional_identity.html` y cargar una vez los recursos
`shared/js/institutional_identity.js` y `shared/css/institutional_identity.css`.
El servidor proporciona:

- `identity_context`, `identity_object_id`, `identity_mode` (`add` o `change`).
- `identity_bound`: true al volver a mostrar un formulario enviado con errores.
- `identity_field_map`: diccionario clave de datos -> nombre real del campo HTML; admite prefijos de formularios.
- `identity_config_id`: ID único para el JSON de cada instancia.
- `identity_reference_name` y `identity_reference`: nombre/valor del campo oculto de selección.

El componente consulta los campos dentro del formulario, omite los inexistentes
y permite múltiples instancias independientes. `NovaDeskIdentity.initialize(root)`
inicializa contenedores incorporados dinámicamente sin repetir listeners.

Debounce: 350 ms. También admite búsqueda explícita y blur del correo. Cancelación
con AbortController y número de secuencia. Los candidatos son botones utilizables
con teclado; flechas/Home/End navegan y Escape cierra la lista.

En alta, un resultado exacto seguro puede completar campos vacíos y el valor por
defecto de empleo sin pisar cambios manuales. En edición, abrir el formulario no
consulta ni actualiza datos; incluso un resultado exacto exige selección explícita.
Una selección explícita puede reemplazar campos existentes. Las modificaciones
hechas mientras esa resolución está en curso también se preservan. Al cambiar la
consulta se descartan referencias/respuestas antiguas y datos todavía controlados
por el componente. Quitar selección conserva los valores para carga manual.

No se completan contraseñas, roles, grupos, permisos, flags administrativos ni
auditoría. Las validaciones normales de Django permanecen vigentes; el componente
no crea cuentas para personas del directorio ni asigna relaciones automáticamente.

Los archivos anteriores de alta son adaptadores de compatibilidad. El endpoint
Admin de correo mantiene su URL y forma de respuesta usando ahora el servicio
común. El buscador del directorio y entregas conserva su API anterior.

Para otro módulo se debe registrar primero una política de servidor, su whitelist
y validación de referencia al guardar, y después su mapeo de formulario. Un simple
atributo HTML no habilita un módulo ni sus permisos. Esta fase no migra esos módulos.

## Validación

```powershell
python manage.py check
python manage.py test apps.directory apps.accounts
node --check static/shared/js/institutional_identity.js
node --test apps/accounts/tests_js/institutional_autofill.test.cjs
git diff --check
```

Los tests usan datos sintéticos y fuentes simuladas. La comprobación contra RRHH/AD
reales queda para el entorno autorizado; no es parte de una modificación de producción.
