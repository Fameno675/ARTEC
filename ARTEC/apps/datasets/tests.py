import io
from unittest import mock

from django.test import TestCase, override_settings
from django.urls import reverse

from apps.audit.models import AuditLog
from apps.common.testing import (CSV_HEADER, artec_user, csv_upload, make_submission, operator_user, recent_date, xlsx_upload)
from apps.datasets.importer import error_report_csv, process_import
from apps.datasets.models import DataSource, ImportBatch, ImportRowResult
from apps.feedback.models import FeedbackRating, FeedbackSubmission
from apps.operators.models import Operator


def artec_source(t="artec_file"):
    return DataSource.objects.create(name=f"src-{t}", source_type=t, provenance="test")


def op_source(code="orange"):
    return DataSource.objects.create(name=f"op-{code}", source_type="operator_file")


class ImportCsvTests(TestCase):
    def setUp(self):
        self.admin = artec_user()
        self.src = artec_source()
        self.d = recent_date()

    def run_artec(self, body, name="data.csv"):
        return process_import(uploaded_file=csv_upload(CSV_HEADER + "\n" + body, name), user=self.admin, data_source=self.src)

    def test_valid_csv_committed_with_metadata(self):
        b = self.run_artec(f"E1,orange,{self.d},7,6,8,ok\nE2,yas,{self.d},3,,9,\n")
        self.assertEqual(b.status, "committed")
        self.assertEqual((b.total_rows, b.accepted_rows, b.rejected_rows, b.review_rows), (2, 2, 0, 0))
        self.assertEqual(FeedbackSubmission.objects.filter(import_batch=b).count(), 2)
        self.assertEqual(FeedbackRating.objects.count(), 5)  # note vide = non évalué
        self.assertEqual(b.uploaded_by, self.admin)
        self.assertEqual(b.original_filename, "data.csv")
        self.assertEqual(len(b.file_sha256), 64)
        self.assertEqual(b.data_source, self.src)
        self.assertTrue(b.finished_at)
        sub = FeedbackSubmission.objects.get(external_id="E1")
        self.assertEqual(sub.source, "artec_import")
        self.assertEqual(sub.data_source, self.src)
        self.assertTrue(AuditLog.objects.filter(action="import.committed").exists())

    def test_semicolon_and_bom_supported(self):
        text = "\ufeff" + CSV_HEADER.replace(",", ";") + f"\nE1;orange;{self.d};7;6;8;x\n"
        b = process_import(uploaded_file=csv_upload(text), user=self.admin, data_source=self.src)
        self.assertEqual(b.status, "committed")

    def test_header_case_insensitive_and_unknown_columns_warn(self):
        text = f"EXTERNAL_ID,Operator_Code,Collected_At,Score_Mobile_Data_Speed,bogus\nE1,orange,{self.d},5,zzz\n"
        b = process_import(uploaded_file=csv_upload(text), user=self.admin, data_source=self.src)
        self.assertEqual(b.status, "committed")
        self.assertTrue(any("bogus" in w for w in b.error_summary["warnings"]))

    def test_missing_required_columns_fails_whole_file(self):
        b = process_import(uploaded_file=csv_upload("operator_code,score_mobile_data_speed\norange,5\n"), user=self.admin, data_source=self.src)
        self.assertEqual(b.status, "failed")
        self.assertEqual(b.error_summary["error"], "missing_columns")
        self.assertEqual(FeedbackSubmission.objects.count(), 0)

    def test_no_score_columns_fails(self):
        b = process_import(uploaded_file=csv_upload("operator_code,collected_at\norange,2026-01-01\n"), user=self.admin, data_source=self.src)
        self.assertEqual(b.error_summary["error"], "no_score_columns")

    def test_invalid_rows_classified_with_codes(self):
        good = "".join(f"G{i},orange,{self.d},{i % 10},5,5,\n" for i in range(50))
        bad = (f"B1,orange,{self.d},11,5,5,\n"       # hors échelle
               f"B2,orange,{self.d},-1,5,5,\n"
               f"B3,orange,{self.d},7.5,5,5,\n"      # décimal
               f"B4,orange,{self.d},abc,5,5,\n"
               f"B5,orange,2999-01-01,5,5,5,\n"      # futur
               f"B6,orange,pas-une-date,5,5,5,\n"
               f"B7,orange,{self.d},,,,\n"           # aucune note
               f"B8,inconnu,{self.d},5,5,5,\n"
               f"B9,,{self.d},5,5,5,\n"
               f"B10,orange,2010-01-01,5,5,5,\n")    # trop ancienne
        b = self.run_artec(good + bad)
        self.assertEqual(b.status, "committed")
        self.assertEqual((b.accepted_rows, b.rejected_rows), (50, 10))
        codes = {r.row_number: r.error_codes for r in b.rows.filter(status="rejected")}
        flat = [c for v in codes.values() for c in v]
        for expected in ("score_out_of_range", "score_not_integer", "score_invalid", "date_in_future", "date_invalid",
                         "no_scores", "operator_unknown", "operator_missing", "date_too_old"):
            self.assertIn(expected, flat)
        self.assertEqual(FeedbackSubmission.objects.filter(import_batch=b).count(), 50)  # rien de rejeté en base

    def test_scores_stored_only_between_0_and_10(self):
        self.run_artec(f"E1,orange,{self.d},0,10,5,\n")
        self.assertEqual(sorted(FeedbackRating.objects.values_list("score", flat=True)), [0, 5, 10])

    def test_duplicates_inside_file_rejected(self):
        body = "".join(f"G{i},orange,{self.d},{i},5,5,\n" for i in range(1, 9))
        b = self.run_artec(body + f"G1,orange,{self.d},1,5,5,\n")
        self.assertEqual(b.duplicate_rows, 1)
        self.assertEqual(b.rows.get(row_number=10).error_codes, ["duplicate_in_file"])
        self.assertEqual(FeedbackSubmission.objects.count(), 8)

    def test_duplicates_against_database_rejected(self):
        body = "".join(f"G{i},orange,{self.d},{i},5,5,\n" for i in range(1, 11))
        self.run_artec(body)
        again = f"G1,orange,{self.d},1,5,5,\n" + "".join(f"N{i},orange,{self.d},{i},9,1,\n" for i in range(1, 10))
        b2 = self.run_artec(again)
        self.assertEqual(b2.status, "committed")
        self.assertEqual(b2.duplicate_rows, 1)
        self.assertEqual(b2.rows.get(row_number=2).error_codes, ["duplicate_in_db"])
        self.assertEqual(FeedbackSubmission.objects.count(), 19)

    def test_mostly_duplicate_file_refused_as_whole(self):
        body = "".join(f"G{i},orange,{self.d},{i},5,5,\n" for i in range(1, 10))
        self.run_artec(body)
        b2 = self.run_artec(body)  # 100 % de doublons
        self.assertEqual(b2.status, "failed")
        self.assertEqual(b2.duplicate_rows, 9)
        self.assertEqual(FeedbackSubmission.objects.count(), 9)

    def test_identical_file_triggers_warning(self):
        body = "".join(f"G{i},orange,{self.d},{i},5,5,\n" for i in range(1, 10))
        b1 = self.run_artec(body)
        self.assertEqual(b1.status, "committed")
        b2 = self.run_artec(body)
        self.assertEqual(b1.file_sha256, b2.file_sha256)
        self.assertIn("Un fichier identique", " ".join(b2.error_summary.get("warnings", [])))

    def test_dedup_without_external_id_uses_content_hash(self):
        body = f",orange,{self.d},6,5,4,\n" * 1 + "".join(f"X{i},yas,{self.d},{i},1,2,\n" for i in range(9))
        self.run_artec(body)
        b = self.run_artec(f",orange,{self.d},6,5,4,\n" + "".join(f"Y{i},yas,{self.d},{i},3,3,\n" for i in range(1, 9)))
        self.assertEqual(b.rows.get(row_number=2).error_codes, ["duplicate_in_db"])

    def test_external_id_with_different_scores_goes_to_review(self):
        self.run_artec(f"EXT-1,orange,{self.d},5,5,5,\n" + "".join(f"Z{i},orange,{self.d},{i},2,3,\n" for i in range(9)))
        b = self.run_artec(f"EXT-1,orange,{self.d},9,2,2,\n" + "".join(f"W{i},orange,{self.d},{i},4,4,\n" for i in range(9)))
        r = b.rows.get(row_number=2)
        self.assertEqual((r.status, r.error_codes), ("to_review", ["external_id_conflict"]))
        self.assertEqual(b.review_rows, 1)

    def test_review_rules(self):
        old = "2023-01-15"
        body = (f"R1,orange,{self.d},10,10,10,\n"       # tout à 10
                f"R2,orange,{self.d},0,0,0,\n"          # tout à 0
                f"R3,orange,{old},5,6,7,\n"             # > 2 ans
                f"R4,orange,{self.d},5,6,7,voir http://x.io\n" +
                "".join(f"OK{i},orange,{self.d},{i},{i + 1},3,\n" for i in range(8)))
        b = self.run_artec(body)
        self.assertEqual(b.review_rows, 4)
        reasons = {r.row_number: r.error_codes for r in b.rows.filter(status="to_review")}
        self.assertIn("all_scores_identical_extreme", reasons[2])
        self.assertIn("date_older_than_2_years", reasons[4])
        self.assertIn("comment_contains_url", reasons[5])
        self.assertEqual(FeedbackSubmission.objects.filter(validation_status="to_review").count(), 4)
        self.assertEqual(FeedbackSubmission.objects.filter(validation_status="accepted").count(), 8)

    def test_reject_threshold_fails_whole_batch_and_commits_nothing(self):
        body = f"A,orange,{self.d},5,5,5,\n" + "".join(f"B{i},orange,{self.d},99,5,5,\n" for i in range(4))
        b = self.run_artec(body)  # 4/5 = 80 % > 20 %
        self.assertEqual(b.status, "failed")
        self.assertEqual(b.error_summary["error"], "reject_rate_exceeded")
        self.assertEqual(FeedbackSubmission.objects.count(), 0)
        self.assertEqual(ImportRowResult.objects.filter(batch=b).count(), 5)  # rapport conservé

    def test_exactly_at_threshold_is_accepted(self):
        body = f"B,orange,{self.d},99,5,5,\n" + "".join(f"G{i},orange,{self.d},{i},5,5,\n" for i in range(4))  # 1/5 = 20 %
        self.assertEqual(self.run_artec(body).status, "committed")

    def test_transaction_rollback_on_unexpected_error(self):
        body = "".join(f"G{i},orange,{self.d},{i},5,5,\n" for i in range(5))
        with mock.patch("apps.datasets.importer._save_rows", side_effect=RuntimeError("boom")):
            b = self.run_artec(body)
        self.assertEqual(b.status, "failed")
        self.assertEqual(b.error_summary["error"], "commit_failed")
        self.assertEqual(FeedbackSubmission.objects.count(), 0)
        self.assertEqual(FeedbackRating.objects.count(), 0)
        self.assertEqual(ImportBatch.objects.get(pk=b.pk).status, "failed")  # la trace de l'import subsiste

    def test_failed_import_does_not_touch_existing_data(self):
        existing = make_submission("orange", {"mobile_data_speed": 5})
        self.run_artec("garbage")
        self.assertTrue(FeedbackSubmission.objects.filter(pk=existing.pk).exists())
        self.assertEqual(FeedbackSubmission.objects.count(), 1)

    def test_wrong_extension_and_empty_file(self):
        for name in ("data.xls", "data.xlsm", "data.exe", "data.txt", "data"):
            b = process_import(uploaded_file=csv_upload("x", name), user=self.admin, data_source=self.src)
            self.assertEqual(b.error_summary["error"], "unsupported_format", name)
        b = process_import(uploaded_file=csv_upload(CSV_HEADER + "\n"), user=self.admin, data_source=self.src)
        self.assertEqual(b.error_summary["error"], "empty_file")

    @override_settings(IMPORT_MAX_FILE_BYTES=200)
    def test_file_too_large(self):
        b = self.run_artec("".join(f"G{i},orange,{self.d},5,5,5,\n" for i in range(50)))
        self.assertEqual(b.error_summary["error"], "file_too_large")
        self.assertEqual(FeedbackSubmission.objects.count(), 0)

    @override_settings(IMPORT_MAX_ROWS=3)
    def test_too_many_rows(self):
        b = self.run_artec("".join(f"G{i},orange,{self.d},5,5,5,\n" for i in range(5)))
        self.assertEqual(b.error_summary["error"], "too_many_rows")

    def test_binary_and_bad_encoding_refused(self):
        b = process_import(uploaded_file=csv_upload("a,b\n\x00\x01"), user=self.admin, data_source=self.src)
        self.assertEqual(b.status, "failed")
        from django.core.files.uploadedfile import SimpleUploadedFile
        b = process_import(uploaded_file=SimpleUploadedFile("x.csv", "é,ü\n1,2".encode("latin-1")), user=self.admin, data_source=self.src)
        self.assertEqual(b.error_summary["error"], "encoding_error")

    def test_formulas_in_csv_are_data_not_executed_and_neutralized_in_report(self):
        body = f'=1+1,orange,{self.d},99,5,5,"=HYPERLINK(""http://evil"")"\n' + "".join(f"G{i},orange,{self.d},{i},5,5,\n" for i in range(9))
        b = self.run_artec(body)
        report = error_report_csv(b)
        self.assertIn("'=1+1", report)
        self.assertNotIn(",=1+1", report)

    def test_filename_sanitised(self):
        b = process_import(uploaded_file=csv_upload(CSV_HEADER + f"\nE,orange,{self.d},5,5,5,\n", "../../etc/pass\x00wd.csv"),
                           user=self.admin, data_source=self.src)
        self.assertNotIn("/", b.original_filename)
        self.assertNotIn("\x00", b.original_filename)

    def test_external_source_types_mapped(self):
        for t, expected in (("social_export", "external_import"), ("survey_export", "external_import"), ("official_api", "external_import")):
            src = DataSource.objects.create(name=f"s-{t}", source_type=t, legal_basis="ok")
            b = process_import(uploaded_file=csv_upload(CSV_HEADER + f"\nE-{t},orange,{self.d},5,5,5,\n"), user=self.admin, data_source=src)
            self.assertEqual(FeedbackSubmission.objects.get(import_batch=b).source, expected)


class ImportExcelTests(TestCase):
    def setUp(self):
        self.admin = artec_user()
        self.src = artec_source()
        self.d = recent_date()

    def test_valid_xlsx(self):
        up = xlsx_upload([["E1", "orange", self.d, 7, 6, 8, "ok"], ["E2", "airtel", self.d, 3, None, 9, None]])
        b = process_import(uploaded_file=up, user=self.admin, data_source=self.src)
        self.assertEqual(b.status, "committed", b.error_summary)
        self.assertEqual((b.accepted_rows, b.file_format), (2, "xlsx"))
        self.assertEqual(FeedbackRating.objects.count(), 5)

    def test_xlsx_with_real_dates_and_float_integers(self):
        import datetime
        up = xlsx_upload([["E1", "orange", datetime.datetime.now() - datetime.timedelta(days=2), 7.0, 6.0, 8.0, None]])
        b = process_import(uploaded_file=up, user=self.admin, data_source=self.src)
        self.assertEqual(b.status, "committed", b.error_summary)

    def test_xlsx_decimal_scores_rejected(self):
        rows = [["E0", "orange", self.d, 7.5, 6, 8, None]] + [[f"G{i}", "orange", self.d, i, 5, 5, None] for i in range(9)]
        b = process_import(uploaded_file=xlsx_upload(rows), user=self.admin, data_source=self.src)
        self.assertEqual(b.rows.get(row_number=2).error_codes, ["score_not_integer"])

    def test_falls_back_to_first_sheet(self):
        b = process_import(uploaded_file=xlsx_upload([["E1", "orange", self.d, 7, 6, 8, None]], sheet="Feuil1"), user=self.admin, data_source=self.src)
        self.assertEqual(b.status, "committed")

    def test_xlsx_formula_not_executed(self):
        import openpyxl
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "feedback"
        ws.append(CSV_HEADER.split(","))
        ws.append(["E1", "orange", self.d, "=1+1", 5, 5, None])
        buf = io.BytesIO()
        wb.save(buf)
        from django.core.files.uploadedfile import SimpleUploadedFile
        b = process_import(uploaded_file=SimpleUploadedFile("f.xlsx", buf.getvalue()), user=self.admin, data_source=self.src)
        self.assertEqual(FeedbackRating.objects.filter(score=2).count(), 0)  # formule jamais évaluée en note

    def test_corrupt_and_fake_xlsx_refused(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        for content in (b"not a zip", b"PK\x03\x04garbage"):
            b = process_import(uploaded_file=SimpleUploadedFile("x.xlsx", content), user=self.admin, data_source=self.src)
            self.assertEqual(b.status, "failed")
            self.assertIn(b.error_summary["error"], ("invalid_xlsx", "xlsx_parse_error"))

    def test_macro_workbook_refused(self):
        import zipfile
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("[Content_Types].xml", "<x/>")
            z.writestr("xl/workbook.xml", "<x/>")
            z.writestr("xl/vbaProject.bin", b"macro")
        from django.core.files.uploadedfile import SimpleUploadedFile
        b = process_import(uploaded_file=SimpleUploadedFile("m.xlsx", buf.getvalue()), user=self.admin, data_source=self.src)
        self.assertEqual(b.error_summary["error"], "macro_refused")


class OperatorImportScopeTests(TestCase):
    def setUp(self):
        self.d = recent_date()

    def test_operator_import_forced_to_own_operator(self):
        u = operator_user("orange")
        b = process_import(uploaded_file=csv_upload(f"collected_at,score_mobile_data_speed\n{self.d},7\n"), user=u,
                           data_source=op_source(), operator_scope=u.operator)
        self.assertEqual(b.status, "committed")
        s = FeedbackSubmission.objects.get()
        self.assertEqual((s.operator.code, s.source), ("orange", "operator_import"))

    def test_operator_cannot_import_rows_about_competitor(self):
        u = operator_user("orange")
        body = f"operator_code,collected_at,score_mobile_data_speed\nyas,{self.d},1\n" + "".join(f"orange,{self.d},{i}\n" for i in range(9))
        b = process_import(uploaded_file=csv_upload(body), user=u, data_source=op_source(), operator_scope=u.operator)
        self.assertEqual(b.rows.get(row_number=2).error_codes, ["operator_not_allowed"])
        self.assertFalse(FeedbackSubmission.objects.filter(operator__code="yas").exists())

    def test_operator_import_view_end_to_end(self):
        u = operator_user("airtel")
        self.client.force_login(u)
        r = self.client.post(reverse("operator:import_create"), {"file": csv_upload(f"collected_at,score_customer_service\n{self.d},6\n")})
        b = ImportBatch.objects.get()
        self.assertRedirects(r, reverse("operator:import_detail", args=[b.pk]), fetch_redirect_response=False)
        self.assertEqual(b.operator.code, "airtel")
        self.assertEqual(self.client.get(reverse("operator:import_detail", args=[b.pk])).status_code, 200)

    def test_import_template_download(self):
        self.client.force_login(operator_user())
        r = self.client.get(reverse("operator:import_template"))
        self.assertIn("score_mobile_data_speed", r.content.decode())
        self.assertIn("attachment", r["Content-Disposition"])


class ArtecImportViewTests(TestCase):
    def test_artec_import_requires_source_and_operator_code(self):
        self.client.force_login(artec_user())
        src = artec_source()
        d = recent_date()
        r = self.client.post(reverse("artec:import_create"), {"file": csv_upload(f"operator_code,collected_at,score_customer_service\norange,{d},6\n"), "data_source": src.pk})
        b = ImportBatch.objects.get()
        self.assertEqual(b.status, "committed")
        self.assertEqual(self.client.get(reverse("artec:import_detail", args=[b.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("artec:import_list")).status_code, 200)

    def test_social_source_requires_legal_basis(self):
        self.client.force_login(artec_user())
        r = self.client.post(reverse("artec:source_create"), {"name": "FB export", "source_type": "social_export", "is_active": "on"})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(DataSource.objects.filter(name="FB export").exists())
        r = self.client.post(reverse("artec:source_create"), {"name": "FB export", "source_type": "social_export", "legal_basis": "Export autorisé par la page propriétaire", "is_active": "on"})
        self.assertEqual(r.status_code, 302)

    def test_import_file_is_stored_privately(self):
        from django.conf import settings
        b = process_import(uploaded_file=csv_upload(CSV_HEADER + f"\nE,orange,{recent_date()},5,5,5,\n"), user=artec_user(), data_source=artec_source())
        self.assertTrue(str(b.stored_file.path).startswith(str(settings.PRIVATE_MEDIA_ROOT)))
        with self.assertRaises(ValueError):
            b.stored_file.url  # aucune URL publique
