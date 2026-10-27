from django.db import migrations

from apps.feedback.seed import seed_criteria


def forwards(apps, schema_editor):
    seed_criteria(apps.get_model("feedback", "Criterion"), apps.get_model("feedback", "SurveyForm"),
                  apps.get_model("feedback", "SurveyFormCriterion"))


class Migration(migrations.Migration):
    dependencies = [("feedback", "0001_initial")]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
