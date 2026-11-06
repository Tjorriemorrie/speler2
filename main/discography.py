import logging
import math

from django.db.models import F
from django.utils import timezone

from main.lastfm_service import (
    _owned_tracks,
    get_album_tracks,
    get_artist_top_tracks,
    get_track_album,
    straighten_quotes,
    track_slug,
)
from main.models import Artist

logger = logging.getLogger(__name__)

# top tracks only give the play counts; an album track missing from them counts as 0
ARTIST_TOP_TRACKS_LIMIT = 200
# the best quarter of an album's tracks are its stand-outs (3 of a usual 12)
STAND_OUT_TRACKS_SHARE = 0.25
# the best missing songs whose album is looked up, and listed when all are on owned albums
MISSING_SONGS_CHECKED = 3
# fewer tracks is a single or an EP, not an album worth suggesting
MIN_ALBUM_TRACKS = 4


def _next_review_artist() -> Artist:
    """The artist reviewed longest ago, never reviewed first."""
    return Artist.objects.order_by(F('disco_at').asc(nulls_first=True), 'count_albums').first()


def get_review_artist(reviewed_id: str | None) -> Artist:
    """Get the artist to review, after sending the reviewed one to the back of the queue."""
    if reviewed_id:
        Artist.objects.filter(id=reviewed_id).update(disco_at=timezone.now())
        logger.info(f'🎵 Marked artist reviewed: artist_id={reviewed_id}')
    return _next_review_artist()


def get_track_playcounts(artist_name: str) -> dict[str, int]:
    """Get the play counts of the artist's top tracks by track slug."""
    return {
        track_slug(title): playcount
        for title, playcount in get_artist_top_tracks(artist_name, ARTIST_TOP_TRACKS_LIMIT)
    }


def get_stand_out_tracks(
    artist_name: str,
    album_title: str,
    track_names: list[str],
    playcounts: dict[str, int],
    owned: set[str],
) -> list[dict]:
    """Get the best quarter of the album's tracks, best first, without the owned slugs."""
    tracks = {}
    for track_name in track_names:
        tracks.setdefault(track_slug(track_name), track_name)
    shown = math.ceil(len(tracks) * STAND_OUT_TRACKS_SHARE)
    kept = sorted(
        (
            {'name': track_name, 'playcount': playcounts.get(slug, 0)}
            for slug, track_name in tracks.items()
            if slug not in owned
        ),
        key=lambda track: track['playcount'],
        reverse=True,
    )[:shown]
    logger.info(
        f'🎵 Picked album tracks: artist={artist_name}, album={album_title}, '
        f'tracks={len(tracks)}, kept={len(kept)}'
    )
    return kept


def get_missing_songs(artist: Artist) -> dict:
    """Suggest the album of the first best missing song not owned, else those missing songs.

    The album comes with that song and the next best of its stand-out tracks not owned, up to
    MISSING_SONGS_CHECKED in all. When every checked song is on an owned album, those songs are
    listed with their albums instead. A song on no album or on one under MIN_ALBUM_TRACKS is
    checked but not listed.
    """
    name = straighten_quotes(artist.name)
    top_tracks = get_artist_top_tracks(name, ARTIST_TOP_TRACKS_LIMIT)
    playcounts = {track_slug(title): playcount for title, playcount in top_tracks}
    owned_albums = {track_slug(album) for album in artist.albums.values_list('name', flat=True)}
    owned_tracks = {slug for _, slug in _owned_tracks({artist.slug})}

    songs = []
    checked = set()
    for title, playcount in top_tracks:
        slug = track_slug(title)
        if slug in owned_tracks or slug in checked:
            continue
        checked.add(slug)
        song = {'name': title, 'playcount': playcount}
        if (album := get_track_album(name, title)) is None:
            logger.info(f'🎵 Skipped song without album: artist={artist.name}, song={title}')
        elif track_slug(album[0]) in owned_albums:
            songs.append({**song, 'album': album[0]})
        elif len(track_names := get_album_tracks(name, album[0])) < MIN_ALBUM_TRACKS:
            logger.info(
                f'🎵 Skipped short album: artist={artist.name}, album={album[0]}, '
                f'tracks={len(track_names)}'
            )
        else:
            album_title, url = album
            others = get_stand_out_tracks(
                name, album_title, track_names, playcounts, owned_tracks | {slug}
            )
            tracks = [song, *others][:MISSING_SONGS_CHECKED]
            logger.info(f'🎵 Suggested new album: artist={artist.name}, album={album_title}')
            return {'album': {'name': album_title, 'url': url, 'tracks': tracks}, 'songs': []}
        if len(checked) == MISSING_SONGS_CHECKED:
            break
    logger.info(f'🎵 Suggested songs on owned albums: artist={artist.name}, songs={len(songs)}')
    return {'album': None, 'songs': songs}
