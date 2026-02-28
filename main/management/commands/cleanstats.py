import logging
from datetime import datetime

from django.core.management.base import BaseCommand
from django.db.models import Avg, Max, Q, Sum
from django.db.models.expressions import RawSQL
from django.utils.timezone import make_aware

from main.models import Album, Artist, Rating, Song

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Cleans and recalculates stats for songs, albums, and artists.'

    def add_arguments(self, parser):
        """Cmd args."""
        parser.add_argument(
            'target',
            nargs='?',
            choices=['songs', 'albums', 'artists'],
            help='Specify which stats to clean: songs, albums, artists. If omitted, runs all.',
        )

    def handle(self, *args, **options):
        """Run cmd."""
        target = options['target']

        if target is None:
            logger.info('No subcommand provided. Running all: songs → albums → artists')
            self.clean_songs()
            self.clean_albums()
            self.clean_artists()
        elif target == 'songs':
            self.clean_songs()
        elif target == 'albums':
            self.clean_albums()
        elif target == 'artists':
            self.clean_artists()

    def clean_songs(self):
        """Clean songs."""
        dirty_songs = Song.objects.filter(is_dirty=True)
        total = dirty_songs.count()
        logger.info(f'Cleaning {total} dirty songs...')

        updated_album_ids = set()

        for i, song in enumerate(dirty_songs, start=1):
            # Ratings
            ratings = Rating.objects.filter(Q(winner=song) | Q(loser=song))
            count = ratings.count()

            if count == 0:
                song.rating = 0
                song.count_rated = 0
                song.rated_at = None
            else:
                song.count_rated = count
                song.rating = Rating.objects.filter(winner=song).count() / count
                song.rated_at = ratings.aggregate(Max('rated_at'))['rated_at__max']

            # Play history
            song.count_played = song.histories.count()
            song.played_at = song.histories.aggregate(Max('played_at'))['played_at__max']

            song.is_dirty = False
            song.save(
                update_fields=[
                    'rating',
                    'count_rated',
                    'rated_at',
                    'count_played',
                    'played_at',
                    'is_dirty',
                ]
            )

            updated_album_ids.add(song.album_id)
            logger.debug(f'[{i}/{total}] Updated song {song.id}')

        updated = Album.objects.filter(id__in=updated_album_ids).update(is_dirty=True)
        logger.info(f'Marked {updated} albums as dirty.')

    def clean_albums(self):
        """Clean albums."""
        dirty_albums = Album.objects.filter(is_dirty=True)
        total = dirty_albums.count()
        logger.info(f'Cleaning {total} dirty albums...')

        updated_artist_ids = set()

        for i, album in enumerate(dirty_albums, start=1):
            # ensure current values
            album.count_songs = album.songs.count()

            # Ratings
            song_agg = album.songs.aggregate(
                rating=Avg('rating'),
                rated_at=Max('rated_at'),
                count_rated=Sum('count_rated'),
                count_played=Sum('count_played'),
                played_at=Max('played_at'),
            )
            album.rating = song_agg['rating'] or 0
            album.rated_at = song_agg['rated_at']
            album.count_rated = song_agg['count_rated'] or 0
            album.count_played = song_agg['count_played'] or 0
            album.played_at = song_agg['played_at']

            # avg_played_at using SQLite timestamp cast
            avg_played_at = album.songs.aggregate(
                avg_played_at=Avg(RawSQL("strftime('%%s', played_at)", []))
            )['avg_played_at']
            album.avg_played_at = (
                make_aware(datetime.fromtimestamp(avg_played_at)) if avg_played_at else None
            )

            album.is_dirty = False
            album.save(
                update_fields=[
                    'rating',
                    'rated_at',
                    'count_rated',
                    'count_played',
                    'played_at',
                    'avg_played_at',
                    'is_dirty',
                ]
            )

            updated_artist_ids.add(album.artist_id)
            logger.debug(f'[{i}/{total}] Updated album {album.id}')

        updated = Artist.objects.filter(id__in=updated_artist_ids).update(is_dirty=True)
        logger.info(f'Marked {updated} artists as dirty.')

    def clean_artists(self):
        """Clean artists."""
        dirty_artists = Artist.objects.filter(is_dirty=True)
        total = dirty_artists.count()
        logger.info(f'Cleaning {total} dirty artists...')

        for i, artist in enumerate(dirty_artists, start=1):
            # ensure current values
            artist.count_albums = artist.albums.count()
            artist.count_songs = artist.songs.count()

            # ratings
            album_agg = artist.albums.aggregate(
                count_rated=Sum('count_rated'),
                count_played=Sum('count_played'),
                rated_at=Max('rated_at'),
                played_at=Max('played_at'),
            )
            song_agg = artist.songs.aggregate(
                rating=Avg('rating'),
                avg_played_at=Avg(RawSQL("strftime('%%s', played_at)", [])),
            )

            artist.rating = song_agg['rating'] or 0
            artist.rated_at = album_agg['rated_at']
            artist.count_rated = album_agg['count_rated'] or 0
            artist.count_played = album_agg['count_played'] or 0
            artist.played_at = album_agg['played_at']
            artist.avg_played_at = (
                make_aware(datetime.fromtimestamp(song_agg['avg_played_at']))
                if song_agg['avg_played_at']
                else None
            )

            artist.is_dirty = False
            artist.save(
                update_fields=[
                    'rating',
                    'rated_at',
                    'count_rated',
                    'count_played',
                    'played_at',
                    'avg_played_at',
                    'is_dirty',
                ]
            )

            logger.debug(f'[{i}/{total}] Updated artist {artist.id}')

        logger.info(f'Updated {total} artists.')
