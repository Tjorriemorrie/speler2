import logging
from datetime import timedelta

import pylast
from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.db.models import Count, F, Max, Sum, Window
from django.db.models.functions import RowNumber
from django.utils import timezone

from main.discography import MIN_ALBUM_TRACKS, get_stand_out_tracks, get_track_playcounts
from main.lastfm_service import (
    _owned_artists,
    artist_slug,
    get_album_tracks,
    get_artist_top_albums,
    get_similar_tracks,
    get_track_album,
    straighten_quotes,
    track_slug,
)
from main.models import Artist, Similar, Song

logger = logging.getLogger(__name__)

# as many as last.fm gives: it stops around 250, whatever the limit
SIMILARS_FETCH_LIMIT = 250
# each artist's best songs are the seeds
SIMILARS_SEED_SONGS = 3
# an artist's place in this order sets the weight of its seeds
SIMILARS_ARTIST_ORDERING = ('-rating', '-count_played', 'id')
# best artist first, each artist's best song first; id breaks ties, so a song keeps its place in
# the progress count between renders
SIMILARS_SEED_ORDERING = (
    '-artist__rating',
    '-artist__count_played',
    'artist_id',
    '-rating',
    '-count_played',
    'id',
)
# once every seed is fetched, at most one is redone per this interval
SIMILARS_REFETCH_INTERVAL = timedelta(hours=1)
# what makes a song a hit; applied when ranking, so changing it needs no refetch
HIT_MIN_PLAYS = 1_000_000
# library artists listed under the recommended album as the artists it is similar to
SIMILARS_ARTISTS_SHOWN = 5
# the hit and the album's stand-out tracks after it
SIMILARS_TRACKS_SHOWN = 3
SIMILARS_CACHE_TIMEOUT = 3600 * 16


def _get_seed_ids() -> list[int]:
    """Ids of the seed songs: every artist's best songs, best artist first."""
    return list(
        Song.objects.annotate(
            place=Window(
                RowNumber(), partition_by='artist_id', order_by=('-rating', '-count_played', 'id')
            )
        )
        .filter(place__lte=SIMILARS_SEED_SONGS)
        .order_by(*SIMILARS_SEED_ORDERING)
        .values_list('id', flat=True)
    )


def has_unfetched_seeds() -> bool:
    """Whether any seed song has not been fetched yet."""
    return Song.objects.filter(id__in=_get_seed_ids(), similars_at__isnull=True).exists()


def get_similars_progress() -> dict | None:
    """How many seeds are fetched out of how many, and the place of the latest fetched one."""
    seed_ids = _get_seed_ids()
    fetched_ids = list(
        Song.objects.filter(id__in=seed_ids, similars_at__isnull=False)
        .order_by('-similars_at')
        .values_list('id', flat=True)
    )
    if not fetched_ids:
        return None
    return {
        'done': len(fetched_ids),
        'total': len(seed_ids),
        'latest': seed_ids.index(fetched_ids[0]) + 1,
    }


def _get_artist_weight(artist_id: int) -> float:
    """The artist's inverse percentile rank: the best artist is 1, the worst nearly 0."""
    artist_ids = list(
        Artist.objects.order_by(*SIMILARS_ARTIST_ORDERING).values_list('id', flat=True)
    )
    return 1 - artist_ids.index(artist_id) / len(artist_ids)


def update_next_similar_song() -> bool:
    """Store the similar songs by new artists of the seed fetched longest ago.

    Returns whether a seed was marked done, so a batch can tell an outage from progress.
    """
    if not settings.LASTFM_ENABLE:
        logger.info('🎵 LastFM disabled, not updating similar songs')
        return False

    seed_ids = _get_seed_ids()
    # a song fallen out of the seeds no longer recommends; it is fetched anew if it comes back
    count_dropped, _ = Similar.objects.exclude(song_id__in=seed_ids).delete()
    Song.objects.exclude(id__in=seed_ids).filter(similars_at__isnull=False).update(
        similars_at=None
    )
    if count_dropped:
        logger.info(f'🎵 Dropped similar songs of former seeds: deleted={count_dropped}')

    seeds = Song.objects.filter(id__in=seed_ids)
    if not seeds.filter(similars_at__isnull=True).exists():
        refetched_at = seeds.aggregate(latest=Max('similars_at'))['latest']
        if refetched_at and timezone.now() - refetched_at < SIMILARS_REFETCH_INTERVAL:
            logger.info(f'🎵 Every seed fetched, last refetch too recent: at={refetched_at}')
            return False

    # never fetched comes first, best seed first; after that the oldest fetch is redone
    seed = (
        seeds.select_related('artist')
        .order_by(F('similars_at').asc(nulls_first=True), *SIMILARS_SEED_ORDERING)
        .first()
    )
    if not seed:
        logger.info('🎵 No songs in the library, nothing to update')
        return False

    seed_artist = straighten_quotes(seed.artist.name)
    seed_title = straighten_quotes(seed.name)
    logger.info(
        f'🎵 Fetching similar songs: song_id={seed.id}, artist={seed_artist}, title={seed_title}'
    )
    try:
        similar_tracks = get_similar_tracks(seed_artist, seed_title, SIMILARS_FETCH_LIMIT)
    except pylast.PyLastError as exc:
        # unknown song is final, so it must not block the songs after it; the rest is retried
        if not (
            isinstance(exc, pylast.WSError) and exc.status == str(pylast.STATUS_INVALID_PARAMS)
        ):
            logger.warning(
                f'⚠️ Fetching similar songs from LastFM failed, retrying next update: '
                f'song_id={seed.id}, artist={seed_artist}, title={seed_title}, error={exc}'
            )
            return False
        logger.warning(
            f'⚠️ Song not found on LastFM, marking it done: song_id={seed.id}, '
            f'artist={seed_artist}, title={seed_title}'
        )
        similar_tracks = []

    # only artists not in the library are recommended, owned ones get "more from artist"
    owned_artists = _owned_artists({artist_slug(track['artist']) for track in similar_tracks})
    weight = _get_artist_weight(seed.artist_id)
    seen = set()
    count_skipped = 0
    now = timezone.now()
    similars = []
    for track in similar_tracks:
        key = (artist_slug(track['artist']), track_slug(track['name']))
        # an empty artist slug cannot be put in the remove url, an empty track slug cannot match
        if not all(key) or key[0] in owned_artists or key in seen:
            count_skipped += 1
            continue
        seen.add(key)
        similars.append(
            Similar(
                song=seed,
                artist_name=track['artist'],
                artist_slug=key[0],
                track_name=track['name'],
                track_slug=key[1],
                match=track['match'],
                playcount=track['playcount'],
                score=weight * track['match'],
                scraped_at=now,
            )
        )

    # a refetch replaces the seed's previous songs rather than adding to them
    with transaction.atomic():
        count_replaced, _ = Similar.objects.filter(song=seed).delete()
        Similar.objects.bulk_create(similars)
        seed.similars_at = now
        seed.save(update_fields=['similars_at'])
    logger.info(
        f'🎵 Similar songs updated: song_id={seed.id}, artist={seed_artist}, title={seed_title}, '
        f'fetched={len(similar_tracks)}, skipped={count_skipped}, saved={len(similars)}, '
        f'replaced={count_replaced}'
    )
    return True


def _fetch_hit_album(best: dict) -> dict:
    """Get the hit's album with its stand-out tracks, the hit first; empty when there is none."""
    name = straighten_quotes(best['artist_name'])
    album = get_track_album(name, best['track_name'])
    track_names = get_album_tracks(name, album[0]) if album else []
    # last.fm often files a hit under its single, so the artist's top album stands in
    if len(track_names) < MIN_ALBUM_TRACKS:
        top_albums = get_artist_top_albums(name, 1)
        if not top_albums:
            return {}
        album = (top_albums[0][0], top_albums[0][2])
        track_names = get_album_tracks(name, album[0])
    hit = {'name': best['track_name'], 'playcount': best['playcount']}
    others = get_stand_out_tracks(
        name, album[0], track_names, get_track_playcounts(name), {best['track_slug']}
    )
    return {
        'name': album[0],
        'url': album[1],
        'tracks': [hit, *others][:SIMILARS_TRACKS_SHOWN],
    }


def _get_hit_album(best: dict) -> dict:
    """Get the hit's album, cached."""
    cache_key = f'similars_hit_album_{best["artist_slug"]}_{best["track_slug"]}'
    if (album := cache.get(cache_key)) is None:
        album = _fetch_hit_album(best)
        cache.set(cache_key, album, timeout=SIMILARS_CACHE_TIMEOUT)
    return album


def get_recommended_album() -> dict | None:
    """Get the album of the hit most similar across the library.

    It carries the hit, the album's stand-out tracks and the library artists the hit is most
    similar to.
    """
    ranked = (
        Similar.objects.filter(playcount__gte=HIT_MIN_PLAYS)
        .values('artist_slug', 'track_slug')
        .annotate(
            total_score=Sum('score'),
            count_seeds=Count('id'),
            artist_name=Max('artist_name'),
            track_name=Max('track_name'),
            playcount=Max('playcount'),
        )
        .order_by('-total_score')
    )
    for best in ranked:
        # the artist may have been added to the library since it was fetched
        if _owned_artists({best['artist_slug']}):
            deleted, _ = Similar.objects.filter(artist_slug=best['artist_slug']).delete()
            logger.info(
                f'🎵 Dropped recommendations of artist now in library: '
                f'artist={best["artist_name"]}, deleted={deleted}'
            )
            continue
        album = _get_hit_album(best)
        if album:
            break
        logger.info(
            f'🎵 Skipped hit without album: artist={best["artist_name"]}, '
            f'track={best["track_name"]}'
        )
    else:
        logger.info('🎵 No recommended album yet')
        return None

    best.update(album)
    best['artists'] = list(
        Artist.objects.filter(
            songs__similars__artist_slug=best['artist_slug'],
            songs__similars__track_slug=best['track_slug'],
        )
        # reuses the filter's join; an artist can recommend the hit through several seeds
        .annotate(match=Max('songs__similars__match'))
        .order_by('-match')[:SIMILARS_ARTISTS_SHOWN]
    )
    logger.info(
        f'🎵 Recommended album: artist={best["artist_name"]}, track={best["track_name"]}, '
        f'album={best["name"]}, playcount={best["playcount"]}, '
        f'total_score={best["total_score"]:.3f}, count_seeds={best["count_seeds"]}'
    )
    return best
