import logging
import random
from collections import defaultdict
from datetime import datetime
from typing import Tuple, Union

from django.core.cache import cache
from django.db import connection
from django.db.models import Avg, ExpressionWrapper, F, FloatField, Max, Sum, Value
from django.db.models.expressions import Func, RawSQL
from django.utils import timezone
from django.utils.timezone import make_aware
from unidecode import unidecode

from main.constants import LIST_GENRES, RATINGS_WINDOW
from main.lastfm_service import scrobble
from main.models import Album, Artist, History, Song
from main.selectors import get_recent_artist_ids

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
    # but exclude recent artist, to prevent single artist spam
    limit = RATINGS_WINDOW // 60
    recent_artist_ids = get_recent_artist_ids()
    songs = list(songs_with_priority.all()[:limit])  # Query once and store in memory
    next_song = None
    artists_already_played = defaultdict(int)
    # Iterate over the songs and check if the artist was recently played
    for song in songs:
        if song.artist.id not in recent_artist_ids:
            next_song = song  # Found a valid song, assign it
            break
        artists_already_played[song.artist.name] += 1
    if artists_already_played:
        aap_str = ', '.join(f'{k} (x{v})' for k, v in artists_already_played.items())
        logger.info(f'>>>>>>>>>> Already played: {unidecode(aap_str)}')
    # If no valid song is found, randomly select one from the top 100
    if not next_song and songs:
        logger.info('Could not find any unplayed artist in first 100 priority queue!')
        next_song = random.choice(songs)  # noqa: S311
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
    # Convert 'played_at' to a Unix timestamp using SQLite's strftime
    avg_played_at = album.songs.aggregate(
        avg_played_at=Avg(RawSQL("strftime('%%s', played_at)", []))
    )['avg_played_at']
    album.avg_played_at = (
        make_aware(datetime.fromtimestamp(avg_played_at)) if avg_played_at else None
    )
    album.save()

    artist = album.artist
    artist.count_played = artist.albums.aggregate(Sum('count_played'))['count_played__sum']
    artist.played_at = artist.albums.aggregate(Max('played_at'))['played_at__max']
    # Convert 'played_at' to a Unix timestamp using SQLite's strftime
    avg_played_at = artist.songs.aggregate(
        avg_played_at=Avg(RawSQL("strftime('%%s', played_at)", []))
    )['avg_played_at']
    artist.avg_played_at = (
        make_aware(datetime.fromtimestamp(avg_played_at)) if avg_played_at else None
    )
    artist.save()

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
        logger.info(f'current julian: {current_julian_day}')
    diff = round(current_julian_day - earliest_julian_day)
    logger.info(f'Days to earliest is {diff:.0f} days')

    if earliest_julian_day is None:
        earliest_julian_diff = 1.0  # Default value if no data
    else:
        # Calculate days since earliest Julian Day
        earliest_julian_diff = current_julian_day - earliest_julian_day

        # Ensure the value is at least 1 to avoid division by zero
        earliest_julian_diff = max(earliest_julian_diff, 1.0)

    # adjust the earliest day to prevent spam of top hits
    # 2.0-1.8 does not work when adding album, then it plays hits immediately afterward
    adj = 1.66
    adj_earliest_julian_diff = earliest_julian_diff * adj
    diff_adj = round(adj_earliest_julian_diff - earliest_julian_diff)
    logger.info(
        f'Diff {earliest_julian_diff} adj with {adj}x [{diff_adj} days] '
        f'gives {adj_earliest_julian_diff}'
    )

    # Cache the values for 2 hour (3600 seconds * 2)
    cache.set(cache_key, (max_played, adj_earliest_julian_diff), timeout=7200)

    return max_played, adj_earliest_julian_diff


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
