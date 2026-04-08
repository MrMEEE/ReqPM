"""
Management command to deduplicate packages with different casing
"""
from django.core.management.base import BaseCommand
from django.db import transaction
from backend.apps.packages.models import Package, PackageDependency
from collections import defaultdict


class Command(BaseCommand):
    help = 'Deduplicate packages that differ only in casing (e.g., MarkupSafe vs markupsafe)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be done without making changes',
        )
        parser.add_argument(
            '--project',
            type=int,
            help='Only deduplicate packages in specific project ID',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        project_id = options.get('project')
        
        if dry_run:
            self.stdout.write(self.style.WARNING('DRY RUN MODE - No changes will be made'))
        
        # Build query
        packages_qs = Package.objects.all()
        if project_id:
            packages_qs = packages_qs.filter(project_id=project_id)
            self.stdout.write(f'Checking project {project_id}...')
        else:
            self.stdout.write('Checking all projects...')
        
        # Group packages by (project, lowercase_name)
        package_groups = defaultdict(list)
        for package in packages_qs.select_related('project').order_by('project_id', 'name'):
            key = (package.project_id, package.name.lower())
            package_groups[key].append(package)
        
        # Find duplicates
        duplicates_found = 0
        packages_merged = 0
        packages_deleted = 0
        
        for (proj_id, normalized_name), packages in package_groups.items():
            if len(packages) <= 1:
                continue
            
            duplicates_found += 1
            
            # Sort by priority: direct dependencies first, then by ID (older first)
            packages.sort(key=lambda p: (not p.is_direct_dependency, p.id))
            primary = packages[0]
            duplicates = packages[1:]
            
            self.stdout.write(f'\n{self.style.WARNING("Found duplicates:")}')
            self.stdout.write(f'  Primary: {primary.name} (ID: {primary.id}, direct: {primary.is_direct_dependency})')
            for dup in duplicates:
                self.stdout.write(f'  Duplicate: {dup.name} (ID: {dup.id}, direct: {dup.is_direct_dependency})')
            
            if not dry_run:
                with transaction.atomic():
                    # Merge remaining packages into primary
                    for dup in duplicates:
                        # Keep python_name if primary doesn't have one
                        if not primary.python_name and dup.python_name:
                            primary.python_name = dup.python_name
                        
                        # Mark as direct dependency if any duplicate is direct
                        if dup.is_direct_dependency:
                            primary.is_direct_dependency = True
                        
                        # Merge requirements_file
                        if dup.requirements_file and not primary.requirements_file:
                            primary.requirements_file = dup.requirements_file
                        
                        # Update dependencies pointing to duplicate
                        # First, collect unique dependencies to transfer
                        deps_to_transfer = PackageDependency.objects.filter(
                            depends_on=dup
                        )
                        deps_updated = 0
                        deps_deleted = 0
                        
                        for dep in deps_to_transfer:
                            # Check if this relationship already exists for primary
                            existing = PackageDependency.objects.filter(
                                package=dep.package,
                                depends_on=primary
                            ).exists()
                            
                            if existing:
                                # Delete duplicate dependency relationship
                                dep.delete()
                                deps_deleted += 1
                            else:
                                # Update to point to primary
                                dep.depends_on = primary
                                dep.save()
                                deps_updated += 1
                        
                        # Update dependents (packages that depend on this duplicate)
                        dependents_to_transfer = PackageDependency.objects.filter(
                            package=dup
                        )
                        dependents_updated = 0
                        dependents_deleted = 0
                        
                        for dep in dependents_to_transfer:
                            # Check if this relationship already exists for primary
                            existing = PackageDependency.objects.filter(
                                package=primary,
                                depends_on=dep.depends_on
                            ).exists()
                            
                            if existing:
                                # Delete duplicate dependency relationship
                                dep.delete()
                                dependents_deleted += 1
                            else:
                                # Update to use primary as the package
                                dep.package = primary
                                dep.save()
                                dependents_updated += 1
                        
                        self.stdout.write(
                            f'  Merged {dup.name} into {primary.name} '
                            f'(updated {deps_updated} deps, deleted {deps_deleted} duplicate deps, '
                            f'updated {dependents_updated} dependents, deleted {dependents_deleted} duplicate dependents)'
                        )
                        
                        # Delete duplicate
                        dup.delete()
                        packages_deleted += 1
                    
                    # Update primary package to have normalized name (lowercase) AFTER deleting duplicates
                    if primary.name != normalized_name:
                        self.stdout.write(f'  Normalizing primary name: {primary.name} -> {normalized_name}')
                        primary.name = normalized_name
                    
                    # Save primary with merged data
                    primary.save()
                    packages_merged += 1
            else:
                self.stdout.write(f'  Would merge {len(duplicates)} duplicate(s) into primary')
        
        # Summary
        self.stdout.write(f'\n{self.style.SUCCESS("Summary:")}')
        self.stdout.write(f'  Duplicate groups found: {duplicates_found}')
        
        if dry_run:
            self.stdout.write(f'  Would merge: {sum(len(pkgs)-1 for pkgs in package_groups.values() if len(pkgs) > 1)} packages')
        else:
            self.stdout.write(f'  Packages merged: {packages_merged}')
            self.stdout.write(f'  Packages deleted: {packages_deleted}')
            self.stdout.write(self.style.SUCCESS('✓ Deduplication complete!'))
