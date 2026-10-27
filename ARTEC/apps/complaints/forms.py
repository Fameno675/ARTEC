from django import forms

from apps.operators.models import Operator

from .models import ComplaintStatus, DecisionType


class ComplaintForm(forms.Form):
    target_operator = forms.ModelChoiceField(queryset=Operator.objects.none(), label="Opérateur concerné")
    subject = forms.CharField(max_length=200, label="Objet")
    description = forms.CharField(widget=forms.Textarea(attrs={"rows": 6}), min_length=30, label="Description des faits allégués")
    observed_from = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}), label="Observé du")
    observed_to = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}), label="au")

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["target_operator"].queryset = Operator.objects.active().exclude(pk=user.operator_id)

    def clean(self):
        c = super().clean()
        if c.get("observed_from") and c.get("observed_to") and c["observed_to"] < c["observed_from"]:
            self.add_error("observed_to", "La date de fin précède celle de début.")
        return c


class AttachmentForm(forms.Form):
    file = forms.FileField(label="Pièce justificative")


class MessageForm(forms.Form):
    note = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}), max_length=3000, label="Message")


class StatusForm(forms.Form):
    status = forms.ChoiceField(choices=ComplaintStatus.choices)
    note = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}))
    visible_to_complainant = forms.BooleanField(required=False, initial=True)


class DecisionForm(forms.Form):
    decision_type = forms.ChoiceField(choices=DecisionType.choices)
    evidence_summary = forms.CharField(widget=forms.Textarea(attrs={"rows": 4}), label="Résumé des preuves vérifiables")
