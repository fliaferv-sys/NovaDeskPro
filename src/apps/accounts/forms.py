from apps.directory.identity_policies import authorize_identity_context, validate_identity_reference


class InstitutionalIdentityValidationMixin:
    """Validate source identifiers without rewriting administrator-entered fields."""
    def clean(self):
        cleaned_data = super().clean()
        reference = self.data.get("institutional_identity_ref", "")
        if reference:
            request = self.identity_request
            context = "accounts.change" if self.instance.pk and not self.instance._state.adding else "accounts.add"
            object_id = str(self.instance.pk) if context == "accounts.change" else ""
            policy = authorize_identity_context(request, context, object_id)
            self.selected_institutional_identity = validate_identity_reference(request, policy, reference)
        return cleaned_data
