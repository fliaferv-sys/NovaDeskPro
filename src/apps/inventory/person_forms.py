"""Explicit, signed institutional selection; never accept a posted person snapshot."""
from django.core.exceptions import ValidationError

from apps.directory.identity_policies import (
    authorize_identity_context, validate_identity_reference, associated_local_user,
)
from apps.directory.person_references import person_snapshot


class InventoryPersonFormMixin:
    identity_kind = "asset"
    person_field = "assigned_user"
    snapshot_field = "custodian_identity"
    person_required = False

    def __init__(self, *args, request=None, **kwargs):
        self.identity_request = request or getattr(self, "identity_request", None)
        super().__init__(*args, **kwargs)
        if self.person_field in self.fields:
            self.fields[self.person_field].required = False

    def clean(self):
        cleaned = super().clean()
        instance = getattr(self, "instance", None)
        snapshot = getattr(instance, self.snapshot_field, {}) if instance else {}
        reference = self.data.get("institutional_identity_ref", "")
        if reference:
            if self.identity_request is None:
                raise ValidationError("La selección requiere una sesión autorizada.")
            editing = instance is not None and not instance._state.adding
            context = "inventory." + self.identity_kind + (".change" if editing else ".add")
            if getattr(self, "identity_admin", False):
                context = "inventory.admin." + self.identity_kind + (".change" if editing else ".add")
            policy = authorize_identity_context(self.identity_request, context, str(instance.pk) if editing else "")
            identity = validate_identity_reference(self.identity_request, policy, reference)
            cleaned[self.person_field] = associated_local_user(identity)
            snapshot = person_snapshot(identity)
        elif self.data.get("institutional_identity_clear") == "1":
            snapshot = {}
            cleaned[self.person_field] = None
        elif snapshot and cleaned.get(self.person_field) != getattr(instance, self.person_field):
            self.add_error(self.person_field, "Seleccione nuevamente la persona o quite la selección institucional.")
        if self.person_required and not cleaned.get(self.person_field) and not snapshot:
            self.add_error(self.person_field, "Seleccione una persona institucional o una cuenta local.")
        cleaned[self.snapshot_field] = snapshot
        if instance is not None:
            setattr(instance, self.snapshot_field, snapshot)
        self.person_reference = snapshot
        return cleaned

    def identity_context_data(self):
        instance = getattr(self, "instance", None)
        editing = instance is not None and not instance._state.adding
        return dict(identity_context="inventory." + self.identity_kind + (".change" if editing else ".add"),
                    identity_object_id=str(instance.pk) if editing else "", identity_mode="change" if editing else "add",
                    identity_reference=self.data.get("institutional_identity_ref", ""),
                    identity_clear_reference=self.data.get("institutional_identity_clear", ""),
                    identity_field_map={"local_user_id": self.person_field}, identity_config_id="inventory-person-map",
                    identity_explicit_only=True, identity_clear_fields=True, identity_bound=self.is_bound)


class InventoryPersonAdminMixin:
    change_form_template = "admin/inventory/person_form.html"
    identity_kind = "asset"
    person_field = "assigned_user"
    snapshot_field = "custodian_identity"
    person_required = False

    def get_form(self, request, obj=None, **kwargs):
        base = super().get_form(request, obj, **kwargs)
        return type("InventoryPersonForm", (InventoryPersonFormMixin, base), {
            "identity_request": request, "identity_admin": True, "identity_kind": self.identity_kind,
            "person_field": self.person_field, "snapshot_field": self.snapshot_field,
            "person_required": self.person_required,
        })

    def render_change_form(self, request, context, add=False, change=False, form_url="", obj=None):
        context.update(context["adminform"].form.identity_context_data())
        context["identity_context"] = "inventory.admin." + self.identity_kind + (".add" if add else ".change")
        context["current_person"] = getattr(obj, self.snapshot_field, {}).get("name") if obj else ""
        return super().render_change_form(request, context, add, change, form_url, obj)
