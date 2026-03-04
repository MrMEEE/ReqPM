from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('packages', '0010_package_analyzed_errors'),
    ]

    operations = [
        migrations.AddField(
            model_name='package',
            name='build_system',
            field=models.CharField(
                blank=True,
                choices=[
                    ('unknown', 'Unknown'),
                    ('setuptools', 'Setuptools (setup.py)'),
                    ('poetry', 'Poetry Core'),
                    ('flit', 'Flit Core'),
                    ('hatchling', 'Hatchling'),
                    ('pdm', 'PDM Backend'),
                    ('meson', 'Meson Python'),
                    ('scikit-build', 'Scikit-Build Core'),
                    ('other-pyproject', 'Other (pyproject.toml)'),
                ],
                default='unknown',
                help_text='Build system used by this package (auto-detected or manually set)',
                max_length=30,
            ),
        ),
    ]
