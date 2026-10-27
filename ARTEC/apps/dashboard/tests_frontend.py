"""Tests du frontend : rendu de toutes les pages, CSRF, fichiers statiques, données de graphiques, pages d'erreur."""
import json
import re
from datetime import date, timedelta

from django.contrib.staticfiles import finders
from django.core.management import call_command
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.analytics import services as ml
from apps.common.testing import artec_user, op, operator_user, make_user, csv_upload, recent_date
from apps.complaints.models import Complaint
from apps.datasets.models import ImportBatch

STATIC_RE = re.compile(r'(?:href|src)="/static/([^"?#]+)')
FORM_POST_RE = re.compile(r'<form[^>]*method="post"[^>]*>(.*?)</form>', re.S | re.I)


class DemoMixin:
    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo_data", yes=True, force=True, verbosity=0)
        cls.artec = artec_user()
        cls.orange = operator_user("orange")
        cls.batch = ml.create_batch(requested_by=cls.artec, operator=None, start=date.today() - timedelta(days=200), end=date.today())
        ml.execute_batch(cls.batch)
        cls.complaint = Complaint.objects.first()


def pages(case):
    """(rôle, url, nom) de toutes les pages GET du frontend."""
    r = case.complaint.reference
    return [
        ("anon", reverse("public:home"), "home"), ("anon", reverse("public:survey_list"), "survey_list"),
        ("anon", reverse("public:survey_detail", args=["satisfaction-generale"]), "survey_detail"),
        ("anon", reverse("public:survey_thanks", args=["satisfaction-generale"]), "thanks"),
        ("anon", reverse("public:results"), "results"), ("anon", reverse("public:results") + "?operator=orange&granularity=week", "results_filtered"),
        ("anon", reverse("public:methodology"), "methodology"), ("anon", reverse("accounts:login"), "login"),
        ("operator", reverse("operator:dashboard"), "op_dashboard"), ("operator", reverse("operator:import_list"), "op_import_list"),
        ("operator", reverse("operator:import_create"), "op_import_create"), ("operator", reverse("operator:complaint_list"), "op_complaint_list"),
        ("operator", reverse("operator:complaint_create"), "op_complaint_create"), ("operator", reverse("operator:complaint_detail", args=[r]), "op_complaint_detail"),
        ("operator", reverse("accounts:password_change"), "password"),
        ("artec", reverse("artec:dashboard"), "artec_dashboard"), ("artec", reverse("artec:feedback_list") + "?status=to_review", "feedback_list"),
        ("artec", reverse("artec:operators"), "operators"), ("artec", reverse("artec:audit"), "audit"),
        ("artec", reverse("artec:survey_list"), "survey_list_a"), ("artec", reverse("artec:survey_create"), "survey_form"),
        ("artec", reverse("artec:import_list"), "import_list"), ("artec", reverse("artec:import_create"), "import_create"),
        ("artec", reverse("artec:source_list"), "source_list"), ("artec", reverse("artec:source_create"), "source_form"),
        ("artec", reverse("artec:complaint_list"), "complaint_list"), ("artec", reverse("artec:complaint_detail", args=[r]), "complaint_detail"),
        ("artec", reverse("artec:mlbatch_list"), "mlbatch_list"), ("artec", reverse("artec:mlbatch_detail", args=[case.batch.pk]), "mlbatch_detail"),
        ("artec", reverse("artec:mlbatch_detail", args=[case.batch.pk]) + "?anomalies=1", "mlbatch_detail_anom"),
    ]


class RenderEveryPageTests(DemoMixin, TestCase):
    def login(self, role):
        self.client.logout()
        if role == "operator":
            self.client.force_login(self.orange)
        elif role == "artec":
            self.client.force_login(self.artec)

    def test_every_page_renders_with_structure(self):
        for role, url, name in pages(self):
            self.login(role)
            r = self.client.get(url)
            self.assertEqual(r.status_code, 200, f"{name} {url}")
            html = r.content.decode()
            self.assertIn('<html lang="fr">', html, name)
            self.assertIn('id="contenu"', html, name)
            self.assertIn("ar-skip-link", html, name)
            self.assertEqual(len(re.findall(r"<h1[ >]", html)), 1, f"{name}: un seul h1")
            self.assertNotIn("cdn.jsdelivr", html, name)           # aucune dépendance CDN
            self.assertNotIn("{{", html, name)                      # aucune variable non rendue
            self.assertNotIn("{%", html, name)
            for img in re.findall(r"<img[^>]*>", html):
                self.assertIn("alt=", img, f"{name}: image sans alt")

    def test_every_post_form_has_csrf_token(self):
        for role, url, name in pages(self):
            self.login(role)
            html = self.client.get(url).content.decode()
            for body in FORM_POST_RE.findall(html):
                self.assertIn("csrfmiddlewaretoken", body, f"{name}: formulaire POST sans CSRF")

    def test_all_referenced_static_files_exist(self):
        seen = set()
        for role, url, name in pages(self):
            self.login(role)
            seen.update(STATIC_RE.findall(self.client.get(url).content.decode()))
        self.assertGreater(len(seen), 8)
        for path in seen:
            self.assertIsNotNone(finders.find(path), f"fichier statique introuvable : {path}")

    def test_private_pages_never_rendered_for_wrong_role(self):
        for role, url, name in pages(self):
            if role == "anon" or name == "password":      # changement de mot de passe : tout compte connecté
                continue
            self.client.logout()
            self.assertEqual(self.client.get(url).status_code, 302, name)         # anonyme -> connexion
            self.client.force_login(make_user("operator", "yas") if role == "artec" else self.artec)
            self.assertEqual(self.client.get(url).status_code, 403, name)         # mauvais rôle

    def test_logout_is_post_form_not_link(self):
        self.login("operator")
        html = self.client.get(reverse("operator:dashboard")).content.decode()
        self.assertIn(f'action="{reverse("accounts:logout")}"', html)
        self.assertNotRegex(html, r'<a[^>]+href="/compte/deconnexion/')


class DataForChartsTests(DemoMixin, TestCase):
    def script_json(self, html, sid):
        m = re.search(rf'<script id="{sid}" type="application/json">(.*?)</script>', html, re.S)
        self.assertIsNotNone(m, f"script JSON {sid} absent")
        return json.loads(m.group(1))

    def test_public_results_data_is_real_and_complete(self):
        html = self.client.get(reverse("public:results")).content.decode()
        inds = self.script_json(html, "indicators-data")
        self.assertEqual({i["operator"] for i in inds}, {"orange", "yas", "airtel"})
        by = {i["operator"]: i for i in inds}
        self.assertTrue(by["orange"]["sample_sufficient"])
        self.assertFalse(by["airtel"]["sample_sufficient"])                 # volontairement petit dans la démo
        self.assertTrue(all("series" in i and "operator_name" in i for i in inds))
        cmap = self.script_json(html, "criteria-map")
        self.assertEqual(len(cmap), 10)
        self.assertIn("mobile_data_speed", cmap)
        omap = self.script_json(html, "operators-map")
        self.assertEqual(set(omap), {"orange", "yas", "airtel"})
        self.assertEqual(sorted(o["index"] for o in omap.values()), [0, 1, 2])

    def test_airtel_flagged_not_ranked_in_page(self):
        html = self.client.get(reverse("public:results")).content.decode()
        self.assertIn("Échantillon insuffisant", html)
        self.assertIn("petit échantillon", html)

    def test_artec_dashboard_data_series_sources_import(self):
        self.client.force_login(self.artec)
        r = self.client.get(reverse("artec:dashboard"))
        html = r.content.decode()
        inds = self.script_json(html, "indicators-data")
        self.assertTrue(all(i["series"] for i in inds if i["n_submissions"]))
        self.assertIn("external_import", self.script_json(html, "sources-data"))
        imp = self.script_json(html, "import-data")
        self.assertIn("rejected_rows", imp)
        self.assertEqual(set(self.script_json(html, "complaints-data")), {"received", "under_review", "info_requested", "closed", "rejected"})
        self.assertIn("Avis à examiner", html)
        self.assertIn("pas une preuve", html.replace("n’est pas une preuve", "pas une preuve").replace("ne prouve ni", "pas une preuve"))

    def test_operator_dashboard_scoped_data_only(self):
        self.client.force_login(self.orange)
        html = self.client.get(reverse("operator:dashboard")).content.decode()
        ind = self.script_json(html, "indicators-data")
        self.assertEqual(ind["operator"], "orange")
        self.assertNotIn('"operator": "yas"', html)                    # aucune donnée d'un autre opérateur
        self.assertIn("<h3 id=\"ind-orange-1\">Orange Madagascar</h3>", html)   # nom lisible, pas le code
        self.assertIsInstance(self.script_json(html, "series-data"), list)

    def test_import_detail_batch_json_matches_batch(self):
        from apps.datasets.importer import process_import
        from apps.datasets.models import DataSource
        d = recent_date()
        body = "collected_at,score_customer_service\n" + "".join(f"{d},{i}\n" for i in range(9)) + f"{d},99\n"
        b = process_import(uploaded_file=csv_upload(body), user=self.orange, data_source=DataSource.objects.create(name="x", source_type="operator_file"), operator_scope=self.orange.operator)
        self.client.force_login(self.orange)
        html = self.client.get(reverse("operator:import_detail", args=[b.pk])).content.decode()
        data = self.script_json(html, "batch-data")
        self.assertEqual((data["accepted_rows"], data["rejected_rows"]), (9, 1))
        self.assertIn("hors de l", html); self.assertIn("chelle 0-10", html)           # code traduit en français, pas de code brut
        self.assertNotIn("<li>score_out_of_range</li>", html)
        self.assertIn(reverse("operator:import_errors", args=[b.pk]), html)
        # même gabarit réutilisé côté ARTEC avec les bonnes URL
        self.client.force_login(self.artec)
        html = self.client.get(reverse("artec:import_detail", args=[b.pk])).content.decode()
        self.assertIn(reverse("artec:import_errors", args=[b.pk]), html)
        self.assertNotIn("/operateur/", html.split("<main")[1])


class FormPagesTests(DemoMixin, TestCase):
    def test_survey_form_hooks_and_backend_field_names(self):
        html = self.client.get(reverse("public:survey_detail", args=["satisfaction-generale"])).content.decode()
        self.assertEqual(html.count("data-score-field"), 10)
        for code in ("mobile_data_speed", "mobile_data_stability", "mobile_data_availability", "call_audio_quality", "call_success_stability",
                     "sms_reliability", "pricing_value", "credit_purchase_ease", "mobile_money_reliability", "customer_service"):
            self.assertIn(f'name="score_{code}"', html)
        for name in ("operator", "comment", "form_ts", "website"):
            self.assertIn(f'name="{name}"', html)
        for code in ("orange", "yas", "airtel"):
            self.assertIn(f'value="{code}"', html)
        self.assertIn("data-feedback-form", html)
        self.assertIn('role="progressbar"', html)
        self.assertIn("hp-field", html)
        self.assertIn("pseudonymisé", html)                                     # information de confidentialité

    def test_form_without_js_still_posts_valid_data(self):
        """Les champs natifs (select + number) restent soumettables : le JS n'est qu'une amélioration."""
        from unittest import mock
        from apps.feedback import antispam
        url = reverse("public:survey_detail", args=["satisfaction-generale"])
        with mock.patch("apps.feedback.antispam.time.time", return_value=1000.0):
            tok = antispam.make_form_token()
        with mock.patch("apps.feedback.antispam.time.time", return_value=1020.0):
            r = self.client.post(url, {"operator": "yas", "score_customer_service": "6", "comment": "", "website": "", "form_ts": tok})
        self.assertEqual(r.status_code, 302)

    def test_server_errors_displayed_accessibly(self):
        url = reverse("public:survey_detail", args=["satisfaction-generale"])
        r = self.client.post(url, {"operator": "yas", "score_customer_service": "11", "website": ""})
        html = r.content.decode()
        self.assertIn('role="alert"', html)
        self.assertIn("ar-field-error", html)
        self.assertIn('aria-invalid="true"', html)

    def test_import_forms_declare_limits_and_columns(self):
        self.client.force_login(self.artec)
        html = self.client.get(reverse("artec:import_create")).content.decode()
        self.assertIn('data-required-columns="collected_at,operator_code"', html)
        self.assertIn('enctype="multipart/form-data"', html)
        self.assertIn('id="import-columns"', html)
        self.assertIn("score_mobile_data_speed", html)
        self.client.force_login(self.orange)
        html = self.client.get(reverse("operator:import_create")).content.decode()
        self.assertIn('data-required-columns="collected_at"', html)
        self.assertNotIn('name="data_source"', html)

    def test_destructive_actions_ask_for_confirmation(self):
        self.client.force_login(self.artec)
        self.assertIn("data-confirm", self.client.get(reverse("artec:complaint_detail", args=[self.complaint.reference])).content.decode())
        self.assertIn("data-confirm", self.client.get(reverse("artec:mlbatch_list")).content.decode())
        self.assertIn("data-confirm", self.client.get(reverse("artec:feedback_list") + "?status=to_review").content.decode())
        self.assertIn('id="ar-confirm-modal"', self.client.get(reverse("artec:dashboard")).content.decode())

    def test_django_messages_are_displayed_after_action(self):
        self.client.force_login(self.artec)
        r = self.client.post(reverse("artec:complaint_status", args=[self.complaint.reference]), {"status": "under_review", "visible_to_complainant": "on"}, follow=True)
        self.assertContains(r, "Statut mis à jour.")
        self.assertContains(r, 'role="status"')
        r = self.client.post(reverse("artec:complaint_decision", args=[self.complaint.reference]), {"decision_type": "no_action", "evidence_summary": "court"}, follow=True)
        self.assertContains(r, 'role="alert"')


class MlReviewScreenTests(DemoMixin, TestCase):
    def test_alert_screen_distinguishes_phases_and_never_claims_proof(self):
        self.client.force_login(self.artec)
        html = self.client.get(reverse("artec:mlbatch_detail", args=[self.batch.pk]) + "?anomalies=1").content.decode()
        self.assertIn("1. Anomalie détectée", html)
        self.assertIn("2. Vérification en cours", html)
        self.assertIn("3. Décision humaine", html)
        self.assertIn("<strong>n’est pas une probabilité</strong>", html)
        self.assertIn("Observations justificatives", html)
        self.assertIn('name="outcome"', html)
        self.assertNotRegex(html.lower(), r"infraction (prouvée|avérée|confirmée)")

    def test_mlbatch_detail_query_count_is_bounded(self):
        self.client.force_login(self.artec)
        with CaptureQueriesContext(connection) as q:
            self.client.get(reverse("artec:mlbatch_detail", args=[self.batch.pk]))
        self.assertLess(len(q), 30, f"{len(q)} requêtes : N+1 probable")

    def test_unavailable_engine_banner(self):
        from django.test import override_settings
        with override_settings(ML_ENGINE_BACKEND="unavailable"):
            b = ml.create_batch(requested_by=self.artec, operator=None, start=date.today() - timedelta(days=5), end=date.today())
            ml.execute_batch(b)
        self.client.force_login(self.artec)
        html = self.client.get(reverse("artec:mlbatch_detail", args=[b.pk])).content.decode()
        self.assertIn("Analyse en attente ou en échec", html)
        self.assertIn("données sont intactes", html)
        self.assertIn("en attente ou en échec", self.client.get(reverse("artec:dashboard")).content.decode())


class ErrorPagesTests(TestCase):
    def test_404_custom(self):
        r = self.client.get("/page-qui-n-existe-pas/")
        self.assertEqual(r.status_code, 404)
        self.assertContains(r, "Page introuvable", status_code=404)

    def test_403_custom_for_wrong_role(self):
        self.client.force_login(operator_user("yas"))
        r = self.client.get(reverse("artec:dashboard"))
        self.assertContains(r, "Accès refusé", status_code=403)

    def test_csrf_failure_page(self):
        from django.test import Client, override_settings
        c = Client(enforce_csrf_checks=True)
        with override_settings(CSRF_FAILURE_VIEW="django.views.csrf.csrf_failure"):
            r = c.post(reverse("accounts:login"), {})
        self.assertEqual(r.status_code, 403)
        self.assertContains(r, "session a expiré", status_code=403)

    def test_500_template_is_standalone_and_valid(self):
        from django.template.loader import render_to_string
        html = render_to_string("500.html")
        self.assertIn("Une erreur est survenue", html)
        self.assertNotIn("{%", html)

    def test_429_page(self):
        from django.template.loader import render_to_string
        self.assertIn("429", render_to_string("public/too_many.html"))


class ChartAttributesWellFormedTests(DemoMixin, TestCase):
    """Régression : des guillemets non échappés dans data-labels / data-parts cassaient les graphiques dans le navigateur."""

    def chart_nodes(self, html):
        from html.parser import HTMLParser

        nodes = []

        class P(HTMLParser):
            def handle_starttag(self, tag, attrs):
                d = dict(attrs)
                if "data-chart" in d:
                    nodes.append(d)

        P().feed(html)
        return nodes

    def test_json_attributes_parse_on_every_chart(self):
        self.client.force_login(self.artec)
        urls = [reverse("artec:dashboard"), reverse("artec:import_detail", args=[self._import().pk])]
        total = 0
        for url in urls:
            for attrs in self.chart_nodes(self.client.get(url).content.decode()):
                total += 1
                for key in ("data-labels", "data-parts"):
                    if attrs.get(key):
                        self.assertIsInstance(json.loads(attrs[key]), (dict, list), f"{key} invalide sur {url}")
        self.assertGreaterEqual(total, 6)

    def test_french_labels_and_parts_present(self):
        self.client.force_login(self.artec)
        nodes = self.chart_nodes(self.client.get(reverse("artec:dashboard")).content.decode())
        labels = [json.loads(n["data-labels"]) for n in nodes if n.get("data-labels")]
        self.assertTrue(any(l.get("received") == "Reçues" for l in labels))
        parts = [json.loads(n["data-parts"]) for n in nodes if n.get("data-parts")]
        self.assertTrue(any(p[0]["key"] == "accepted_rows" for p in parts))

    def _import(self):
        from apps.datasets.importer import process_import
        from apps.datasets.models import DataSource
        d = recent_date()
        return process_import(uploaded_file=csv_upload("collected_at,score_customer_service\n" + "".join(f"{d},{i}\n" for i in range(5))),
                              user=self.orange, data_source=DataSource.objects.create(name="y", source_type="operator_file"), operator_scope=self.orange.operator)
