from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from main.backgrounds import fetch_backgrounds
from main.models import Artist


class Command(BaseCommand):
    help = 'Downloads fanart.tv background photos of every artist not fetched yet. Safe to rerun.'

    def add_arguments(self, parser):
        """Add --all."""
        parser.add_argument(
            '--all', action='store_true', help='Ask again for every artist, for new uploads.'
        )

    def handle(self, *args, **options):
        """Fetch each artist in turn; failures are left for the next run."""
        if not settings.FANARTTV_API_KEY:
            raise CommandError('Set FANARTTV_API_KEY in .env first.')
        artists = Artist.objects.order_by('name')
        if not options['all']:
            artists = artists.filter(backgrounds_at__isnull=True)
        artists = list(artists)
        failed = [artist.name for artist in artists if not fetch_backgrounds(artist)]
        self.stdout.write(f'Backgrounds: artists={len(artists)}, failed={failed}')
