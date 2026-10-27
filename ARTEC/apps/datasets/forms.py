from django import forms

from .models import DataSource, DataSourceType


class ImportForm(forms.Form):
    file = forms.FileField(label="Fichier CSV ou Excel (.xlsx)")

    def __init__(self, *args, artec=False, **kwargs):
        super().__init__(*args, **kwargs)
        if artec:
            self.fields["data_source"] = forms.ModelChoiceField(
                queryset=DataSource.objects.filter(is_active=True).exclude(source_type=DataSourceType.PUBLIC_FORM),
                label="Source de données (provenance)",
            )


class DataSourceForm(forms.ModelForm):
    class Meta:
        model = DataSource
        fields = ["name", "source_type", "provenance", "collected_from", "collected_to", "usage_limits", "legal_basis", "is_active"]
        widgets = {"collected_from": forms.DateInput(attrs={"type": "date"}), "collected_to": forms.DateInput(attrs={"type": "date"})}

    def clean_source_type(self):
        st = self.cleaned_data["source_type"]
        if st == DataSourceType.PUBLIC_FORM:
            raise forms.ValidationError("Cette source est réservée au formulaire public.")
        return st

    def clean(self):
        c = super().clean()
        if c.get("source_type") in (DataSourceType.SOCIAL_EXPORT, DataSourceType.OFFICIAL_API) and not c.get("legal_basis"):
            self.add_error("legal_basis", "Précisez l'autorisation / les conditions d'accès (API officielle, export autorisé).")
        if c.get("collected_from") and c.get("collected_to") and c["collected_to"] < c["collected_from"]:
            self.add_error("collected_to", "La date de fin précède celle de début.")
        return c
