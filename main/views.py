import logging
from pathlib import Path

import requests
from django.conf import settings
from django.core.cache import cache
from django.core.handlers.wsgi import WSGIRequest
from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.utils.cache import patch_cache_control
from django_filters.views import FilterMixin
from django_tables2 import SingleTableView

from main.constants import GENRE_CHOICES
from main.filters import SongFilter
from main.lastfm_service import scrape_studio_albums, update_next_similar_artist
from main.lyrics import search_azlyrics
from main.models import Album, Artist, Song
from main.musicfiles import get_album_art, validate_songs
from main.plays import get_next_song, handle_genre_filter, set_genre, set_played
from main.ratings import get_match, set_match_result
from main.selectors import (
    get_albums_by_year_chart,
    get_albums_per_artist_chart,
    get_play_count_chart,
    get_songs_by_played_date_chart,
    get_top_percentile_songs,
)
from main.tables import SongTable

logger = logging.getLogger(__name__)


def home_view(request: WSGIRequest):
    """Home view."""
    ctx = {}
    return render(request, 'main/home.html', ctx)


def next_song_view(request: WSGIRequest):  # noqa: PLR0912
    """Return next song."""
    last_song_id = request.session.get('song_id')
    if last_song_id:
        try:
            song = Song.objects.get(id=last_song_id)
            set_played(song)
        except Song.DoesNotExist:
            logger.warning(f'Looked to play {last_song_id} but not found!')
            pass

    next_song = None

    # demands facet filters
    if request.GET.get('remove_facet'):
        cache.delete('filter_facet')
    if demand := request.GET.get('demand'):
        logger.info(f'Demand received: {demand}')
        dem_type, dem_id = demand.split('_')
        if dem_type == 'song':
            next_song = Song.objects.get(id=dem_id)
        else:
            facet_class = globals().get(dem_type.title())
            facet_ins = get_object_or_404(facet_class, id=dem_id)
            cache.set('filter_facet', {dem_type: facet_ins}, timeout=None)

    # filters of genres
    if request.GET.get('remove_genre'):
        cache.delete('filter_genres')
    if genre := request.GET.get('genre'):
        valid_genres = [genre[0] for genre in GENRE_CHOICES]
        if genre and genre not in valid_genres:
            return HttpResponse(f'Invalid genre selected: {genre}', status=400)
        handle_genre_filter(genre)

    # normal priority queue
    if not next_song:
        next_song = get_next_song()

    # check audio exists
    if not next_song.file_exists():
        validate_songs()
        next_song = get_next_song()

    # store for matches and history
    request.session['song_id'] = next_song.id

    # Check if filter_facet is not None and has at least one item
    if filter_facet := cache.get('filter_facet'):
        filter_value = next(iter(filter_facet.values()))  # Get the first value
    else:
        filter_value = None
    # Check if filter_genre is not None and has at least one item
    if filter_genres := cache.get('filter_genres'):
        genre_values = ', '.join(filter_genres['genre__in'])
    else:
        genre_values = None

    ctx = {
        'song': next_song,
        'filter_value': filter_value,
        'genre_values': genre_values,
    }
    response = render(request, 'main/partial_song_player.html', ctx)

    # Set the HX-Trigger header to load matches
    response['HX-Trigger'] = 'loadNextRating'
    return response


def next_rating_view(request: WSGIRequest):
    """Return next rating."""
    if winner_id := request.GET.get('winner_id'):
        match_ids = request.session.get('match_ids')
        set_match_result(int(winner_id), list(map(int, match_ids)))

    current_song = Song.objects.get(id=request.session.get('song_id'))
    match = get_match(current_song)
    request.session['match_ids'] = [s.id for s in match] if match else None

    response = render(request, 'main/partial_song_rating.html', {'match': match})

    if not match:
        # Set the HX-Trigger header to reload album view with ratings on it
        response['HX-Trigger'] = 'refreshAlbum'

    return response


def album_art_view(request, song_id):
    """Return album art from static directory if exists, otherwise extract from ID3."""
    song = get_object_or_404(Song, id=song_id)
    album = song.album

    # Define path to album art in the static directory
    album_art_path = settings.ALBUMS_DIR / f'{album.artist.slug}-{album.slug}-{album.id}.jpg'

    # Check if album art already exists in the static directory
    if album_art_path.exists():
        with Path.open(album_art_path, 'rb') as art_file:
            response = HttpResponse(art_file.read(), content_type='image/jpeg')
            # Add cache headers to the response (e.g., cache for 1 day)
            patch_cache_control(response, public=True, max_age=86400)  # 86400 seconds = 1 day
            return response

    # If album art does not exist, extract from ID3 and save it
    tag = get_album_art(song)
    if not tag:
        raise Http404('Album art not found in ID3 tags')

    # Save the album art to the static directory
    with Path.open(album_art_path, 'wb') as art_file:
        art_file.write(tag.data)

    # Serve the album art with cache headers
    response = HttpResponse(tag.data, content_type='image/jpeg')
    patch_cache_control(response, public=True, max_age=86400)
    return response


def album_view(request, album_id):
    """Album view of song."""
    current_song_id = request.session.get('song_id')
    if album_id == 0:
        album = Album.objects.get(songs__id=current_song_id)
    else:
        album = get_object_or_404(Album, id=album_id)
    songs = album.songs.order_by('disc_number', 'track_number').all()
    albums_before = (
        album.artist.albums.filter(
            year__lte=album.year,
        )
        .exclude(id=album.id)
        .order_by('year')
        .all()
    )
    albums_after = album.artist.albums.filter(year__gt=album.year).order_by('year').all()
    return render(
        request,
        'main/partial_album.html',
        {
            'album': album,
            'songs': songs,
            'current_song_id': current_song_id,
            'albums_before': albums_before,
            'albums_after': albums_after,
        },
    )


def artist_view(request: WSGIRequest, artist_id: int) -> HttpResponse:
    """Get artist details."""
    artist = get_object_or_404(Artist, id=artist_id)
    albums = artist.albums.order_by('year').all()
    percentile = 0.10
    songs = get_top_percentile_songs(artist, percentile)
    ctx = {
        'artist': artist,
        'albums': albums,
        'songs': songs,
        'percentile': int(percentile * 100),
    }
    return render(request, 'main/partial_artist.html', ctx)


def ranking_view(request, facet):
    """Return ranking for whichever facet."""
    current_song = get_object_or_404(Song, id=request.session.get('song_id'))
    if facet == 'artists':
        cls = Artist
        prefetch = 'albums'
    elif facet == 'albums':
        cls = Album
        prefetch = 'artist'
    elif facet == 'songs':
        cls = Song
        prefetch = None
    logger.info(f'Fetching ranking for {facet} on class {cls} and prefetching {prefetch}')
    query = cls.objects
    if prefetch:
        query = query.prefetch_related(prefetch)
    objs = query.order_by('-rating', '-count_played', '-count_rated').all()

    # Add pagination logic
    paginator = Paginator(objs, 50)
    page = request.GET.get('page')

    try:
        paginated_objs = paginator.page(page)
    except PageNotAnInteger:
        paginated_objs = paginator.page(1)  # If page is not an integer, deliver first page.
    except EmptyPage:
        paginated_objs = paginator.page(
            paginator.num_pages
        )  # If page is out of range, deliver last page.

    max_rating = max([a.rating for a in objs])
    min_rating = min([a.rating for a in objs])
    return render(
        request,
        f'main/partial_ranking_{facet}.html',
        {
            'facet': facet,
            'objs': paginated_objs,
            'current': current_song,
            'max_rating': max_rating,
            'min_rating': min_rating,
        },
    )


class SongListView(SingleTableView, FilterMixin):
    model = Song
    # queryset = Song.objects.all()
    ordering = ['-count_played', '-rating']
    filterset_class = SongFilter
    table_class = SongTable
    template_name = 'main/partial_listing.html'
    paginate_by = 50

    def get_queryset(self):
        """Get query."""
        queryset = super().get_queryset()
        self.filterset = self.filterset_class(self.request.GET, queryset=queryset)
        return self.filterset.qs

    def get_context_data(self, **kwargs):
        """Get context."""
        context = super().get_context_data(**kwargs)
        context['filtering'] = self.filterset
        return context


def stats_view(request):
    """Show stats, e.g. ratings by year."""
    return render(request, 'main/partial_stats.html', {})


def stats_graph_view(request, graph_name: str):
    """Get chart for stats view."""
    if graph_name == 'album_ratings_by_year':
        graph = get_albums_by_year_chart()
    elif graph_name == 'play_count':
        graph = get_play_count_chart()
    elif graph_name == 'albums_per_artist':
        graph = get_albums_per_artist_chart()
    elif graph_name == 'songs_by_date':
        graph = get_songs_by_played_date_chart()
    else:
        return HttpResponse(f'Unknown graph: {graph_name}')

    response = render(request, 'main/partial_stats_graph.html', {'graph': graph})
    patch_cache_control(response, public=True, max_age=3600)
    return response


def lyrics_view(request, song_id: int):
    """Show lyric."""
    cache = True
    song = get_object_or_404(Song, id=song_id)
    refresh = bool(request.GET.get('refresh'))
    instrument = bool(request.GET.get('instrument'))

    try:
        lyrics = search_azlyrics(song, refresh, instrument)
    except (requests.RequestException, ValueError) as exc:
        lyrics = str(exc)
        cache = False

    ctx = {
        'lyrics': lyrics,
        'current_song_id': request.session.get('song_id'),
    }
    response = render(request, 'main/partial_lyrics.html', ctx)
    if cache:
        patch_cache_control(response, public=True, max_age=86400)
    else:
        logger.info('Not using cache for lyrics')
    return response


def genre_view(request, facet: str, facet_id: int, genre: str):
    """Set genre of artist, album or song."""
    # Check if facet class exists, otherwise return a string message
    facet_class = globals().get(facet.title())
    if not facet_class:
        return render(request, 'main/snippet_genre.html', {'message': f'Invalid facet: {facet}'})

    # Get the facet instance or return a string message if not found
    try:
        facet_ins = facet_class.objects.get(id=facet_id)
    except facet_class.DoesNotExist:
        return render(
            request,
            'main/snippet_genre.html',
            {'message': f'{facet.title()} with ID {facet_id} not found.'},
        )

    # Validate the genre choice
    genre = genre.casefold()
    if genre not in [g[0] for g in GENRE_CHOICES]:
        return render(
            request, 'main/snippet_genre.html', {'message': f'Invalid genre choice: {genre}'}
        )

    # Set the genre and render success
    set_genre(facet_ins, genre)
    response = render(
        request,
        'main/snippet_genre.html',
        {
            'obj': facet_ins,
            'success': True,
        },
    )

    if refresh := request.GET.get('refresh'):
        # Set the HX-Trigger header to load matches
        response['HX-Trigger'] = f'refresh{refresh.title()}'

    return response


def similars_view(request):
    """Get artist to review and new bands from LastFM."""
    album_details = scrape_studio_albums()

    try:
        grouped_similars = update_next_similar_artist()
    except NotImplementedError as exc:
        return HttpResponse(str(exc))

    ctx = {
        'album_details': album_details,
        'grouped_similars': grouped_similars,
    }
    response = render(request, 'main/partial_similars.html', ctx)
    # patch_cache_control(response, public=True, max_age=86400)
    return response
