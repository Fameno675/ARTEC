from django.test import TestCase

from apps.audit.models import AuditLog
from apps.audit.services import log
from apps.common.testing import artec_user


class AuditTests(TestCase):
    def test_append_only(self):
        entry = log(artec_user(), "test.action", None, k=1)
        entry.action = "changed"
        with self.assertRaises(PermissionError):
            entry.save()
        with self.assertRaises(PermissionError):
            entry.delete()
        with self.assertRaises(PermissionError):
            AuditLog.objects.all().delete()
        with self.assertRaises(PermissionError):
            AuditLog.objects.all().update(action="x")
