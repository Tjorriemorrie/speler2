"""Artist photos shown behind the player, downloaded from fanart.tv.

Each artist's photos sit in `ARTISTS_DIR/<slug>/`; files put there by hand are shown too.
"""

import logging
from pathlib import Path

import httpx2
from django.conf import settings
from django.utils import timezone

from main.models import Artist, Song
from main.musicfiles import read_artist_mbid

logger = logging.getLogger(__name__)

FANARTTV_URL = 'https://webservice.fanart.tv/v3/music/{mbid}'
BACKGROUND_SUFFIXES = {'.jpg', '.jpeg', '.png', '.webp'}


def artist_dir(artist: Artist) -> Path:
    """Get the folder holding the artist's photos."""
    return settings.ARTISTS_DIR / artist.slug


def list_backgrounds(artist: Artist) -> list[Path]:
    """Get the artist's photos in a stable order, so a play count picks each in turn."""
    folder = artist_dir(artist)
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.iterdir() if p.suffix.lower() in BACKGROUND_SUFFIXES)


def fetch_backgrounds(artist: Artist) -> bool:
    """Download the artist's fanart.tv backgrounds not on disk yet.

    Returns False on a failure worth retrying; the artist is then not marked as fetched.
    """
    song = next((s for s in Song.objects.filter(artist=artist) if s.file_exists()), None)
    mbid = read_artist_mbid(song) if song else None
    if mbid:
        try:
            for image in _get_artist_backgrounds(mbid):
                _download(image, artist_dir(artist))
        except httpx2.HTTPError as exc:
            logger.warning(f'⚠️ Backgrounds fetch failed for {artist}: {exc}')
            return False
    else:
        logger.info(f'Backgrounds: no MusicBrainz id in the tags of {artist}')

    artist.backgrounds_at = timezone.now()
    artist.save(update_fields=['backgrounds_at'])
    return True


def _get_artist_backgrounds(mbid: str) -> list[dict]:
    """Get the artist's backgrounds listed on fanart.tv; an unknown artist has none."""
    response = httpx2.get(
        FANARTTV_URL.format(mbid=mbid),
        params={'api_key': settings.FANARTTV_API_KEY},
        timeout=30,
        follow_redirects=True,
    )
    if response.status_code == 404:  # noqa: PLR2004
        return []
    response.raise_for_status()
    return response.json().get('artistbackground', [])


def _download(image: dict, folder: Path) -> None:
    """Save the image under its fanart.tv id, unless it is already there."""
    path = folder / f'{image["id"]}{Path(image["url"]).suffix.lower() or ".jpg"}'
    if path.exists():
        return
    response = httpx2.get(image['url'], timeout=60, follow_redirects=True)
    response.raise_for_status()
    folder.mkdir(parents=True, exist_ok=True)
    path.write_bytes(response.content)
