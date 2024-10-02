import plotly.graph_objects as go
from django.db.models import Count, Sum

from main.models import Album, Song


def get_play_count_chart():
    """Chart play count bar."""
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

    return graph


def get_albums_by_year_chart():
    """Chart albums by year."""
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

    return graph
