import logging
from random import randint
from typing import List

import plotly.graph_objects as go
from django.core.cache import cache
from django.db.models import Count, Sum
from django.db.models.functions import TruncDate
from django.utils import timezone

from main.constants import RATINGS_WINDOW
from main.models import Album, Artist, History, Song

logger = logging.getLogger(__name__)


def get_play_count_chart():
    """Chart play count bar."""
    cache_key = 'play_count'
    if graph := cache.get(cache_key):
        return graph

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
        return graph

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
        return graph

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
        return graph

    # Step 1: Query to group songs by date
    date_stats = (
        History.objects.annotate(played_date=TruncDate('played_at'))
        .values('played_date')
        .annotate(song_count=Count('id'))
        .order_by('played_date')
    )

    # Step 2: Extract the dates and counts for the x and y axes
    x = [stat['played_date'] for stat in date_stats]
    y = [stat['song_count'] for stat in date_stats]

    # Step 3: Create the bar chart using graph_objects
    fig = go.Figure(data=[go.Bar(x=x, y=y)])

    # Step 4: Customize the layout
    fig.update_layout(
        title='Number of Songs Played per Date',
        xaxis_title='Date',
        yaxis_title='Number of Songs',
        autosize=True,
        margin=dict(l=20, r=20, t=30, b=20),
        xaxis=dict(tickmode='linear', dtick=86400000, tickformat='%d %b'),
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


def get_recent_artist_ids():
    """Get recent artist IDS."""
    # Calculate the time window (40 minutes ago)
    time_threshold = timezone.now() - timezone.timedelta(seconds=RATINGS_WINDOW)

    # Query the History model for songs played in the time window
    recent_histories = History.objects.filter(played_at__gte=time_threshold)

    # Retrieve a flat list of distinct artist IDs
    artist_ids = recent_histories.values_list('song__artist__id', flat=True).distinct()

    return list(artist_ids)
