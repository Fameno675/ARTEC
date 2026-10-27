"""Toutes les routes, regroupées par espace de noms : public, accounts, operator, artec."""
from django.urls import path

from apps.accounts import views as acc
from apps.analytics import views as ml
from apps.complaints import views as cpl
from apps.datasets import views as ds
from apps.feedback import views as fb

from . import views as dash

public_patterns = [
    path("", dash.home, name="home"),
    path("sondages/", fb.survey_list, name="survey_list"),
    path("sondages/<slug:slug>/", fb.survey_detail, name="survey_detail"),
    path("sondages/<slug:slug>/merci/", fb.survey_thanks, name="survey_thanks"),
    path("resultats/", dash.results, name="results"),
    path("methodologie/", dash.methodology, name="methodology"),
]

accounts_patterns = [
    path("connexion/", acc.LoginView.as_view(), name="login"),
    path("deconnexion/", acc.LogoutView.as_view(), name="logout"),
    path("mot-de-passe/", acc.PasswordChangeView.as_view(), name="password_change"),
    path("redirection/", acc.home_redirect, name="home_redirect"),
]

operator_patterns = [
    path("", dash.operator_dashboard, name="dashboard"),
    path("imports/", ds.operator_import_list, name="import_list"),
    path("imports/nouveau/", ds.operator_import_create, name="import_create"),
    path("imports/modele.csv", ds.operator_import_template, name="import_template"),
    path("imports/<uuid:pk>/", ds.operator_import_detail, name="import_detail"),
    path("imports/<uuid:pk>/erreurs.csv", ds.operator_import_errors, name="import_errors"),
    path("reclamations/", cpl.operator_complaint_list, name="complaint_list"),
    path("reclamations/nouvelle/", cpl.operator_complaint_create, name="complaint_create"),
    path("reclamations/<str:reference>/", cpl.operator_complaint_detail, name="complaint_detail"),
    path("reclamations/<str:reference>/pieces/", cpl.operator_complaint_attach, name="complaint_attach"),
    path("reclamations/<str:reference>/message/", cpl.operator_complaint_reply, name="complaint_reply"),
    path("reclamations/<str:reference>/pieces/<int:pk>/", cpl.operator_attachment_download, name="attachment_download"),
]

artec_patterns = [
    path("", dash.artec_dashboard, name="dashboard"),
    path("avis/", dash.artec_feedback_list, name="feedback_list"),
    path("avis/<uuid:pk>/validation/", fb.artec_feedback_validate, name="feedback_validate"),
    path("operateurs/", dash.artec_operators, name="operators"),
    path("audit/", dash.artec_audit, name="audit"),
    path("sondages/", fb.artec_survey_list, name="survey_list"),
    path("sondages/nouveau/", fb.artec_survey_edit, name="survey_create"),
    path("sondages/<int:pk>/", fb.artec_survey_edit, name="survey_edit"),
    path("imports/", ds.artec_import_list, name="import_list"),
    path("imports/nouveau/", ds.artec_import_create, name="import_create"),
    path("imports/modele.csv", ds.artec_import_template, name="import_template"),
    path("imports/<uuid:pk>/", ds.artec_import_detail, name="import_detail"),
    path("imports/<uuid:pk>/erreurs.csv", ds.artec_import_errors, name="import_errors"),
    path("sources/", ds.artec_source_list, name="source_list"),
    path("sources/nouveau/", ds.artec_source_create, name="source_create"),
    path("reclamations/", cpl.artec_complaint_list, name="complaint_list"),
    path("reclamations/<str:reference>/", cpl.artec_complaint_detail, name="complaint_detail"),
    path("reclamations/<str:reference>/statut/", cpl.artec_complaint_status, name="complaint_status"),
    path("reclamations/<str:reference>/decision/", cpl.artec_complaint_decision, name="complaint_decision"),
    path("reclamations/<str:reference>/pieces/<int:pk>/", cpl.artec_attachment_download, name="attachment_download"),
    path("recommandations/", ml.recommendations, name="recommendations"),
    path("analyses/", ml.mlbatch_list, name="mlbatch_list"),
    path("analyses/predictions/<int:pk>/revue/", ml.prediction_review, name="prediction_review"),
    path("analyses/<uuid:pk>/", ml.mlbatch_detail, name="mlbatch_detail"),
]
