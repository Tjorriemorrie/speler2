import logging

from django.core.management import BaseCommand

from main.lyrics import scrape_billboards
from main.musicfiles import recheck_metadata, scan_directory, validate_songs

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Parse music folder.'

    def add_arguments(self, parser):
        """Add arguments."""
        subparsers = parser.add_subparsers(
            title='sub-commands',
            required=True,
        )

        # Scan parser
        scan_parser = subparsers.add_parser(
            'scan',
            help='Scan music folder.',
        )
        scan_parser.set_defaults(method=scan_directory)

        # Validate parser
        validate_parser = subparsers.add_parser(
            'validate',
            help='Validate songs.',
        )
        validate_parser.add_argument(
            '--no-delete',
            action='store_false',
            dest='delete',
            help='Do not delete invalid songs',
        )
        validate_parser.set_defaults(method=validate_songs, delete=True)

        # Recheck metadata parser
        recheck_parser = subparsers.add_parser(
            'recheckmetadata',
            help='Recheck metadata of songs and albums.',
        )
        recheck_parser.set_defaults(method=recheck_metadata)

        # Scrape Billboards parser
        scrape_parser = subparsers.add_parser(
            'scrapebillboards',
            help='Scrape billboard charts.',
        )
        scrape_parser.set_defaults(method=scrape_billboards)

    def handle(self, *args, method, **options):
        """Run cmd."""
        method(*args, **options)
