"""
Django management command to update GPG keys for Mock builds
"""
from django.core.management.base import BaseCommand, CommandError
from django.conf import settings
from backend.core.gpg_key_manager import get_gpg_key_manager
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Update GPG keys from distribution-gpg-keys repository'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--force',
            action='store_true',
            help='Force update even if cache is recent',
        )
        parser.add_argument(
            '--verify-only',
            action='store_true',
            help='Only verify keys are installed, do not update',
        )
        parser.add_argument(
            '--info',
            action='store_true',
            help='Show information about cached keys',
        )
        parser.add_argument(
            '--distribution',
            type=str,
            default='redhat',
            help='Distribution to show info for (default: redhat)',
        )
    
    def handle(self, *args, **options):
        force = options['force']
        verify_only = options['verify_only']
        show_info = options['info']
        distribution = options['distribution']
        
        # Get cache directory from settings
        reqpm_config = getattr(settings, 'REQPM', {})
        cache_dir = reqpm_config.get('GPG_KEYS_CACHE_DIR', '/var/cache/reqpm/distribution-gpg-keys')
        
        # Create GPG key manager
        manager = get_gpg_key_manager(cache_dir=cache_dir)
        
        # Show info mode
        if show_info:
            self.stdout.write(self.style.SUCCESS(f'\nGPG Key Information for {distribution}:'))
            info = manager.get_key_info(distribution)
            
            if info['cache_exists']:
                self.stdout.write(f"  Cache age: {info['cache_age']} days")
            else:
                self.stdout.write(self.style.WARNING("  No cache found"))
            
            if info['keys']:
                self.stdout.write(f"\n  Found {len(info['keys'])} keys:")
                for key in info['keys']:
                    self.stdout.write(f"    - {key['name']} ({key['size']} bytes)")
            else:
                self.stdout.write(self.style.WARNING(f"  No keys found for {distribution}"))
            
            return
        
        # Verify only mode
        if verify_only:
            self.stdout.write('\nVerifying GPG keys installation...')
            success, message = manager.verify_keys_installed()
            
            if success:
                self.stdout.write(self.style.SUCCESS(f'✓ {message}'))
            else:
                self.stdout.write(self.style.ERROR(f'✗ {message}'))
                self.stdout.write(self.style.WARNING('\nRun without --verify-only to update keys'))
            
            return
        
        # Update mode
        self.stdout.write('\nUpdating GPG keys from distribution-gpg-keys repository...')
        
        if force:
            self.stdout.write(self.style.WARNING('Force update enabled - ignoring cache'))
        
        # Check if update is needed
        if not force and not manager.is_update_needed():
            self.stdout.write(self.style.SUCCESS('✓ GPG keys are already up to date'))
            
            # Verify installation
            success, message = manager.verify_keys_installed()
            if success:
                self.stdout.write(self.style.SUCCESS(f'✓ {message}'))
            else:
                self.stdout.write(self.style.WARNING(f'⚠ {message}'))
            
            return
        
        # Perform update
        self.stdout.write('Downloading and updating keys...')
        success, message = manager.update_keys(force=force)
        
        if success:
            self.stdout.write(self.style.SUCCESS(f'✓ {message}'))
            
            # Show key info
            info = manager.get_key_info('redhat')
            if info['keys']:
                self.stdout.write(self.style.SUCCESS(f'✓ Found {len(info["keys"])} Red Hat keys'))
        else:
            self.stdout.write(self.style.ERROR(f'✗ {message}'))
            raise CommandError('Failed to update GPG keys')
        
        self.stdout.write(self.style.SUCCESS('\n✓ GPG keys updated successfully'))
        self.stdout.write('\nNote: Mock builds will now use the updated keys')
