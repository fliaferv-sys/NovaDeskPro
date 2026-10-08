# NovaDesk Pro en IIS

Ejecutar solamente en producción, en PowerShell de 64 bits como administrador.
Este script no instala IIS, no crea sitios ni cambia bindings, Django o datos.
Requiere IIS Static Content, ARR y URL Rewrite instalados y un sitio existente.
Django debe estar disponible en http://127.0.0.1:8000 y aceptar el host público.

## Preparación

1. En el directorio que contiene manage.py en producción, ejecutar `python manage.py collectstatic --noinput` con el entorno del proyecto.
2. Confirmar los valores reales de STATIC_ROOT y MEDIA_ROOT. Las rutas siguientes corresponden a la estructura actual de producción; son parámetros del script y no se introducen en settings.py.
3. Dar permisos NTFS de lectura a la identidad usada por IIS sobre ambos directorios (incluida la identidad de autenticación anónima si usa IUSR). Mantener los permisos de escritura del proceso Django sobre media. El script no modifica ACL ni autenticación.
4. Revisar las reglas inbound existentes en el sitio y posibles reglas globales del servidor o web.config heredados. El script REEMPLAZA todas las reglas inbound del sitio por las dos reglas de NovaDesk. No usarlo en un sitio compartido sin revisar esa sustitución. Las reglas globales que se ejecutan antes deben excluir static/media también.

## Vista previa y aplicación

Desde deployment, revisar primero:

```powershell
.\configure-iis.ps1 -SiteName 'NOMBRE_REAL_DEL_SITIO' -StaticRoot 'C:\NovaDeskPro\src\src\staticfiles' -MediaRoot 'C:\NovaDeskPro\src\src\media' -WhatIf
```

Para aplicar, ejecutar el mismo comando sin `-WhatIf`.
`-BackendUrl` permite cambiar el puerto de backend manteniendo 127.0.0.1.
WhatIf valida rutas, sitio y módulos, pero no guarda configuración ni crea respaldo.
Antes de aplicar se crea un respaldo de configuración IIS con appcmd; si falla, se cancela.
La configuración se guarda en applicationHost.config mediante una sola confirmación.
Repetir el script deja la misma configuración funcional; cada aplicación crea un respaldo nuevo.

El script crea o actualiza los directorios virtuales /static y /media. La primera
regla evita que esos prefijos (incluso archivos inexistentes) lleguen a Django.
La segunda envía el resto a ARR, preservando la query string. Se habilita el proxy
ARR a nivel servidor, por lo que ese ajuste afecta a todos los sitios.
Los directorios de archivos solo usan StaticFileModule con GET/HEAD y sin listado
de directorios. Los archivos media que se publiquen allí serán accesibles desde
IIS según la autenticación del sitio; verificar que no haya documentos privados
que dependan de autorización Django antes de publicar toda esa carpeta.

## Verificación y recuperación

- Abrir una URL real de CSS bajo /static/ y una foto real bajo /media/funcionarios/; deben devolver 200 y el Content-Type correcto.
- Un archivo inexistente bajo cada prefijo debe devolver 404 de IIS.
- Abrir login/directorio y probar búsquedas con parámetros para confirmar el proxy.
- Ante 403 revisar permisos/autenticación; 404.3 indica MIME type ausente; 500.19 indica configuración bloqueada, módulos faltantes o conflicto heredado. Revisar logs de IIS.
- Para volver atrás, usar el nombre de respaldo impreso: `& "$env:windir\System32\inetsrv\appcmd.exe" restore backup 'NovaDesk-FECHA'`. La restauración devuelve la configuración IIS de todo el servidor al momento del respaldo; coordinar si hubo otros cambios posteriores. No restaura archivos ni datos.

Referencia oficial: [ARR y URL Rewrite](https://learn.microsoft.com/en-us/iis/extensions/url-rewrite-module/reverse-proxy-with-url-rewrite-v2-and-application-request-routing).

No ejecutar este procedimiento en la PC de desarrollo. La validación del script
en desarrollo cubre sintaxis; la comprobación funcional de IIS queda para producción.
