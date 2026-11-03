import logging
import math

import pylast
from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.db.models import Count, F, Max, Sum
from django.utils import timezone

from main.discography import get_stand_out_tracks, get_track_playcounts
from main.lastfm_service import (
    _owned_artists,
    artist_slug,
    get_artist_top_albums,
    get_similar_artists,
    straighten_quotes,
)
from main.models import Artist, Similar

logger = logging.getLogger(__name__)

# as many as last.fm gives in one page
SIMILARS_FETCH_LIMIT = 50
# order in which artists are fetched as seeds
# id breaks ties, so an artist keeps its place in the progress count between renders
SIMILARS_SEED_ORDERING = ('-rating', '-count_played', 'id')
# only the top decile of artists are seeds; once all are fetched they are refetched oldest first
SIMILARS_SEED_SHARE = 0.1
# library artists listed under the recommended album as the artists it is similar to
SIMILARS_ARTISTS_SHOWN = 5
SIMILARS_CACHE_TIMEOUT = 3600 * 16


def _get_seed_ids() -> list[int]:
    """Ids of the seed artists: the top decile of the library, best first."""
    limit = math.ceil(Artist.objects.count() * SIMILARS_SEED_SHARE)
    return list(
        Artist.objects.order_by(*SIMILARS_SEED_ORDERING).values_list('id', flat=True)[:limit]
    )


def get_similars_progress() -> dict | None:
    """How many seeds are fetched out of how many, and the place of the latest fetched one."""
    seed_ids = _get_seed_ids()
    fetched_ids = list(
        Artist.objects.filter(id__in=seed_ids, similars_at__isnull=False)
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


def update_next_similar_artist():
    """Store the similar artists not owned yet of the seed artist fetched longest ago."""
    if not settings.LASTFM_ENABLE:
        logger.info('🎵 LastFM disabled, not updating similar artists')
        return

    seed_ids = _get_seed_ids()
    # an artist fallen out of the seeds no longer recommends; it is fetched anew if it comes back
    count_dropped, _ = Similar.objects.exclude(artist_id__in=seed_ids).delete()
    Artist.objects.exclude(id__in=seed_ids).filter(similars_at__isnull=False).update(
        similars_at=None
    )
    if count_dropped:
        logger.info(f'🎵 Dropped similar artists of former seeds: deleted={count_dropped}')

    # never fetched comes first, best seed first; after that the oldest fetch is redone
    seed = (
        Artist.objects.filter(id__in=seed_ids)
        .order_by(F('similars_at').asc(nulls_first=True), *SIMILARS_SEED_ORDERING)
        .first()
    )
    if not seed:
        logger.info('🎵 No artists in the library, nothing to update')
        return

    seed_name = straighten_quotes(seed.name)
    logger.info(f'🎵 Fetching similar artists: artist_id={seed.id}, artist={seed_name}')
    try:
        similar_artists = get_similar_artists(seed_name, SIMILARS_FETCH_LIMIT)
    except pylast.PyLastError as exc:
        # unknown artist is final, so it must not block the artists after it; the rest is retried
        if not (
            isinstance(exc, pylast.WSError) and exc.status == str(pylast.STATUS_INVALID_PARAMS)
        ):
            logger.warning(
                f'⚠️ Fetching similar artists from LastFM failed, retrying next update: '
                f'artist_id={seed.id}, artist={seed_name}, error={exc}'
            )
            return
        logger.warning(
            f'⚠️ Artist not found on LastFM, marking it done: artist_id={seed.id}, '
            f'artist={seed_name}'
        )
        similar_artists = []

    # only artists not in the library are recommended, owned ones get "more from artist"
    owned_artists = _owned_artists({artist_slug(name) for name, _ in similar_artists})
    seen = set()
    count_skipped = 0
    now = timezone.now()
    similars = []
    for name, match in similar_artists:
        slug = artist_slug(name)
        # an empty slug cannot be put in the remove url
        if not slug or slug in owned_artists or slug in seen:
            count_skipped += 1
            continue
        seen.add(slug)
        similars.append(
            Similar(
                artist=seed,
                artist_name=name,
                artist_slug=slug,
                match=match,
                rating=seed.rating,
                score=seed.rating * match,
                scraped_at=now,
            )
        )

    # a refetch replaces the seed's previous artists rather than adding to them
    with transaction.atomic():
        count_replaced, _ = Similar.objects.filter(artist=seed).delete()
        Similar.objects.bulk_create(similars)
        seed.similars_at = now
        seed.save(update_fields=['similars_at'])
    logger.info(
        f'🎵 Similar artists updated: artist_id={seed.id}, artist={seed_name}, '
        f'fetched={len(similar_artists)}, skipped={count_skipped}, saved={len(similars)}, '
        f'replaced={count_replaced}'
    )


def _get_top_album(artist_name: str, slug: str) -> tuple[str, int, str] | None:
    """Get the artist's most played album from last.fm, cached."""
    cache_key = f'similars_top_album_{slug}'
    if (top_albums := cache.get(cache_key)) is None:
        top_albums = get_artist_top_albums(straighten_quotes(artist_name), 1)
        cache.set(cache_key, top_albums, timeout=SIMILARS_CACHE_TIMEOUT)
    return top_albums[0] if top_albums else None


def get_recommended_album() -> dict | None:
    """Get the top album of the artist most similar across the library.

    It carries its stand-out tracks and the library artists it is most similar to.
    """
    ranked = (
        Similar.objects.values('artist_slug')
        .annotate(
            total_score=Sum('score'),
            count_artists=Count('id'),
            artist_name=Max('artist_name'),
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
        top_album = _get_top_album(best['artist_name'], best['artist_slug'])
        if top_album:
            break
        logger.info(f'🎵 Skipped artist without albums: artist={best["artist_name"]}')
    else:
        logger.info('🎵 No recommended album yet')
        return None

    best['name'], _, best['url'] = top_album
    cache_key = f'similars_album_tracks_{best["artist_slug"]}'
    if (tracks := cache.get(cache_key)) is None:
        name = straighten_quotes(best['artist_name'])
        tracks = get_stand_out_tracks(name, best['name'], get_track_playcounts(name), set())
        cache.set(cache_key, tracks, timeout=SIMILARS_CACHE_TIMEOUT)
    best['tracks'] = tracks
    best['artists'] = list(
        Artist.objects.filter(similars__artist_slug=best['artist_slug'])
        # reuses the filter's join, so each artist gets the match of its own row
        .annotate(match=F('similars__match'))
        .order_by('-match')[:SIMILARS_ARTISTS_SHOWN]
    )
    logger.info(
        f'🎵 Recommended album: artist={best["artist_name"]}, album={best["name"]}, '
        f'total_score={best["total_score"]:.3f}, count_artists={best["count_artists"]}'
    )
    return best
