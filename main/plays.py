import logging
import math
import random
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Tuple, Union

import numpy as np
import simpleaudio as sa
from django.conf import settings
from django.core.cache import cache
from django.db import connection
from django.db.models import Avg, ExpressionWrapper, F, FloatField, Max, Sum, Value
from django.db.models.expressions import Case, Func, RawSQL, When
from django.utils import timezone
from django.utils.timezone import make_aware
from unidecode import unidecode

from main.constants import LIST_GENRES
from main.lastfm_service import scrobble
from main.models import Album, Artist, History, Song
from main.selectors import get_recent_artists

logger = logging.getLogger(__name__)

MIN_SONGS_FOR_AVG = 100
DEFAULT_AVG_SONG_LENGTH = 240.0
MIN_LOOKUP_LIMIT = 50
COUNTDOWN_MIN_POINTS = 4
# a rating match needs the recent history to hold songs that have been played
# before, so until the window has this many entries a brand new song is skipped
MIN_HISTORY_FOR_NEW_SONGS = 4
COUNTDOWN_MIN_SLOPE = -1e-6
COUNTDOWN_ALPHA = 0.2


def _compute_average_song_length() -> float:
    song_count = Song.objects.count()
    if song_count < MIN_SONGS_FOR_AVG:
        return DEFAULT_AVG_SONG_LENGTH
    avg_length = Song.objects.aggregate(avg=Avg('track_length'))['avg']
    return float(avg_length) if avg_length else DEFAULT_AVG_SONG_LENGTH


def _compute_next_song_lookup_limit() -> int:
    artist_count = Artist.objects.count()
    return max(artist_count, MIN_LOOKUP_LIMIT)


def _slope_steps_remaining(series: list, smoothed_value: float) -> Union[int, None]:
    """Extrapolate a smoothed metric's history down its recent slope to a song count.

    Returns None when the series isn't trending down enough to extrapolate
    (too few points, or flat/rising), meaning the countdown is unbounded.
    """
    m = (
        np.polyfit(np.arange(len(series)), series, 1)[0]
        if len(series) >= COUNTDOWN_MIN_POINTS
        else 0.0
    )
    if m >= COUNTDOWN_MIN_SLOPE:
        return None
    return max(math.ceil(smoothed_value / -m), 0)


AVERAGE_SONG_LENGTH = _compute_average_song_length()
next_song_lookup_limit = _compute_next_song_lookup_limit()
num_slots_in_window = next_song_lookup_limit * 0.07
# one rotation's worth of history: long enough to see a trend, short enough that
# a spike from an album add falls out of the slope fit once the queue moves past it
COUNTDOWN_WINDOW = max(int(num_slots_in_window), COUNTDOWN_MIN_POINTS)
RATINGS_WINDOW = num_slots_in_window * AVERAGE_SONG_LENGTH * 1.1


def get_next_song() -> Song:  # noqa: PLR0912, PLR0915
    """Get next song to play."""
    logger.info(
        f'Ratings window is {RATINGS_WINDOW / 60:.0f} min ({num_slots_in_window:.0f} slots)'
    )
    max_played, time_till_last_played = get_next_song_priority_values()

    # Calculate time since played using raw SQL
    time_since_played_expr = RawSQL(
        "(julianday('now') - julianday(COALESCE(main_song.played_at, '1982-08-04')))", []
    )

    query = Song.objects

    # filter on facet
    if filter_facet := cache.get('filter_facet'):
        logger.info(f'Filtering on facet {filter_facet}')
        query = query.filter(**filter_facet)

    # filter on genre
    if filter_genres := cache.get('filter_genres'):
        logger.info(f'Filtering on genres {filter_genres}')
        query = query.filter(**filter_genres)

    # bump the worst albums
    # worst_albums_ids = [a.id for a in list_lowest_rated_albums()]

    # Annotate priority
    weight_played_once = 0.26
    # weight_bad_album = 0.4
    songs_with_priority = (
        query.annotate(
            time_since_played=ExpressionWrapper(time_since_played_expr, output_field=FloatField()),
            base_priority=(
                F('rating')
                - (F('count_played') / Value(max_played))
                + (F('time_since_played') / Value(time_till_last_played))
            ),
        )
        .annotate(
            priority=ExpressionWrapper(
                F('base_priority')
                + Case(
                    When(count_played=1, then=Value(weight_played_once)),
                    default=Value(0.0),
                    output_field=FloatField(),
                ),
                # + Case(
                #     When(album_id__in=worst_albums_ids, then=Value(weight_bad_album)),
                #     default=Value(0.0),
                #     output_field=FloatField(),
                # )
                output_field=FloatField(),
            )
        )
        .order_by('-priority')
    )

    # Get the song with the highest priority
    # but exclude recent artist, to prevent single artist spam
    queue = defaultdict(int)
    history_artists = get_recent_artists()
    history_artist_names = set()
    for history_artist in reversed(history_artists):
        queue[history_artist.song.artist.name] = 0
        history_artist_names.add(history_artist.song.artist.name)

    # Query once and store in memory (for rnd)
    songs = list(songs_with_priority.all()[:next_song_lookup_limit])

    # an unplayed song has nothing to rate against, so while the history window is
    # still filling up skip past them - unless every candidate is new, in which
    # case there is nothing to skip to and the normal priority order stands
    played_songs = [song for song in songs if song.count_played]
    skip_new_songs = len(history_artists) < MIN_HISTORY_FOR_NEW_SONGS and bool(played_songs)
    if skip_new_songs:
        logger.info(
            f'Skipping new songs: history={len(history_artists)}/{MIN_HISTORY_FOR_NEW_SONGS}, '
            f'played_candidates={len(played_songs)}/{len(songs)}'
        )

    next_song = None
    # Iterate over the songs and check if the artist was recently played
    for song in songs:
        if song.artist.name in queue:
            queue[song.artist.name] += 1
            # logger.info(f'Increased existing artist on queue {unidecode(song.artist.name)}')
        elif not next_song and not (skip_new_songs and not song.count_played):
            next_song = song
            queue[song.artist.name] = 0
            history_artist_names.add(song.artist.name)
            # logger.info(f'Found next song {next_song}')

    # If no valid song is found, randomly select one from the top 100
    if not next_song and songs:
        next_song = random.choice(played_songs if skip_new_songs else songs)  # noqa: S311
        cowbell_path = settings.SOUNDS_DIR / 'mixkit-cowbell-sharp-hit-1743.wav'
        sa.WaveObject.from_wave_file(str(cowbell_path)).play()
        logger.info(
            f'{"!" * 5} Could not find any unplayed artist in first '
            f'{next_song_lookup_limit} priority queue!'
        )
    elif next_song:
        space_per_artist = 3
        unique_count = len(history_artist_names)
        # median, not mean: a freshly added album puts a dozen-plus of its songs
        # near the top of the priority queue, and one such artist drags the mean
        # far enough up to hold the gate open indefinitely. the median reads what
        # we actually want, the backlog of a typical artist in rotation. the
        # "an album was just added" signal is time_buffer_steps' job, below
        upcoming = (
            float(np.median([queue[name] for name in history_artist_names])) - space_per_artist
        )
        # too few unique artists and too many repeats queued are the same
        # underlying symptom (an album add flooding the top of the priority
        # queue with one artist) seen from two angles, so gate on whichever
        # one hasn't recovered yet rather than tracking two countdowns
        artist_gap = num_slots_in_window - unique_count
        gate = max(upcoming, artist_gap)

        # smooth before storing: each song moves the raw average by a discrete
        # step, so the series zig-zags and a line fitted through it twitches.
        # an EMA damps the song-to-song jitter but still follows a real change
        countdown = cache.get('add_album_countdown', [])
        smoothed = (
            COUNTDOWN_ALPHA * gate + (1 - COUNTDOWN_ALPHA) * countdown[-1] if countdown else gate
        )
        countdown = (countdown + [smoothed])[-COUNTDOWN_WINDOW:]
        cache.set('add_album_countdown', countdown, timeout=None)
        logger.info(
            f'Countdown: {", ".join(f"{x:.2f}" for x in countdown)} '
            f'({unique_count}/{num_slots_in_window:.0f} artists)'
        )

        # a newly added album still needs its ratings window to elapse before
        # another add is suggested; convert the remaining window time into an
        # estimated song count so it reads the same as the queue-based countdown
        latest_created_at = Song.objects.latest('created_at').created_at
        window_time_ago = timezone.now() - timedelta(seconds=RATINGS_WINDOW / 2)
        time_buffer_steps = 0
        if latest_created_at > window_time_ago:
            seconds_since_added = (timezone.now() - latest_created_at).total_seconds()
            seconds_remaining = RATINGS_WINDOW - seconds_since_added
            time_buffer_steps = max(math.ceil(seconds_remaining / AVERAGE_SONG_LENGTH), 0)

        # gate on the smoothed value, not the raw one: the raw gate can dip
        # to 0 for a single song while the EMA trend is still above it, which
        # would fire "do it!" a beat too early
        if smoothed > 0:
            # give countdown estimate: extrapolate the current value down at
            # the recent slope. the stored history is capped at one rotation so
            # the slope is local to the same stretch the level came from --
            # fitting a longer decay curve gives a slope from its steep early
            # part and a level from its flat tail, which reads far too optimistic
            steps = _slope_steps_remaining(countdown, smoothed)
            if steps is None:
                logger.info(f'{"." * 5} Add album: oo')
            else:
                # floor it against the recently-added time buffer so the
                # estimate never undercuts the ratings window still in effect
                steps_remaining = max(steps, time_buffer_steps)
                logger.info(f'{"." * 5} Add album: in ~{steps_remaining} songs')

        # countdown says "do it" but the ratings window buffer is still running
        elif time_buffer_steps:
            logger.info(f'{"." * 5} Add album: in ~{time_buffer_steps} songs')

        else:
            waterdrop_path = settings.SOUNDS_DIR / 'mixkit-water-bubble-1317.wav'
            sa.WaveObject.from_wave_file(str(waterdrop_path)).play()
            logger.info(f'{"+" * 5} Add album: do it!')
    if not next_song:
        raise ValueError('Expected to get a song, but found nothing')

    for name, cnt in queue.items():
        symbol = '>' if next_song.artist.name == name else '-'
        cnt_txt = f'{"+" * cnt}'
        logger.info(f'{symbol * 5} {unidecode(name)} {cnt_txt}')

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
              SELECT MIN(julianday(played_at)) AS earliest_julian_day,
                     julianday('now')          AS current_julian_day
              FROM main_song \
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
    # the bigger the mul is from 1.0, the bigger the denominator is,
    #   making the value smaller, meaning the last played song's value is lowered,
    #   giving it less weight - vs the rating value which will then have more weight
    # values below 1.0 will increase value of ratio
    adj = 2.0
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
