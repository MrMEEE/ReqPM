from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('packages', '0012_package_missing_packages_status'),
    ]

    operations = [
        migrations.AlterField(
            model_name='package',
            name='build_status',
            field=models.CharField(
                choices=[
                    ('not_built', 'Not Built'),
                    ('waiting_for_deps', 'Waiting for Dependencies'),
                    ('dep_build_pending', 'Dependency Build Pending'),
                    ('pending', 'Pending'),
                    ('building', 'Building'),
                    ('completed', 'Completed'),
                    ('failed', 'Failed'),
                    ('missing_packages', 'Missing Packages'),
                ],
                default='not_built',
                help_text='Current build status for this package',
                max_length=20,
            ),
        ),
    ]
