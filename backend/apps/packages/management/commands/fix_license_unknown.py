"""
Management command to fix 'License: Unknown' in existing spec file revisions
by resolving the correct SPDX expression from PyPI metadata.
"""
import time
from django.core.management.base import BaseCommand
from django.db import transaction
from backend.apps.packages.models import Package, SpecFileRevision
from backend.core.pypi_client import PyPIClient


class Command(BaseCommand):
    help = 'Fix "License: Unknown" in spec files by resolving from PyPI metadata'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be changed without writing anything',
        )
        parser.add_argument(
            '--project',
            type=int,
            help='Limit to packages in a specific project ID',
        )
        parser.add_argument(
            '--package',
            type=int,
            help='Fix a single package by ID',
        )
        parser.add_argument(
            '--delay',
            type=float,
            default=0.3,
            help='Seconds to wait between PyPI requests (default: 0.3)',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        project_id = options.get('project')
        package_id = options.get('package')
        delay = options['delay']

        if dry_run:
            self.stdout.write(self.style.WARNING('DRY RUN — no changes will be written'))

        client = PyPIClient()
        fixed = 0
        skipped = 0
        not_found = 0
        errors = 0

        # Collect candidate packages (those whose latest spec has License: Unknown)
        qs = Package.objects.all()
        if project_id:
            qs = qs.filter(project_id=project_id)
        if package_id:
            qs = qs.filter(id=package_id)

        candidates = []
        for pkg in qs.order_by('name'):
            spec = SpecFileRevision.objects.filter(package=pkg).order_by('-created_at').first()
            if spec and 'License:' in spec.content:
                # Extract current License value
                for line in spec.content.split('\n'):
                    stripped = line.strip()
                    if stripped.lower().startswith('license:'):
                        value = stripped.split(':', 1)[1].strip()
                        if value.lower() in ('unknown', ''):
                            candidates.append((pkg, spec))
                        break

        self.stdout.write(f'Found {len(candidates)} package(s) with License: Unknown')

        for pkg, spec in candidates:
            pypi_name = pkg.python_name or pkg.name
            try:
                info = client.get_package_info(pypi_name, pkg.version)
                if delay:
                    time.sleep(delay)

                if not info or info.license == 'Unknown':
                    # Try without version pin
                    if pkg.version:
                        info = client.get_package_info(pypi_name)
                        if delay:
                            time.sleep(delay)

                if not info or info.license == 'Unknown':
                    self.stdout.write(
                        self.style.WARNING(f'  {pkg.name} (id={pkg.id}): no license found on PyPI')
                    )
                    not_found += 1
                    continue

                spdx = info.license
                new_content = _replace_license(spec.content, spdx)
                if new_content == spec.content:
                    skipped += 1
                    continue

                self.stdout.write(
                    f'  {pkg.name} (id={pkg.id}, project={pkg.project_id}): Unknown → {spdx}'
                )

                if not dry_run:
                    with transaction.atomic():
                        SpecFileRevision.objects.create(
                            package=pkg,
                            content=new_content,
                            commit_message=f'Auto-fix: set License to {spdx} (resolved from PyPI)'
                        )
                fixed += 1

            except Exception as e:
                self.stderr.write(f'  {pkg.name} (id={pkg.id}): ERROR — {e}')
                errors += 1

        self.stdout.write('')
        self.stdout.write(
            self.style.SUCCESS(
                f'Done. fixed={fixed}  not_found={not_found}  skipped={skipped}  errors={errors}'
            )
        )


def _replace_license(spec: str, spdx: str) -> str:
    """Replace the License: line in a spec file."""
    import re
    return re.sub(
        r'^(License:\s*).*$',
        lambda m: f'{m.group(1)}{spdx}',
        spec,
        count=1,
        flags=re.MULTILINE,
    )
