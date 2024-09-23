import logging
import random
from typing import Tuple

from django.conf import settings
from django.core.cache import cache
from django.db import connection
from django.db.models import ExpressionWrapper, F, FloatField, Max, Sum, Value
from django.db.models.expressions import Func, RawSQL
from django.utils import timezone

from main.lastfm_service import scrobble
from main.models import History, Song

logger = logging.getLogger(__name__)


def get_next_song() -> Song:
    """Get next song to play."""
    # First play unrated songs
    if (unrated_songs := Song.objects.filter(count_played=0)).exists():
        song = random.choice(unrated_songs)  # noqa: S311
        logger.info(f'Returning unplayed random song: {song}')
        return song

    max_played, time_till_last_played = get_next_song_priority_values()

    # Calculate time since played using raw SQL
    time_since_played_expr = RawSQL("(julianday('now') - julianday(main_song.played_at))", [])

    query = Song.objects
    # filter on facet
    if filter_facet := cache.get('filter_facet'):
        logger.info(f'Filtering on {filter_facet}')
        query = query.filter(**filter_facet)
    # Annotate priority
    songs_with_priority = query.annotate(
        time_since_played=ExpressionWrapper(time_since_played_expr, output_field=FloatField()),
        priority=(
            F('rating')
            - (F('count_played') / Value(max_played))
            + (F('time_since_played') / Value(time_till_last_played))
        ),
    ).order_by('-priority')

    # Get the song with the highest priority
    next_song = songs_with_priority.first()
    if not next_song:
        raise ValueError('Expected to get a song, but found nothing')

    logger.info(f'Next Song: {next_song}')
    # playd = next_song.count_played / max_played
    # tspd = next_song.time_since_played / time_till_last_played
    # calculated_priority = next_song.rating - playd + tspd
    logger.info(f'Next Song: priority {next_song.priority:.3f}')
    # logger.info(f'Next Song: calc {calculated_priority:.3f}')
    # logger.info(f'Next Song: rating {next_song.rating:.2f}')
    # logger.info(f'Next Song: played {playd:.2f} ({next_song.count_played} / {max_played})')
    # logger.info(
    #     f'Next Song: days {tspd:.2f} ({next_song.time_since_played} / {time_till_last_played})'
    # )
    return next_song


def set_played(song: Song) -> History:
    """Increase play stats for song."""
    history = History.objects.create(song=song, played_at=timezone.now())

    song.count_played = song.histories.count()
    song.played_at = song.histories.aggregate(Max('played_at'))['played_at__max']
    song.save()

    album = song.album
    album.count_played = album.songs.aggregate(Sum('count_played'))['count_played__sum']
    album.played_at = album.songs.aggregate(Max('played_at'))['played_at__max']
    album.save()

    artist = album.artist
    artist.count_played = artist.albums.aggregate(Sum('count_played'))['count_played__sum']
    artist.played_at = artist.albums.aggregate(Max('played_at'))['played_at__max']
    artist.save()

    if settings.LASTFM_ENABLE:
        scrobble(history)

    return history


# Custom SQL function to use with Django ORM
class Julianday(Func):
    function = 'julianday'
    template = '%(function)s(%(expressions)s)'


def get_next_song_priority_values() -> Tuple[float, float]:
    """Get values for calculated priority with caching."""
    cache_key = 'next_song_priority_values'
    cached_values = cache.get(cache_key)

    if cached_values is not None:
        return cached_values

    # Calculate max_played
    max_played = float(Song.objects.aggregate(Max('count_played'))['count_played__max'])

    raw_sql = """
        SELECT
            MIN(julianday(played_at)) AS earliest_julian_day,
            julianday('now') AS current_julian_day
        FROM main_song
    """

    # Execute raw SQL
    with connection.cursor() as cursor:
        cursor.execute(raw_sql)
        earliest_julian_day, current_julian_day = cursor.fetchone()
        logger.info(f'earliest julian: {earliest_julian_day}')
        logger.info(f'cur julian: {current_julian_day}')

    if earliest_julian_day is None:
        julian_till_earliest = 1  # Default value if no data
    else:
        # Calculate days since earliest Julian Day
        julian_till_earliest = current_julian_day - earliest_julian_day

        # Ensure the value is at least 1 to avoid division by zero
        julian_till_earliest = max(julian_till_earliest, 1)

    # Cache the values for 2 hour (3600 seconds * 2)
    cache.set(cache_key, (max_played, julian_till_earliest), timeout=7200)

    return max_played, julian_till_earliest
