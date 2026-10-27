"""Isolation des données entre opérateurs et accès non autorisés."""
from django.test import TestCase
from django.urls import reverse

from apps.common.testing import CSV_HEADER, artec_user, csv_upload, make_submission, operator_user, recent_date
from apps.datasets.importer import process_import
from apps.datasets.models import DataSource, ImportBatch


class OperatorDataIsolationTests(TestCase):
    def setUp(self):
        self.d = recent_date()
        src = DataSource.objects.create(name="s", source_type="operator_file")
        self.orange, self.yas = operator_user("orange"), operator_user("yas")
        self.b_orange = process_import(uploaded_file=csv_upload(f"collected_at,score_customer_service\n{self.d},6\n"), user=self.orange, data_source=src, operator_scope=self.orange.operator)
        self.b_yas = process_import(uploaded_file=csv_upload(f"collected_at,score_customer_service\n{self.d},2\n"), user=self.yas, data_source=src, operator_scope=self.yas.operator)

    def test_import_list_only_own(self):
        self.client.force_login(self.orange)
        r = self.client.get(reverse("operator:import_list"))
        self.assertEqual([b.pk for b in r.context["batches"]], [self.b_orange.pk])

    def test_manual_url_change_to_other_operators_import_gives_404(self):
        self.client.force_login(self.orange)
        self.assertEqual(self.client.get(reverse("operator:import_detail", args=[self.b_yas.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("operator:import_errors", args=[self.b_yas.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("operator:import_detail", args=[self.b_orange.pk])).status_code, 200)

    def test_operator_cannot_reach_artec_import_views_to_read_others(self):
        self.client.force_login(self.orange)
        self.assertEqual(self.client.get(reverse("artec:import_detail", args=[self.b_yas.pk])).status_code, 403)

    def test_dashboard_scoped_to_own_operator(self):
        make_submission("orange", {"customer_service": 9})
        make_submission("yas", {"customer_service": 1})
        self.client.force_login(self.orange)
        ctx = self.client.get(reverse("operator:dashboard")).context
        self.assertEqual(ctx["operator"].code, "orange")
        self.assertEqual(ctx["indicators"]["operator"], "orange")
        self.assertEqual(ctx["indicators"]["n_submissions"], 2)  # son import + son avis, rien de Yas

    def test_operator_cannot_pass_operator_parameter_to_see_others(self):
        make_submission("yas", {"customer_service": 1})
        self.client.force_login(self.orange)
        ctx = self.client.get(reverse("operator:dashboard") + "?operator=yas").context
        self.assertEqual(ctx["indicators"]["operator"], "orange")

    def test_operator_cannot_see_artec_feedback_list(self):
        self.client.force_login(self.orange)
        self.assertEqual(self.client.get(reverse("artec:feedback_list")).status_code, 403)

    def test_post_with_foreign_import_pk_rejected(self):
        self.client.force_login(self.orange)
        r = self.client.post(reverse("artec:feedback_validate", args=[make_submission("yas", {"customer_service": 1}, status="to_review").pk]), {"decision": "accept"})
        self.assertEqual(r.status_code, 403)


class PublicPagesTests(TestCase):
    def test_public_pages_render_without_login(self):
        for name in ("public:home", "public:survey_list", "public:results", "public:methodology"):
            self.assertEqual(self.client.get(reverse(name)).status_code, 200, name)

    def test_results_show_period_volume_and_limits_and_flag_small_samples(self):
        for i in range(5):
            make_submission("orange", {"mobile_data_speed": 6})
        r = self.client.get(reverse("public:results"))
        self.assertContains(r, "Échantillon insuffisant")
        self.assertContains(r, "n = 5")
        self.assertContains(r, "période")
        self.assertTrue(r.context["limitations"])
        self.assertEqual(r.context["min_sample"], 30)

    def test_public_results_exclude_operator_imports(self):
        make_submission("orange", {"mobile_data_speed": 6}, source="operator_import")
        ind = self.client.get(reverse("public:results")).context["indicators"]
        self.assertTrue(all(i["n_submissions"] == 0 for i in ind))

    def test_artec_dashboard_renders_with_warnings(self):
        make_submission("orange", {"mobile_data_speed": 6}, status="to_review")
        self.client.force_login(artec_user())
        r = self.client.get(reverse("artec:dashboard"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Avis à examiner")
        self.assertEqual(self.client.get(reverse("artec:operators")).status_code, 200)
        self.assertEqual(self.client.get(reverse("artec:audit")).status_code, 200)
        self.assertEqual(self.client.get(reverse("artec:feedback_list") + "?status=to_review").status_code, 200)

    def test_pagination_applies(self):
        for _ in range(30):
            make_submission("orange", {"mobile_data_speed": 6})
        self.client.force_login(artec_user())
        r = self.client.get(reverse("artec:feedback_list"))
        self.assertEqual(len(r.context["submissions"]), 25)
        self.assertEqual(len(self.client.get(reverse("artec:feedback_list") + "?page=2").context["submissions"]), 5)
