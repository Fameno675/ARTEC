from django.db import migrations

from apps.operators.seed import seed_operators


def forwards(apps, schema_editor):
    seed_operators(apps.get_model("operators", "Operator"))


class Migration(migrations.Migration):
    dependencies = [("operators", "0001_initial")]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
