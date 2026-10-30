from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('packages', '0020_ai_fix_attempt'),
    ]

    operations = [
        migrations.AddField(
            model_name='package',
            name='last_build_log',
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name='package',
            name='last_build_root_log',
            field=models.TextField(blank=True),
        ),
    ]
