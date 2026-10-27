from django import forms

from apps.operators.models import Operator

from .models import Criterion, SurveyForm, SurveyFormCriterion


class PublicFeedbackForm(forms.Form):
    operator = forms.ModelChoiceField(
        queryset=Operator.objects.none(), to_field_name="code", label="Opérateur évalué", empty_label="— Choisir —"
    )
    comment = forms.CharField(label="Commentaire (facultatif, sans donnée personnelle)", max_length=500, required=False,
                              widget=forms.Textarea(attrs={"rows": 3, "class": "form-control"}))
    form_ts = forms.CharField(widget=forms.HiddenInput, required=False)
    website = forms.CharField(required=False, label="Ne pas remplir", widget=forms.TextInput(attrs={"autocomplete": "off", "tabindex": "-1"}))

    def __init__(self, *args, survey: SurveyForm, **kwargs):
        super().__init__(*args, **kwargs)
        self.survey = survey
        self.fields["operator"].queryset = Operator.objects.active()
        self.fields["operator"].widget.attrs["class"] = "form-select"
        self.criteria = [sc.criterion for sc in survey.survey_criteria.select_related("criterion") if sc.criterion.is_active]
        for crit in self.criteria:
            self.fields[f"score_{crit.code}"] = forms.IntegerField(
                label=crit.label, help_text=crit.description, required=False, min_value=0, max_value=10,
                widget=forms.NumberInput(attrs={"min": 0, "max": 10, "class": "form-control", "placeholder": "0-10"}),
            )

    @property
    def criteria_fields(self):
        return [{"criterion": c, "field": self[f"score_{c.code}"]} for c in self.criteria]

    def clean(self):
        cleaned = super().clean()
        scores = self.scores(cleaned)
        if not scores and not self.errors:
            raise forms.ValidationError("Notez au moins un critère (de 0 à 10).")
        return cleaned

    def scores(self, cleaned=None):
        cleaned = cleaned if cleaned is not None else self.cleaned_data
        return {c.code: cleaned.get(f"score_{c.code}") for c in self.criteria if cleaned.get(f"score_{c.code}") is not None}


class SurveyAdminForm(forms.ModelForm):
    criteria_selection = forms.ModelMultipleChoiceField(
        queryset=Criterion.objects.filter(is_active=True), label="Critères", widget=forms.CheckboxSelectMultiple
    )

    class Meta:
        model = SurveyForm
        fields = ["title", "slug", "description", "starts_at", "ends_at", "is_active"]
        widgets = {
            "starts_at": forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
            "ends_at": forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields["criteria_selection"].initial = list(self.instance.criteria.values_list("pk", flat=True))

    def clean(self):
        cleaned = super().clean()
        s, e = cleaned.get("starts_at"), cleaned.get("ends_at")
        if s and e and e <= s:
            self.add_error("ends_at", "La fin doit être postérieure au début.")
        return cleaned

    def save(self, commit=True):
        survey = super().save(commit=commit)
        if commit:
            selected = list(self.cleaned_data["criteria_selection"])
            SurveyFormCriterion.objects.filter(survey_form=survey).exclude(criterion__in=selected).delete()
            for pos, crit in enumerate(selected, start=1):
                SurveyFormCriterion.objects.update_or_create(survey_form=survey, criterion=crit, defaults={"position": pos})
        return survey
