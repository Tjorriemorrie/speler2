import logging

from django.core.handlers.wsgi import WSGIRequest
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render

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
    return render(request, 'main/partial_song_player.html', {'song': next_song})


def next_rating_view(request: WSGIRequest):
    """Return next rating."""
    if winner_id := request.GET.get('winner_id'):
        match_ids = request.session.get('match_ids')
        set_match_result(int(winner_id), list(map(int, match_ids)))

    match = get_match()
    request.session['match_ids'] = [s.id for s in match] if match else None
    return render(request, 'main/partial_song_rating.html', {'match': match})


def album_art_view(request, song_id):
    """Return album art from ID3."""
    song = get_object_or_404(Song, id=song_id)
    tag = get_album_art(song)
    return HttpResponse(tag.data, content_type=tag.mime)


def ranking_view(request):
    """Return ranking for whichever facet."""
    artists = Artist.objects.order_by('-rating')
    albums = Album.objects.prefetch_related('artist').order_by('-rating')
    songs = Song.objects.order_by('-rating')
    ctx = {
        'artists': artists,
        'albums': albums,
        'songs': songs,
    }
    return render(request, 'main/partial_ranking.html', ctx)
