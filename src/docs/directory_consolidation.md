# Directorio consolidado (solo lectura)

La lista inicial continúa basada en RRHH y su orden. Consulta AD en lotes de hasta
40 correos exactos usando el lector LDAP existente. Lotes saturados (100 filas)
no se usan para consolidar, porque no prueban unicidad. Si AD falla, RRHH sigue
visible. No descarga indiscriminadamente todas las cuentas AD.

La búsqueda agrega RRHH, AD y cuentas locales; ya no descarta filas por correo
antes de comprobar identidad. Complementa los resultados RRHH con los mismos
lotes AD, incluso al buscar cargo/legajo que AD no conoce. Reutiliza
consolidate_institutional_identities y las reglas de enlaces locales existentes.
Las referencias firmadas de los formularios y el contrato común siguen intactos.

Solo se consolida RRHH/AD con correo institucional compatible y username o
identificador seguro, sin conflictos de identidad/estado. Se conservan los
registros dudosos por separado. La ficha mantiene RRHH para legajo, cargo,
teléfono, vínculo, estado y foto; AD completa username y correo disponible.
La insignia muestra AD + RR.HH. tanto en Django como en resultados dinámicos.

RRHH sin correo: el contrato AD actual no contiene IdPersonal o legajo. Se
requiere una cuenta NovaDesk **ya existente** con IdPersonal RRHH inequívoco,
correo y username que correspondan exactamente a una sola cuenta AD. El merge
común vuelve a comprobar nombres/identificadores/estado antes de mostrar correo.
No crea User ni deduce email desde nombre. Sin esa evidencia se conserva RRHH
sin correo. No puede solucionarse legítimamente con coincidencia de nombres.

AD sin RRHH continúa apareciendo en búsquedas y mantiene foto de tercerizado y
clasificación Tercerizado. La vista inicial no se transforma en listado completo
de AD. RRHH que contradice estado AD no se reactiva ni desactiva automáticamente:
ambas fichas quedan separadas con sus estados originales. No altera tercerizados.csv.

Todo es GET/consulta SQL/LDAP de lectura. No cambia RRHH, AD, cuentas locales,
assets, Printing, Tickets ni permisos. No se imprime la planilla ni nuevos
identificadores sensibles. Solo se añaden sources/source_label al JSON público
del Directorio, dentro de su whitelist existente.
