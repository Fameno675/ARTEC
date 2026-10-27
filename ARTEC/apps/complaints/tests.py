from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from apps.audit.models import AuditLog
from apps.common.testing import artec_user, make_user, op, operator_user
from apps.complaints import services
from apps.complaints.models import ArtecDecision, Complaint, ComplaintEvent


def file_complaint(user=None, target="yas"):
    user = user or operator_user("orange")
    return services.create_complaint(user=user, target_operator=op(target), subject="Tarifs anormaux",
                                     description="Description détaillée des faits allégués sur la période.")


class ComplaintServiceTests(TestCase):
    def test_create_sets_reference_event_and_audit(self):
        c = file_complaint()
        self.assertRegex(c.reference, r"^REC-\d{4}-0001$")
        self.assertEqual(c.status, "received")
        self.assertEqual(c.complainant_operator.code, "orange")
        self.assertEqual(c.events.get().event_type, "filed")
        self.assertTrue(AuditLog.objects.filter(action="complaint.filed").exists())
        self.assertTrue(file_complaint().reference.endswith("0002"))

    def test_cannot_complain_against_self(self):
        u = operator_user("orange")
        with self.assertRaises(ValidationError):
            services.create_complaint(user=u, target_operator=op("orange"), subject="s", description="d" * 40)

    def test_db_constraint_parties_differ(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Complaint.objects.create(reference="REC-X-1", complainant_operator=op("yas"), target_operator=op("yas"), subject="s", description="d")

    def test_only_operator_accounts_can_file(self):
        with self.assertRaises(PermissionDenied):
            services.create_complaint(user=artec_user(), target_operator=op("yas"), subject="s", description="d" * 40)

    def test_status_transitions(self):
        c, a = file_complaint(), artec_user()
        with self.assertRaises(ValidationError):
            services.change_status(complaint=c, user=a, new_status="closed")  # received -> closed interdit
        services.change_status(complaint=c, user=a, new_status="under_review")
        services.change_status(complaint=c, user=a, new_status="info_requested", note="Merci de fournir les logs.")
        services.change_status(complaint=c, user=a, new_status="under_review")
        services.change_status(complaint=c, user=a, new_status="closed")
        c.refresh_from_db()
        self.assertEqual(c.status, "closed")
        with self.assertRaises(ValidationError):
            services.change_status(complaint=c, user=a, new_status="under_review")  # état final
        self.assertEqual(c.events.filter(event_type="status_change").count(), 4)

    def test_operator_cannot_change_status(self):
        c = file_complaint()
        with self.assertRaises(PermissionDenied):
            services.change_status(complaint=c, user=operator_user("orange"), new_status="under_review")

    def test_decision_requires_evidence_and_review_state_and_artec(self):
        c, a = file_complaint(), artec_user()
        with self.assertRaises(ValidationError):  # pas encore en examen
            services.record_decision(complaint=c, user=a, decision_type="monitoring", evidence_summary="x" * 30)
        services.change_status(complaint=c, user=a, new_status="under_review")
        with self.assertRaises(ValidationError):
            services.record_decision(complaint=c, user=a, decision_type="monitoring", evidence_summary="trop court")
        with self.assertRaises(PermissionDenied):
            services.record_decision(complaint=c, user=operator_user("orange"), decision_type="monitoring", evidence_summary="x" * 30)
        d = services.record_decision(complaint=c, user=a, decision_type="monitoring", evidence_summary="Relevés contradictoires vérifiés le 12/03, réf. pièce 2.")
        self.assertEqual(ArtecDecision.objects.count(), 1)
        self.assertEqual(d.decided_by, a)
        self.assertFalse(c.events.get(event_type="decision").visible_to_complainant)

    def test_history_is_append_only(self):
        ev = file_complaint().events.get()
        ev.note = "modif"
        with self.assertRaises(PermissionError):
            ev.save()
        with self.assertRaises(PermissionError):
            ev.delete()

    def test_attachment_validation(self):
        c = file_complaint()
        u = c.filed_by
        ok = services.add_attachment(complaint=c, user=u, uploaded=SimpleUploadedFile("preuve.pdf", b"%PDF-1.4 data"))
        self.assertEqual(len(ok.sha256), 64)
        for name, data in (("virus.exe", b"MZ"), ("fake.pdf", b"not a pdf"), ("page.html", b"<script>"), ("x.png", b"GIF89a")):
            with self.assertRaises(ValidationError, msg=name):
                services.add_attachment(complaint=c, user=u, uploaded=SimpleUploadedFile(name, data))
        with self.assertRaises(PermissionDenied):
            services.add_attachment(complaint=c, user=operator_user("airtel"), uploaded=SimpleUploadedFile("a.pdf", b"%PDF"))

    def test_attachment_size_limit(self):
        from django.test import override_settings
        c = file_complaint()
        with override_settings(COMPLAINT_MAX_ATTACHMENT_BYTES=10):
            with self.assertRaises(ValidationError):
                services.add_attachment(complaint=c, user=c.filed_by, uploaded=SimpleUploadedFile("a.pdf", b"%PDF" + b"0" * 50))

    def test_closed_complaint_refuses_attachments_and_messages(self):
        c, a = file_complaint(), artec_user()
        services.change_status(complaint=c, user=a, new_status="rejected")
        c.refresh_from_db()
        with self.assertRaises(ValidationError):
            services.add_message(complaint=c, user=c.filed_by, note="Bonjour")


class ComplaintViewTests(TestCase):
    def setUp(self):
        self.orange = operator_user("orange")
        self.client.force_login(self.orange)

    def test_create_via_view_and_notice_displayed(self):
        r = self.client.get(reverse("operator:complaint_create"))
        self.assertContains(r, "allégation")
        yas = op("yas")
        r = self.client.post(reverse("operator:complaint_create"), {"target_operator": yas.pk, "subject": "Objet", "description": "d" * 40})
        c = Complaint.objects.get()
        self.assertRedirects(r, reverse("operator:complaint_detail", args=[c.reference]), fetch_redirect_response=False)
        self.assertContains(self.client.get(reverse("operator:complaint_detail", args=[c.reference])), "ne constitue ni une preuve")

    def test_cannot_target_own_operator_in_form(self):
        r = self.client.post(reverse("operator:complaint_create"), {"target_operator": op("orange").pk, "subject": "O", "description": "d" * 40})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Complaint.objects.count(), 0)

    def test_attach_and_download_roundtrip(self):
        c = file_complaint(self.orange)
        self.client.post(reverse("operator:complaint_attach", args=[c.reference]), {"file": SimpleUploadedFile("p.pdf", b"%PDF-1.4 hello")})
        att = c.attachments.get()
        r = self.client.get(reverse("operator:attachment_download", args=[c.reference, att.pk]))
        self.assertEqual(b"".join(r.streaming_content), b"%PDF-1.4 hello")
        self.assertIn("attachment", r["Content-Disposition"])

    def test_internal_notes_hidden_from_complainant(self):
        c = file_complaint(self.orange)
        services.change_status(complaint=c, user=artec_user(), new_status="under_review", note="NOTE INTERNE", visible=False)
        self.assertNotContains(self.client.get(reverse("operator:complaint_detail", args=[c.reference])), "NOTE INTERNE")

    def test_artec_workflow_views(self):
        c = file_complaint(self.orange)
        self.client.force_login(artec_user())
        self.client.post(reverse("artec:complaint_status", args=[c.reference]), {"status": "under_review", "visible_to_complainant": "on"})
        c.refresh_from_db()
        self.assertEqual(c.status, "under_review")
        self.client.post(reverse("artec:complaint_decision", args=[c.reference]), {"decision_type": "no_action", "evidence_summary": "Aucune preuve vérifiable n'a pu être recueillie."})
        self.assertEqual(ArtecDecision.objects.count(), 1)
        self.assertContains(self.client.get(reverse("artec:complaint_detail", args=[c.reference])), "allégation")
        self.assertEqual(self.client.get(reverse("artec:complaint_list") + "?status=under_review").status_code, 200)


class ComplaintIsolationTests(TestCase):
    def test_other_operator_cannot_see_or_touch_complaint(self):
        orange = operator_user("orange")
        c = file_complaint(orange, target="airtel")
        for code in ("yas", "airtel"):  # y compris l'opérateur visé : pas d'accès en v1
            other = operator_user(code)
            self.client.force_login(other)
            self.assertEqual(self.client.get(reverse("operator:complaint_detail", args=[c.reference])).status_code, 404, code)
            self.assertEqual(self.client.post(reverse("operator:complaint_reply", args=[c.reference]), {"note": "x"}).status_code, 404)
            self.assertEqual(self.client.post(reverse("operator:complaint_attach", args=[c.reference]), {"file": SimpleUploadedFile("a.pdf", b"%PDF")}).status_code, 404)
            self.assertNotContains(self.client.get(reverse("operator:complaint_list")), c.reference)

    def test_other_operator_cannot_download_attachment(self):
        orange = operator_user("orange")
        c = file_complaint(orange)
        att = services.add_attachment(complaint=c, user=orange, uploaded=SimpleUploadedFile("p.pdf", b"%PDF-1.4"))
        self.client.force_login(operator_user("airtel"))
        self.assertEqual(self.client.get(reverse("operator:attachment_download", args=[c.reference, att.pk])).status_code, 404)

    def test_attachment_id_from_other_complaint_not_reachable_via_own_reference(self):
        orange, airtel = operator_user("orange"), operator_user("airtel")
        mine = file_complaint(airtel, target="yas")
        theirs = file_complaint(orange, target="yas")
        att = services.add_attachment(complaint=theirs, user=orange, uploaded=SimpleUploadedFile("p.pdf", b"%PDF-1.4"))
        self.client.force_login(airtel)
        self.assertEqual(self.client.get(reverse("operator:attachment_download", args=[mine.reference, att.pk])).status_code, 404)
