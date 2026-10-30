from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0007_systemsettings_celery_worker_concurrency'),
    ]

    operations = [
        migrations.AddField(
            model_name='systemsettings',
            name='ai_fixer_allow_insert_lines',
            field=models.BooleanField(
                default=False,
                help_text='Allow the AI fixer to insert arbitrary lines next to an exact spec line',
            ),
        ),
        migrations.AddField(
            model_name='systemsettings',
            name='ai_fixer_allow_spec_rewrite',
            field=models.BooleanField(
                default=False,
                help_text='Allow the AI fixer to replace the complete spec file',
            ),
        ),
    ]
