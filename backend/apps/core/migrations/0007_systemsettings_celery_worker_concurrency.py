from django.db import migrations, models
import django.core.validators


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0006_systemsettings_ai_fixer_slot_wait_timeout'),
    ]

    operations = [
        migrations.AddField(
            model_name='systemsettings',
            name='celery_worker_concurrency',
            field=models.IntegerField(
                default=4,
                help_text='Number of Celery worker processes for the main task queue',
                validators=[
                    django.core.validators.MinValueValidator(1),
                    django.core.validators.MaxValueValidator(20),
                ],
            ),
        ),
    ]
