import logging

from django.core.management import BaseCommand

from main.musicfiles import scan_directory, validate_songs

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Parse music folder.'

    def add_arguments(self, parser):
        """Add arguments."""
        subparsers = parser.add_subparsers(
            title='sub-commands',
            required=True,
        )

        scan_parser = subparsers.add_parser(
            'scan',
            help='Scan music folder.',
        )
        scan_parser.set_defaults(method=scan_directory)

        validate_parser = subparsers.add_parser(
            'validate',
            help='Validate songs.',
        )
        validate_parser.set_defaults(method=validate_songs)

    def handle(self, *args, method, **options):
        """Run cmd."""
        method(*args, **options)
