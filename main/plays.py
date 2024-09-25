import logging
import random
from typing import Tuple, Union

from django.conf import settings
from django.core.cache import cache
from django.db import connection
from django.db.models import ExpressionWrapper, F, FloatField, Max, Sum, Value
from django.db.models.expressions import Func, RawSQL
from django.utils import timezone

from main.constants import LIST_GENRES
from main.lastfm_service import scrobble
from main.models import Album, Artist, History, Song

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
        logger.info(f'Filtering on facet {filter_facet}')
        query = query.filter(**filter_facet)

    # filter on genre
    if filter_genres := cache.get('filter_genres'):
        logger.info(f'Filtering on genres {filter_genres}')
        query = query.filter(**filter_genres)

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
            AVG(julianday(played_at)) AS avg_julian_day,
            julianday('now') AS current_julian_day
        FROM main_song
    """

    # Execute raw SQL
    with connection.cursor() as cursor:
        cursor.execute(raw_sql)
        avg_julian_day, current_julian_day = cursor.fetchone()
        logger.info(f'avg julian: {avg_julian_day}')
        logger.info(f'cur julian: {current_julian_day}')

    if avg_julian_day is None:
        julian_till_avg = 1.0  # Default value if no data
    else:
        # Calculate days since earliest Julian Day
        julian_till_avg = current_julian_day - avg_julian_day

        # Ensure the value is at least 1 to avoid division by zero
        julian_till_avg = max(julian_till_avg, 1.0)

    # Cache the values for 2 hour (3600 seconds * 2)
    cache.set(cache_key, (max_played, julian_till_avg), timeout=7200)

    return max_played, julian_till_avg


def set_genre(instance: Union[Artist, Album, Song], genre: str):
    """Set genre."""
    instance.genre = genre
    instance.save()
    logger.info(f'Genre: {instance} set to {genre}')

    # propagate
    if isinstance(instance, Artist):
        instance.albums.update(genre=genre)
        logger.info(f'Genre: {instance.albums.count()} albums set to {genre}')
        instance.songs.update(genre=genre)
        logger.info(f'Genre: {instance.songs.count()} albums set to {genre}')
    elif isinstance(instance, Album):
        # Update all related songs for the album
        instance.songs.update(genre=genre)
        logger.info(f'Genre: {instance.songs.count()} albums set to {genre}')


def handle_genre_filter(genre: str):
    """Handle genre selection."""
    filter_genres = cache.get('filter_genres')

    # if no existing setting, then set as filter
    if not filter_genres:
        cache.set('filter_genres', {'genre__in': [genre]}, timeout=None)
        return

    genres_selected = filter_genres['genre__in']

    # Add or remove the value
    if genre in genres_selected:
        genres_selected.remove(genre)  # Remove if it exists
    else:
        genres_selected.append(genre)  # Add if it does not exist

    # if all selected, can also remove filter
    if len(genres_selected) == LIST_GENRES:
        cache.delete('filter_genres')
        return

    cache.set('filter_genres', {'genre__in': genres_selected}, timeout=None)
