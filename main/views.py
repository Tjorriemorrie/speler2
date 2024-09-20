import logging
from pathlib import Path

from django.conf import settings
from django.core.handlers.wsgi import WSGIRequest
from django.db.models import Avg, Count
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.utils.cache import patch_cache_control

from main.models import Album, Artist, Song
from main.musicfiles import get_album_art
from main.plays import get_next_song, set_played
from main.ratings import get_match, set_match_result

logger = logging.getLogger(__name__)


def home_view(request: WSGIRequest):
    """Home view."""
    ctx = {}
    return render(request, 'main/home.html', ctx)


def next_song_view(request: WSGIRequest):
    """Return next song."""
    last_song_id = request.session.get('song_id')
    if last_song_id:
        try:
            song = Song.objects.get(id=last_song_id)
            set_played(song)
        except Song.DoesNotExist:
            logger.warning(f'Looked to play {last_song_id} but not found!')
            pass

    next_song = get_next_song()
    request.session['song_id'] = next_song.id

    response = render(request, 'main/partial_song_player.html', {'song': next_song})
    # Set the HX-Trigger header
    response['HX-Trigger'] = 'loadNextRating'
    return response


def next_rating_view(request: WSGIRequest):
    """Return next rating."""
    logger.info('next rating view request')
    if winner_id := request.GET.get('winner_id'):
        match_ids = request.session.get('match_ids')
        set_match_result(int(winner_id), list(map(int, match_ids)))

    current_song = Song.objects.get(id=request.session.get('song_id'))
    match = get_match(current_song)
    request.session['match_ids'] = [s.id for s in match] if match else None
    return render(request, 'main/partial_song_rating.html', {'match': match})


def album_art_view(request, song_id):
    """Return album art from static directory if exists, otherwise extract from ID3."""
    song = get_object_or_404(Song, id=song_id)
    album = song.album
    logger.info(f'Getting album art for {album}')

    # Define path to album art in the static directory
    album_art_path = settings.ALBUM_ART_DIR / f'{album.id}-{album.slug}.jpg'
    logger.info(f'Album art path: {album_art_path}')

    # Check if album art already exists in the static directory
    if album_art_path.exists():
        with Path.open(album_art_path, 'rb') as art_file:
            logger.info(f'album art already found, returning {album_art_path}')
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
        logger.info(f'Album art written to {album_art_path}')

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


def ranking_view(request, facet):
    """Return ranking for whichever facet."""
    current_song = get_object_or_404(Song, id=request.session.get('song_id'))
    if facet == 'artists':
        artists = Artist.objects.prefetch_related('albums').order_by('-rating')
        max_rating = max([a.rating for a in artists])
        min_rating = min([a.rating for a in artists])
        return render(
            request,
            'main/partial_ranking_artists.html',
            {
                'artists': artists,
                'current': current_song,
                'max_rating': max_rating,
                'min_rating': min_rating,
            },
        )
    elif facet == 'albums':
        albums = Album.objects.prefetch_related('artist').order_by('-rating')
        max_rating = max([a.rating for a in albums])
        min_rating = min([a.rating for a in albums])
        return render(
            request,
            'main/partial_ranking_albums.html',
            {
                'albums': albums,
                'current': current_song,
                'max_rating': max_rating,
                'min_rating': min_rating,
            },
        )
    elif facet == 'songs':
        songs = Song.objects.order_by('-count_played', '-count_rated', 'rating')
        max_rating = max([a.rating for a in songs])
        min_rating = min([a.rating for a in songs])
        return render(
            request,
            'main/partial_ranking_songs.html',
            {
                'songs': songs,
                'current': current_song,
                'max_rating': max_rating,
                'min_rating': min_rating,
            },
        )


def year_view(request):
    """Show ratings by year."""
    # Annotate the average rating and count of albums per year
    avg_ratings_per_year = (
        Album.objects.values('year')
        .annotate(avg_rating=Avg('rating'), album_count=Count('id'))
        .order_by('-year')
    )
    max_rating = max([i['avg_rating'] for i in avg_ratings_per_year])
    min_rating = min([i['avg_rating'] for i in avg_ratings_per_year])
    max_albums = max([i['album_count'] for i in avg_ratings_per_year])

    return render(
        request,
        'main/partial_year.html',
        {
            'avg_ratings_per_year': avg_ratings_per_year,
            'max_albums': max_albums,
            'max_rating': max_rating,
            'min_rating': min_rating,
        },
    )
