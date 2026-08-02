# Arquitectura de NovaDesk Pro

NovaDesk Pro es una aplicación Django modular. El proyecto ejecutable vive en
`src/`, la configuracion global en `src/config/` y los dominios en
`src/apps/`.

## Modulos

- `accounts`: usuarios, roles, sedes y autenticacion.
- `core`: departamentos y categorias compartidas.
- `tickets`: mesa de ayuda, comentarios, adjuntos y solicitudes de acceso.
- `inventory`: activos, ubicaciones, historial tecnico e importacion Excel.
- `deliveries`: movimientos de custodia, actas, documentos y PDF.
- `printing`: equipos, consumibles, stock, contadores y contratos.
- `monitoring`: heartbeat de dispositivos e historial de red.
- `notifications`: alertas personales/globales y generadores periodicos.
- `dashboard`: indicadores ejecutivos, departamentales y preferencias.
- `activity`: auditoria transversal.
- `institution`: identidad visual y datos institucionales.
- `reports`: reservado para reportes; aun no expone funcionalidad.

## Politicas de acceso

Los controles siempre se aplican en las vistas; ocultar un boton no concede ni
revoca permisos.

- `ADMIN` y `SUPERVISOR`: gestion global de tickets y entregas.
- `AUDITOR`: lectura global de tickets, sin mutaciones administrativas.
- `TECHNICIAN`: lectura y gestion de tickets de su departamento.
- `CLIENT`: sus propios tickets; solo puede editarlos mientras esten abiertos.
- Entregas: las mutaciones se reservan a `ADMIN` y `SUPERVISOR` y requieren
  solicitudes POST con CSRF.

## Solicitud de creacion de usuarios

El acceso directo `Crear nuevo usuario corporativo` inicia un ticket con autorizacion
formal. El flujo conserva trazabilidad en `ActivityLog` y versiona cada
documento presentado:

1. En el area `SUPPORT` (Soporte DTI), el solicitante selecciona el acceso
   directo `Crear nuevo usuario corporativo` y completa los datos del pedido.
2. NovaDesk muestra, dentro del formulario del ticket, el enlace institucional
   `https://intranet.petropar.gov.py/?page_id=3309`. El usuario descarga el
   paquete `Formularios para creación de usuario para Correo y Windows`, que
   contiene tres formularios.
3. Tras completar y obtener las firmas directivas, el solicitante combina los
   tres formularios en un unico PDF y lo adjunta junto con la fotocopia de
   cedula.
4. NovaDesk solo crea el ticket cuando ambos archivos son validos. La solicitud
   nace en estado `FORM_ATTACHED` y ambos documentos reciben la version 1.
5. Un usuario con el permiso `tickets.validate_access_request` aprueba o
   rechaza la presentacion. Cada generacion, carga y decision queda auditada.

## Configuracion

Los secretos no se guardan en el codigo. Antes de iniciar Django deben
definirse las variables documentadas en `.env.example`. Django no lee ese
archivo automaticamente: el servicio, contenedor o terminal debe exportarlas.

En produccion se debe usar `DJANGO_DEBUG=False`, una base de datos administrada,
HTTPS y almacenamiento persistente para `media/` y `staticfiles/`.

## Puesta en marcha local

1. Crear un entorno virtual nuevo.
2. Instalar `requirements.txt`.
3. Definir las variables de `.env.example`.
4. Ejecutar `python src/manage.py migrate`.
5. Ejecutar `python src/manage.py check` y `python src/manage.py test`.

En Windows, el repositorio incluye comandos que cargan `.env` automaticamente:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\check_dev.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_dev.ps1
```

El servidor queda disponible en `http://127.0.0.1:8000/`. El archivo `.env`
local esta ignorado por Git y nunca debe copiarse a un repositorio o ticket.
