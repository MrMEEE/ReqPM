from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('packages', '0017_package_build_dependency_repo_url'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='specfilerevision',
            name='ai_feedback',
            field=models.CharField(
                choices=[('unknown', 'Unknown'), ('correct', 'Correct'), ('wrong', 'Wrong')],
                default='unknown',
                help_text='User feedback for AI-generated fix quality',
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='specfilerevision',
            name='ai_feedback_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='specfilerevision',
            name='ai_feedback_by',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='ai_fix_feedbacks',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name='specfilerevision',
            name='ai_feedback_note',
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name='specfilerevision',
            name='ai_taught',
            field=models.BooleanField(
                default=False,
                help_text='Whether this revision was explicitly marked as a learning example for AI',
            ),
        ),
        migrations.AddField(
            model_name='specfilerevision',
            name='ai_taught_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='specfilerevision',
            name='ai_taught_by',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='ai_taught_revisions',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name='specfilerevision',
            name='ai_taught_note',
            field=models.TextField(blank=True),
        ),
    ]
