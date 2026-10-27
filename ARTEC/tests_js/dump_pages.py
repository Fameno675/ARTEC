import os, django
os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings"
django.setup()
from datetime import date, timedelta
from django.test import Client
from django.conf import settings
settings.ALLOWED_HOSTS = ["*"]
from apps.accounts.models import User
from apps.analytics import services as ml
from apps.complaints.models import Complaint
b = ml.create_batch(requested_by=None, operator=None, start=date.today()-timedelta(days=200), end=date.today()); ml.execute_batch(b)
os.makedirs("/tmp/pages", exist_ok=True)
def save(name, client, url):
    r = client.get(url, HTTP_HOST="localhost"); assert r.status_code == 200, (name, r.status_code)
    open(f"/tmp/pages/{name}.html", "w").write(r.content.decode())
anon = Client()
for n, u in [("survey_detail","/sondages/satisfaction-generale/"),("results","/resultats/"),("survey_list","/sondages/")]: save(n, anon, u)
art = Client(); art.force_login(User.objects.get(email="demo.artec@example.mg"))
for n, u in [("artec_dashboard","/artec/"),("artec_import_create","/artec/imports/nouveau/"),("mlbatch","/artec/analyses/%s/?anomalies=1" % b.pk),("feedback_list","/artec/avis/?status=to_review")]: save(n, art, u)
op = Client(); op.force_login(User.objects.get(email="demo.orange@example.mg"))
save("op_dashboard", op, "/operateur/")
print("pages ok", os.listdir("/tmp/pages"))
