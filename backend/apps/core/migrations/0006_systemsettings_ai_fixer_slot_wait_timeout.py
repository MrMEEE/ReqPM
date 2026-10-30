from django.db import migrations, models
import django.core.validators


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0005_systemsettings_mock_memory_limit'),
    ]

    operations = [
        migrations.AddField(
            model_name='systemsettings',
            name='ai_fixer_slot_wait_timeout',
            field=models.IntegerField(
                default=45,
                help_text='Seconds to wait for an available AI fixer slot before failing',
                validators=[
                    django.core.validators.MinValueValidator(5),
                    django.core.validators.MaxValueValidator(3600),
                ],
            ),
        ),
    ]
