# Despliegue de NovaDesk Pro

## Requisitos

- Python compatible con la versión fijada de Django.
- PostgreSQL para producción.
- Un proxy HTTPS que sirva `staticfiles/` y mantenga `media/` privado.
- Un programador de tareas para las alertas automáticas.

## Secuencia de publicación

1. Crear un entorno virtual nuevo e instalar `requirements.txt`.
2. Exportar las variables de `.env.example` desde un almacén seguro.
3. Ejecutar `python src/manage.py check --deploy`.
4. Ejecutar `python src/manage.py migrate`.
5. Ejecutar `python src/manage.py collectstatic --noinput`.
6. Ejecutar `python src/manage.py test`.
7. Iniciar el servidor WSGI/ASGI detrás del proxy HTTPS.
8. Comprobar `/health/`.

No se debe publicar `src/media/` como un directorio web abierto. Los documentos
operativos se descargan mediante vistas autenticadas.

## Tareas periódicas

Ejecutar cada cinco minutos `python src/manage.py generate_notifications`.
La tarea actualiza SLA, equipos fuera de línea, stock y vencimientos de
contratos. Su salida debe enviarse al sistema de logs del servidor.

## Respaldo

Respaldar diariamente PostgreSQL y el almacenamiento de documentos. Al menos
una vez al mes debe probarse la restauración completa en un entorno aislado.
