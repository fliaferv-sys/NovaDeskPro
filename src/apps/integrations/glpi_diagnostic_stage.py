"""Temporary stage tracking; never include raw exception text or payloads."""


class DiagnosticStage:
    def __init__(self):
        self.name = "configuracion GLPI"

    def set(self, name):
        self.name = name

    def failure(self, exception):
        # Whitelist messages rather than trying to redact arbitrary response bodies.
        message = {
            TypeError: "Tipo de dato inesperado.",
            AttributeError: "Atributo esperado no disponible.",
            ValueError: "Valor inesperado.",
            UnicodeError: "Error de codificacion.",
        }.get(type(exception), "Detalle omitido por seguridad.")
        if isinstance(exception, KeyError):
            message = "Falta una clave esperada."
            if len(exception.args) == 1 and isinstance(exception.args[0], str) and exception.args[0] in {"id", "items_id", "itemtype", "name"}:
                message = f"Falta la clave requerida: {exception.args[0]}."
        return f"Etapa: {self.name} | Excepcion: {type(exception).__name__} | Mensaje: {message}"
