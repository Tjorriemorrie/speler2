import logging
import random
from typing import List, Tuple

from django.core.cache import cache
from django.db import connection
from django.db.models import ExpressionWrapper, F, FloatField, Max, Sum, Value
from django.db.models.expressions import Func, RawSQL
from django.utils import timezone

from main.models import Artist, History, Song

logger = logging.getLogger(__name__)


def get_next_song() -> Song:
    """Get next song to play."""
    # First play unrated songs
    if (unrated_songs := Song.objects.filter(count_played=0)).exists():
        song = random.choice(unrated_songs)  # noqa: S311
        logger.info(f'Returning unplayed random song: {song}')
        return song

    max_played, avg_days_last_played = get_next_song_priority_values()

    # Calculate time since played using raw SQL
    time_since_played_expr = RawSQL("(julianday('now') - julianday(main_song.played_at))", [])

    # Annotate priority
    songs_with_priority = Song.objects.annotate(
        time_since_played=ExpressionWrapper(time_since_played_expr, output_field=FloatField()),
        priority=(
            F('rating')
            - (F('count_played') / Value(max_played))
            + (F('time_since_played') / Value(avg_days_last_played))
        ),
    ).order_by('-priority')

    # Get the song with the highest priority
    highest_priority_song = songs_with_priority.first()

    logger.info('Highest Priority Song: {}'.format(highest_priority_song))
    return highest_priority_song


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

    return history


# Custom SQL function to use with Django ORM
class Julianday(Func):
    function = 'julianday'
    template = '%(function)s(%(expressions)s)'


def get_next_song_priority_values() -> Tuple[int, float]:
    """Get values for calculated priority with caching."""
    cache_key = 'next_song_priority_values'
    cached_values = cache.get(cache_key)

    if cached_values is not None:
        return cached_values

    # Calculate max_played
    max_played = Song.objects.aggregate(Max('count_played'))['count_played__max']

    raw_sql = """
        SELECT
            AVG(julianday(played_at)) AS avg_julian_day,
            julianday('now') AS current_julian_day
        FROM main_song
    """

    # Execute raw SQL
    with connection.cursor() as cursor:
        cursor.execute(raw_sql)
        avg_julian_day, current_julian_day = cursor.fetchone()

    if avg_julian_day is None:
        avg_days_last_played = 1  # Default value if no data
    else:
        # Calculate days since average Julian Day
        avg_days_last_played = int(round(current_julian_day - avg_julian_day))

        # Ensure the value is at least 1 to avoid division by zero
        avg_days_last_played = max(avg_days_last_played, 1)

    # Cache the values for 1 hour (3600 seconds)
    cache.set(cache_key, (max_played, avg_days_last_played), timeout=3600)

    return max_played, avg_days_last_played


def get_artists_ranked_around(current_artist: Artist) -> List[Artist]:
    """Return artists around selected artist."""
    artists = Artist.objects.order_by('-rating')

    # Find the index of the current artist
    current_artist = artists.get(id=current_artist.id)
    artist_list = list(artists)
    current_index = artist_list.index(current_artist)

    # If the current artist is the first in the ranking, return 2 below
    if current_index == 0:
        result = artist_list[:3]  # Top 3 artists
    # If the current artist is the last in the ranking, return 2 above
    elif current_index == len(artist_list) - 1:
        result = artist_list[-3:]  # Last 3 artists
    # Otherwise, return the artist above, the current one, and the artist below
    else:
        result = artist_list[current_index - 1 : current_index + 2]

    return result
