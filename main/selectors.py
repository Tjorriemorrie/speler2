import logging
from datetime import datetime, timedelta
from random import randint
from typing import List

import plotly.graph_objects as go
from django.core.cache import cache
from django.db.models import (
    Avg,
    BooleanField,
    Count,
    ExpressionWrapper,
    F,
    Max,
    Min,
    Q,
    QuerySet,
    Sum,
    Value,
)
from django.db.models.expressions import RawSQL
from django.db.models.functions import Greatest, TruncDate, TruncWeek
from django.utils import timezone
from django.utils.timezone import make_aware

from main.models import Album, Artist, History, Rating, Song
from main.ratings import get_album_rating, get_artist_rating, get_mean_rating

logger = logging.getLogger(__name__)

DAILY_TO_WEEKLY_THRESHOLD_DAYS = 365
# a bad album with any song below these has not had a fair chance yet, so it is struck through
BAD_ALBUM_MIN_SONG_PLAYS = 2
BAD_ALBUM_MIN_SONG_RATINGS = 10


def get_play_count_chart():
    """Chart play count bar."""
    cache_key = 'play_count'
    if graph := cache.get(cache_key):
        logger.info(f'Graph served from cache: {cache_key}')
        return graph
    logger.info(f'Graph rendering fresh: {cache_key}')

    # Query to aggregate song play count
    song_stats = (
        Song.objects.values('count_played')
        .annotate(song_count=Count('id'))
        .order_by('count_played')
    )

    x = [stat['count_played'] for stat in song_stats]
    y = [stat['song_count'] for stat in song_stats]

    # Create the bar chart using graph_objects
    fig = go.Figure(data=[go.Bar(x=x, y=y)])

    # Customize the layout if needed
    fig.update_layout(
        title='Songs per Play Count',
        xaxis_title='Play Count',
        yaxis_title='Number of Songs',
        autosize=True,
        margin=dict(l=20, r=20, t=30, b=20),
        xaxis=dict(tickmode='linear', tick0=min(x), dtick=1),
    )

    # Convert the Plotly figure to an HTML string (without full HTML)
    graph = fig.to_html(full_html=False)
    cache.set(cache_key, graph, timeout=randint(1_000, 9_999))  # noqa: S311
    logger.info(f'Graph cached for {cache_key}')

    return graph


def get_albums_by_year_chart():
    """Chart albums by year."""
    cache_key = 'albums_by_year'
    if graph := cache.get(cache_key):
        logger.info(f'Graph served from cache: {cache_key}')
        return graph
    logger.info(f'Graph rendering fresh: {cache_key}')

    # Query to aggregate song play count
    album_stats = (
        Album.objects.values('year')
        .annotate(album_count=Count('id'), total_rating=Sum('rating'))
        .order_by('-year')
    )

    x = [stat['year'] for stat in album_stats]
    y = [stat['total_rating'] for stat in album_stats]
    text = [f'{stat["album_count"]}' for stat in album_stats]

    # Create the bar chart using graph_objects
    fig = go.Figure(
        data=[go.Bar(x=x, y=y, text=text, hovertemplate='%{text}<br>Total Rating: %{y}')]
    )

    # Customize the layout if needed
    fig.update_layout(
        title='Album ratings summed per year',
        xaxis_title='Year',
        yaxis_title='Sum of album ratings',
        autosize=True,
        margin=dict(l=20, r=20, t=30, b=20),
        xaxis=dict(tickmode='linear', tick0=min(x), dtick=1),
    )

    # Convert the Plotly figure to an HTML string (without full HTML)
    graph = fig.to_html(full_html=False)
    cache.set(cache_key, graph, timeout=randint(1_000, 9_999))  # noqa: S311
    logger.info(f'Graph cached for {cache_key}')

    return graph


def get_albums_per_artist_chart():
    """Chart the number of artists with a specific album count."""
    cache_key = 'albums_per_artist'
    if graph := cache.get(cache_key):
        logger.info(f'Graph served from cache: {cache_key}')
        return graph
    logger.info(f'Graph rendering fresh: {cache_key}')

    # Query to count the number of artists for each album count
    stats = (
        Artist.objects.values('count_albums')  # Group by the count_albums field
        .annotate(artist_count=Count('id'))  # Count how many artists have each album count
        .order_by('count_albums')  # Order by album count (ascending)
    )

    # Extract data for the chart
    x = [stat['count_albums'] for stat in stats]  # Album counts
    y = [stat['artist_count'] for stat in stats]  # Number of artists with that album count

    # Create the bar chart using graph_objects
    fig = go.Figure(data=[go.Bar(x=x, y=y, text=y, hovertemplate='%{text} artists')])

    # Customize the layout
    fig.update_layout(
        title='Number of Artists per Number of Albums',
        xaxis_title='Number of Albums',
        yaxis_title='Number of Artists',
        autosize=True,
        margin=dict(l=20, r=20, t=30, b=20),
        xaxis=dict(tickmode='linear', dtick=1),
    )

    # Convert the Plotly figure to an HTML string (without full HTML)
    graph = fig.to_html(full_html=False)
    cache.set(cache_key, graph, timeout=randint(1_000, 9_999))  # noqa: S311
    logger.info(f'Graph cached for {cache_key}')

    return graph


def get_songs_by_played_date_chart():
    """Chart number of songs played per date."""
    cache_key = 'songs_by_date'
    if graph := cache.get(cache_key):
        logger.info(f'Graph served from cache: {cache_key}')
        return graph
    logger.info(f'Graph rendering fresh: {cache_key}')

    # Switch from daily to weekly buckets once data spans more than 12 months
    first_played = History.objects.aggregate(first=Min('played_at'))['first']
    span_days = (timezone.now() - first_played).days if first_played else 0
    use_weekly = span_days > DAILY_TO_WEEKLY_THRESHOLD_DAYS
    logger.info(
        f'songs_by_date: first_played={first_played}, span_days={span_days}, '
        f'mode={"weekly" if use_weekly else "daily"}'
    )

    trunc = TruncWeek('played_at') if use_weekly else TruncDate('played_at')
    date_stats = (
        History.objects.annotate(played_date=trunc)
        .values('played_date')
        .annotate(song_count=Count('id'))
        .order_by('played_date')
    )

    x = [stat['played_date'] for stat in date_stats]
    y = [stat['song_count'] for stat in date_stats]

    fig = go.Figure(data=[go.Bar(x=x, y=y)])

    fig.update_layout(
        title='Number of Songs Played per Week'
        if use_weekly
        else 'Number of Songs Played per Date',
        xaxis_title='Week' if use_weekly else 'Date',
        yaxis_title='Number of Songs',
        autosize=True,
        margin=dict(l=20, r=20, t=30, b=20),
    )

    # Step 5: Convert the Plotly figure to an HTML string (without full HTML)
    graph = fig.to_html(full_html=False)
    cache.set(cache_key, graph, timeout=randint(1_000, 9_999))  # noqa: S311
    logger.info(f'Graph cached for {cache_key}')

    return graph


def get_top_percentile_songs(artist: Artist, percentile: float) -> List[Song]:
    """Get top percentile songs for artist."""
    # Step 1: Get all song ratings, ordered by rating
    all_songs = artist.songs.order_by('-rating')

    # Step 2: Calculate the 90th percentile index
    count_songs = all_songs.count()
    if count_songs == 0:
        return all_songs  # Return empty if no songs

    percentile_index = int(percentile * count_songs)  # Get the nth percentile index

    # Step 3: Get the rating at the nth percentile
    percentile_song = all_songs[percentile_index]
    percentile_rating = percentile_song.rating

    # Step 4: Filter songs that are greater than or equal to the 90th percentile rating
    top_songs = artist.songs.filter(rating__gt=percentile_rating).order_by('-rating').all()
    logger.info(f'{percentile_rating:.2f} rating at ix {percentile_index}')
    logger.info(f'{len(top_songs)} from {len(all_songs)}')

    return top_songs


def get_recent_artists() -> QuerySet[History]:
    """Get recent artists: plays in the ratings window, but never fewer than the slot count.

    After a restart the window can be empty, so fall back to the latest plays to keep the
    queue and countdown fed with at least one window's worth of history.
    """
    from main.plays import NUM_SLOTS_IN_WINDOW, RATINGS_WINDOW  # noqa: PLC0415  circular import

    time_threshold = timezone.now() - timezone.timedelta(seconds=RATINGS_WINDOW)
    min_count = round(NUM_SLOTS_IN_WINDOW)

    # Query the History model for songs played in the time window
    # logged by get_next_song alongside the countdown, which has the same counts
    recent_histories = History.objects.filter(played_at__gte=time_threshold)
    if recent_histories.count() >= min_count:
        return recent_histories

    # fewer plays in the window than slots: the latest slot-count plays hold them all
    return History.objects.all()[:min_count]


def get_avg_last_albums() -> QuerySet[Album]:
    """Get last albums by avg played."""
    return Album.objects.order_by(F('avg_played_at').asc(nulls_last=True))[:10]


def list_lowest_rated_artists(multiple_albums: bool = True) -> QuerySet[Artist]:
    """Get artists by lowest rating, excluding those with plays in the past 30 days."""
    time_threshold = timezone.now() - timedelta(days=30)
    recent_artist_ids = (
        History.objects.filter(played_at__gte=time_threshold)
        .values_list('song__album__artist_id', flat=True)
        .distinct()
    )

    return (
        Artist.objects.filter(count_albums__gt=1 if multiple_albums else 0)
        .exclude(rating__isnull=True)
        .exclude(id__in=recent_artist_ids)
        .order_by('rating')[:10]
    )


def list_lowest_rated_albums() -> List[Album]:
    """Get albums by lowest rating, flagging those with a song not yet played or rated enough.

    Lists one slot count of albums: get_next_song bumps their songs that are short of a fair
    chance, so the list is no longer than one ratings window can work through.
    """
    from main.plays import NUM_SLOTS_IN_WINDOW  # noqa: PLC0415  circular import

    limit = round(NUM_SLOTS_IN_WINDOW)
    albums = list(
        Album.objects.annotate(
            min_song_plays=Min('songs__count_played'),
            min_song_ratings=Min('songs__count_rated'),
            # how far the songs together are short of a fair chance
            plays_left=Sum(
                Greatest(BAD_ALBUM_MIN_SONG_PLAYS - F('songs__count_played'), Value(0))
            ),
            ratings_left=Sum(
                Greatest(BAD_ALBUM_MIN_SONG_RATINGS - F('songs__count_rated'), Value(0))
            ),
        )
        .annotate(
            needs_more_chances=ExpressionWrapper(
                Q(min_song_plays__lt=BAD_ALBUM_MIN_SONG_PLAYS)
                | Q(min_song_ratings__lt=BAD_ALBUM_MIN_SONG_RATINGS),
                output_field=BooleanField(),
            )
        )
        .order_by('rating')[:limit]
    )
    count_struck = sum(album.needs_more_chances for album in albums)
    logger.info(
        f'📉 Listed lowest rated albums: albums_count={len(albums)}/{limit}, '
        f'struck={count_struck}, '
        f'min_song_plays={BAD_ALBUM_MIN_SONG_PLAYS}, min_song_ratings={BAD_ALBUM_MIN_SONG_RATINGS}'
    )
    return albums


def upkeep_song(song: Song):
    """Ensure stats are correct on song."""
    # first handle plays
    song.count_played = song.histories.count()
    song.played_at = song.histories.aggregate(Max('played_at'))['played_at__max']

    # lastly handle ratings
    ratings = Rating.objects.filter(Q(winner=song) | Q(loser=song))
    count_wins = Rating.objects.filter(winner=song).count()
    song.count_rated = ratings.count()
    song.rated_at = ratings.aggregate(Max('rated_at'))['rated_at__max']
    song.rating = count_wins / ratings.count()

    logger.info(f'Upkept {song}')
    song.save()


def upkeep_album(album: Album):
    """Ensure stats are correct on album."""
    # first handle plays
    album.count_played = album.songs.aggregate(Sum('count_played'))['count_played__sum']
    album.played_at = album.songs.aggregate(Max('played_at'))['played_at__max']
    # Convert 'played_at' to a Unix timestamp using SQLite's strftime
    avg_played_at = album.songs.aggregate(
        avg_played_at=Avg(RawSQL("strftime('%%s', played_at)", []))
    )['avg_played_at']
    album.avg_played_at = (
        make_aware(datetime.fromtimestamp(avg_played_at)) if avg_played_at else None
    )

    # lastly handle ratings
    album.count_rated = album.songs.aggregate(Sum('count_rated'))['count_rated__sum']
    album.rated_at = album.songs.aggregate(Max('rated_at'))['rated_at__max']
    album.rating = get_album_rating(album, get_mean_rating(Song))

    album.save()
    logger.info(f'🔧 Upkept {album}: rating={album.rating:.3f}')


def upkeep_artist(artist: Artist):
    """Ensure stats are correct on artist."""
    # first handle plays
    artist.count_played = artist.albums.aggregate(Sum('count_played'))['count_played__sum']
    artist.played_at = artist.albums.aggregate(Max('played_at'))['played_at__max']
    # Convert 'played_at' to a Unix timestamp using SQLite's strftime
    avg_played_at = artist.songs.aggregate(
        avg_played_at=Avg(RawSQL("strftime('%%s', played_at)", []))
    )['avg_played_at']
    artist.avg_played_at = (
        make_aware(datetime.fromtimestamp(avg_played_at)) if avg_played_at else None
    )

    # lastly handle ratings
    artist.count_rated = artist.albums.aggregate(Sum('count_rated'))['count_rated__sum']
    artist.rated_at = artist.albums.aggregate(Max('rated_at'))['rated_at__max']
    artist.rating = get_artist_rating(artist, get_mean_rating(Album))

    artist.save()
    logger.info(f'🔧 Upkept {artist}: rating={artist.rating:.3f}')
