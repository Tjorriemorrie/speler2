import datetime
import logging
from statistics import mean

from django.db.models import F
from django.utils import timezone

from main.lastfm_service import (
    _owned_tracks,
    get_album_tracks,
    get_artist_top_albums,
    get_artist_top_tracks,
    straighten_quotes,
    track_slug,
)
from main.models import Artist

logger = logging.getLogger(__name__)

ARTIST_TOP_ALBUMS_LIMIT = 10
# top tracks only give the play counts; an album track missing from them counts as 0
ARTIST_TOP_TRACKS_LIMIT = 200
ARTIST_ALBUMS_SHOWN = 3
ARTIST_ALBUM_TRACKS_SHOWN = 6


def _next_review_artist() -> Artist:
    """The artist reviewed longest ago, never reviewed first."""
    return Artist.objects.order_by(F('disco_at').asc(nulls_first=True), 'count_albums').first()


def get_review_artist(refresh: bool) -> Artist:
    """Get the artist to review, after marking the current one reviewed on refresh."""
    artist = _next_review_artist()
    if refresh:
        artist.disco_at = timezone.now() + datetime.timedelta(days=30 * artist.count_albums)
        artist.save(update_fields=['disco_at'])
        logger.info(f'🎵 Marked artist reviewed: artist={artist.name}, until={artist.disco_at}')
        artist = _next_review_artist()
    return artist


def get_track_playcounts(artist_name: str) -> dict[str, int]:
    """Get the play counts of the artist's top tracks by track slug."""
    return {
        track_slug(title): playcount
        for title, playcount in get_artist_top_tracks(artist_name, ARTIST_TOP_TRACKS_LIMIT)
    }


def get_stand_out_tracks(
    artist_name: str, album_title: str, playcounts: dict[str, int], owned: set[str]
) -> list[dict]:
    """Get the album's tracks played more than its mean, best first, without the owned slugs."""
    tracks = {}
    for track_name in get_album_tracks(artist_name, album_title):
        tracks.setdefault(track_slug(track_name), track_name)
    # last.fm counts are skewed to the hits, so the mean leaves the few stand-out tracks
    cutoff = mean(playcounts.get(slug, 0) for slug in tracks) if tracks else 0
    kept = sorted(
        (
            {'name': track_name, 'playcount': playcounts.get(slug, 0)}
            for slug, track_name in tracks.items()
            if playcounts.get(slug, 0) > cutoff and slug not in owned
        ),
        key=lambda track: track['playcount'],
        reverse=True,
    )[:ARTIST_ALBUM_TRACKS_SHOWN]
    logger.info(
        f'🎵 Picked album tracks: artist={artist_name}, album={album_title}, '
        f'tracks={len(tracks)}, kept={len(kept)}'
    )
    return kept


def get_unowned_top_albums(artist: Artist) -> list[dict]:
    """Get the artist's top albums not owned, each with its stand-out tracks not owned."""
    name = straighten_quotes(artist.name)
    playcounts = get_track_playcounts(name)
    owned_albums = {track_slug(album) for album in artist.albums.values_list('name', flat=True)}
    owned_tracks = {slug for _, slug in _owned_tracks({artist.slug})}

    albums = []
    for title, album_playcount, url in get_artist_top_albums(name, ARTIST_TOP_ALBUMS_LIMIT):
        if track_slug(title) in owned_albums:
            logger.info(f'🎵 Skipped owned album: artist={artist.name}, album={title}')
            continue
        kept = get_stand_out_tracks(name, title, playcounts, owned_tracks)
        if not kept:
            continue
        albums.append({'name': title, 'playcount': album_playcount, 'url': url, 'tracks': kept})
        if len(albums) == ARTIST_ALBUMS_SHOWN:
            break
    return albums
