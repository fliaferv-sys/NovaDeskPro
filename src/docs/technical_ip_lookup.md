# Consulta técnica por IP (solo lectura)

Ruta: `/consultas/ip/` (`integrations:ip_lookup`). Acceso autenticado para
TECHNICIAN, ADMIN o superusuario. No se alteran dashboard, navegación global,
CLIENT, notificaciones ni UI móvil existente. La página usa el layout común.
No consulta al abrir: requiere introducir una IPv4 válida y pulsar Consultar.

Requiere las mismas variables que `sync_glpi`: GLPI_API_URL, GLPI_APP_TOKEN,
GLPI_USERNAME, GLPI_PASSWORD. Timeout y TLS usan la configuración compartida.
No introducir secretos en Git. Ver `sync_glpi.md` para definir el entorno.

`apps.integrations.ip_lookup.lookup_ip` es el servicio reutilizable. Busca la
colección IPAddress con searchText[name] y revalida igualdad IPv4 exacta (el
filtro GLPI puede ser parcial). Sigue únicamente relaciones explícitas:

IPAddress(itemtype=NetworkName, items_id) → NetworkName
→ (itemtype=NetworkPort, items_id) NetworkPort
→ (itemtype=Computer/Printer, items_id) equipo.

Obtiene MAC desde el puerto, nombre de red desde NetworkName (no presume FQDN),
nombre/serie/contact desde el equipo, ubicación desde Location y estado desde
State. User se obtiene exclusivamente del users_id del equipo. No se usa
users_id_tech como usuario relacionado. La caché de objetos existe solo durante
esa consulta y no persiste datos ni tokens.

La estructura y campos se verificaron contra el esquema oficial de GLPI 9.5.5:
https://github.com/glpi-project/glpi/blob/9.5.5/install/mysql/glpi-empty.sql
API: https://github.com/glpi-project/glpi/blob/9.5.5/apirest.md

Correos UserEmail y username del User GLPI se buscan exactamente mediante
identity_services. contact también puede aportar correo, username o nombre
como pista; se conservan candidatos contradictorios en lugar de elegir uno.
No se equipara contacto con responsable NovaDesk. Si el contacto o login
tiene un sufijo igual al NetBIOS institucional
configurado (DIRECTORY_AD_NETBIOS_DOMAIN, default PETROPAR), se prueban el texto
original, el username y username@DIRECTORY_AD_DOMAIN. Son términos exactos de
búsqueda, no valores generados para la persona. No se convierten dominios ajenos.
Los resultados se deduplican por el locator existente, nunca por correo/nombre;
las variantes contradictorias quedan como múltiples candidatos. Un correo
derivado no cuenta como evidencia para elevar confianza a CONFIRMADA.
La consulta puede consolidar una fila AD y una RRHH por correo institucional
normalizado y username compatible, o identificador personal compartido. No
fusiona por nombre, duplicados de una fuente ni campos contradictorios.
El helper compartido consolidate_institutional_identities se usa solo en esta
consulta: no altera el merge general ni las selecciones firmadas. Conserva ambas
fuentes y completa campos faltantes, priorizando RRHH para la ficha y AD para
username. Una identidad consolidada unica y de busqueda completa puede ser
CONFIRMADA; nunca confirma responsabilidad sobre el equipo.
Si User está
inactivo, no se confirma persona. No se crea User local ni se exige su existencia.
La whitelist técnica solo devuelve nombre, correo, cargo, dependencia, teléfono
y origen. No expone CI, legajo, IDs locales ni referencias de selección de forms.

Confianza de red: CONFIRMADA significa relación existente en el catálogo GLPI,
no observación en vivo. Todos los puertos/candidatos se presentan; una IP repetida
no permite elegir un equipo. Tipos distintos de Computer/Printer se presentan
con relación DESCONOCIDA y sin inventar su ficha.

Persona: CONFIRMADA solo si correo y username del mismo User GLPI corresponden
a una identidad única y la búsqueda es completa. PROBABLE si existe una única
coincidencia por una pista; DESCONOCIDA si hay varias, incompletitud, inactividad
o indicadores de cuenta no personal. Esto confirma equivalencia de identidad,
nunca responsabilidad ni custodia. Un nombre único no prueba asignación.

Limitaciones reales:
- El contrato estándar 9.5.5 ofrece date_mod, no una fecha universal de último
  inventario automático. Se muestra como última modificación. La fecha real
  depende de plugins como FusionInventory/OCS; no se adivinan sus campos.
- El hostname es NetworkName.name, no se concatena un dominio no confirmado.
- Dependencia proviene de asignaciones institucionales existentes en NovaDesk;
  si no hay asignación no se inventa a partir de ubicación GLPI.
- Las fichas combinadas del Directorio no tienen procedencia por cada campo:
  se indica la combinación de fuentes, sin atribuir todos los datos a RRHH.
- Las entidades/permisos GLPI delimitan el inventario visible. HTTP 403/404 o
  fuentes inaccesibles no se interpretan como ausencia segura del dispositivo.
  Un error GLPI produce un mensaje seguro de indisponibilidad.
- No es un descubrimiento de red ni un snapshot transaccional; DHCP, datos
  antiguos o cambios simultáneos pueden producir múltiples candidatos.

La página devuelve Cache-Control no-store y mantiene escape HTML. Los resultados
usan campos permitidos; errores nunca incluyen respuestas GLPI, headers, URLs
con credenciales o mensajes crudos. Los valores conocidos de secretos del cliente
se redactan. El acceso se limita a GET y todos los endpoints GLPI usan GET.
No se guarda historial de búsquedas. Los logs normales de acceso del servidor
pueden contener la IP consultada, como cualquier URL del servicio.

Pruebas: `python manage.py test apps.integrations apps.directory`.
Los tests usan mocks, sin conectarse al servidor institucional.
