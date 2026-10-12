# Asignación mixta de ubicaciones de impresoras

Crear/corregir ubicaciones manualmente en el Admin de Inventory, indicando sede,
código único dentro de esa sede, nombre, tipo y estado activo. No es obligatorio
crear todas las propuestas de `propose_printer_locations`.

Primero ejecutar `python manage.py assign_printer_locations --dry-run`.
Sin `--dry-run`, el comando asigna dentro de una transacción únicamente la FK
`organizational_location`. No crea ubicaciones ni cambia otros campos.

Reutiliza el parser y la normalización de `location_analysis`: case, tildes y
espacios repetidos. Dpto./Depto. frente a Departamento y eliminación de prefijos
solo generan posibles coincidencias para revisión, nunca asignaciones.

Requiere branch guardado activo y Sede importada compatible con su nombre,
código o aliases institucionales existentes. Nunca infiere ni cambia branch.
Busca ubicaciones activas en esa misma sede, excluyendo el código provisional
`UBICACION-PENDIENTE`. Asigna solo un candidato exacto sin otros compatibles,
cuando la ubicación actual está vacía o tiene ese código provisional. Una
ubicación real diferente o perteneciente a otra sede requiere revisión.

Estados: ACTUALIZADO (propuesta en dry-run), SIN CAMBIOS (ya asignado), PENDIENTE
(sin dependencia/candidato exacto), REVISAR (ambigüedad, posible coincidencia o
conflicto de sede/ubicación), ERROR (bloque inválido o fallo crítico).
Los bloques inválidos abortan toda ejecución real antes de guardar. Los fallos
de escritura provocan rollback. Las ubicaciones no cambian de nombre y el Admin
combina sede + nombre solo para presentación.

La ejecución real bloquea las filas existentes de sedes, ubicaciones e impresoras
en motores que soportan `select_for_update`. Evitar creación concurrente de
ubicaciones durante su ejecución: esos bloqueos no impiden insertar candidatos
nuevos. Revisar el dry-run después de cada corrección manual.
