from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0004_ai_fixer_max_concurrent'),
    ]

    operations = [
        migrations.AddField(
            model_name='systemsettings',
            name='mock_memory_limit',
            field=models.CharField(
                blank=True,
                default='',
                help_text='Per-build memory cap enforced via cgroup (e.g. 8G, 4096M). Leave empty to disable.',
                max_length=20,
            ),
        ),
    ]
