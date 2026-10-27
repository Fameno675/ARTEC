from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import Role, User
from apps.common.testing import PASSWORD, artec_user, make_user, op, operator_user, tech_user


class UserModelTests(TestCase):
    def test_password_is_hashed_never_plain(self):
        u = operator_user()
        self.assertNotEqual(u.password, PASSWORD)
        self.assertTrue(u.password.startswith("pbkdf2_"))
        self.assertTrue(u.check_password(PASSWORD))

    def test_operator_role_requires_operator(self):
        with self.assertRaises(ValidationError):
            User.objects.create_user(email="x@x.mg", password=PASSWORD, full_name="X", role=Role.OPERATOR)

    def test_non_operator_cannot_have_operator(self):
        with self.assertRaises(ValidationError):
            User.objects.create_user(email="y@x.mg", password=PASSWORD, full_name="Y", role=Role.ARTEC_ADMIN, operator=op("yas"))

    def test_db_constraint_blocks_inconsistent_user(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            User.objects.bulk_create([User(email="z@x.mg", full_name="Z", role=Role.OPERATOR, password="x")])


class AuthAndPermissionTests(TestCase):
    def test_anonymous_redirected_from_private_views(self):
        for name, args in [("operator:dashboard", []), ("artec:dashboard", []), ("operator:import_list", []),
                           ("artec:audit", []), ("operator:complaint_list", [])]:
            r = self.client.get(reverse(name, args=args))
            self.assertEqual(r.status_code, 302, name)
            self.assertIn(reverse("accounts:login"), r["Location"])

    def test_login_logout_session(self):
        u = operator_user()
        self.assertTrue(self.client.login(username=u.email, password=PASSWORD))
        self.assertEqual(self.client.get(reverse("operator:dashboard")).status_code, 200)
        self.assertEqual(self.client.get(reverse("accounts:logout")).status_code, 405)  # POST uniquement
        self.client.post(reverse("accounts:logout"))
        self.assertEqual(self.client.get(reverse("operator:dashboard")).status_code, 302)

    def test_login_form_post_and_redirect_by_role(self):
        u = artec_user()
        r = self.client.post(reverse("accounts:login"), {"username": u.email, "password": PASSWORD}, follow=True)
        self.assertEqual(r.redirect_chain[-1][0], reverse("artec:dashboard"))

    def test_operator_cannot_access_artec_space(self):
        self.client.force_login(operator_user())
        for name in ("artec:dashboard", "artec:import_list", "artec:complaint_list", "artec:mlbatch_list", "artec:audit"):
            self.assertEqual(self.client.get(reverse(name)).status_code, 403, name)

    def test_artec_admin_cannot_use_operator_space(self):
        self.client.force_login(artec_user())
        self.assertEqual(self.client.get(reverse("operator:dashboard")).status_code, 403)
        self.assertEqual(self.client.get(reverse("operator:import_create")).status_code, 403)

    def test_admin_site_reserved_to_tech_admin(self):
        self.client.force_login(artec_user())
        self.assertNotEqual(self.client.get("/gestion/accounts/user/").status_code, 200)
        self.client.force_login(operator_user())
        self.assertNotEqual(self.client.get("/gestion/accounts/user/").status_code, 200)
        self.client.force_login(tech_user())
        self.assertEqual(self.client.get("/gestion/accounts/user/").status_code, 200)

    def test_tech_admin_cannot_take_regulatory_decisions(self):
        self.client.force_login(tech_user())
        self.assertEqual(self.client.get(reverse("artec:dashboard")).status_code, 403)

    def test_inactive_user_cannot_login(self):
        u = operator_user()
        u.is_active = False
        u.save()
        self.assertFalse(self.client.login(username=u.email, password=PASSWORD))

    def test_must_change_password_forces_redirect(self):
        u = operator_user()
        u.must_change_password = True
        u.save()
        self.client.force_login(u)
        r = self.client.get(reverse("operator:dashboard"))
        self.assertRedirects(r, reverse("accounts:password_change"), fetch_redirect_response=False)

    def test_csrf_enforced_on_post(self):
        from django.test import Client
        c = Client(enforce_csrf_checks=True)
        c.force_login(operator_user())
        self.assertEqual(c.post(reverse("operator:import_create"), {}).status_code, 403)

    def test_login_lockout_after_failures(self):
        from django.core.cache import cache
        cache.clear()
        u = operator_user()
        for _ in range(5):
            self.client.post(reverse("accounts:login"), {"username": u.email, "password": "bad"})
        r = self.client.post(reverse("accounts:login"), {"username": u.email, "password": PASSWORD})
        self.assertContains(r, "Trop de tentatives")
        cache.clear()


class SeedTests(TestCase):
    def test_operators_seeded_once_and_idempotent(self):
        from apps.operators.models import Operator
        from apps.operators.seed import seed_operators
        self.assertEqual(Operator.objects.count(), 3)
        seed_operators(Operator)
        seed_operators(Operator)
        self.assertEqual(Operator.objects.count(), 3)
        self.assertEqual(set(Operator.objects.values_list("code", flat=True)), {"orange", "yas", "airtel"})

    def test_criteria_seed_idempotent_and_keeps_edits(self):
        from apps.feedback.models import Criterion, SurveyForm, SurveyFormCriterion
        from apps.feedback.seed import seed_criteria
        self.assertEqual(Criterion.objects.count(), 10)
        s = SurveyForm.objects.get(slug="satisfaction-generale")
        s.title = "Modifié par ARTEC"
        s.save()
        seed_criteria(Criterion, SurveyForm, SurveyFormCriterion)
        self.assertEqual(Criterion.objects.count(), 10)
        self.assertEqual(SurveyForm.objects.count(), 1)
        self.assertEqual(SurveyForm.objects.get(slug="satisfaction-generale").title, "Modifié par ARTEC")
        self.assertEqual(SurveyFormCriterion.objects.count(), 10)
