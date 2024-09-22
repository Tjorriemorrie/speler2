import logging
import re
from pathlib import Path
from xml.etree import ElementTree

import requests
from django.conf import settings

from main.models import Song

logger = logging.getLogger(__name__)


def get_lyrics_chartlyrics(song: Song, use_cache: bool = True) -> str:
    """Get .lyric_txt from chartlyricsa api."""
    # Define file path to store lyrics in settings.LYRICS_DIR
    lyrics_file_path = Path(settings.LYRICS_DIR) / f'{song.artist.slug}-{song.slug}-{song.id}.txt'
    if lyrics_file_path.exists():
        if use_cache:
            with Path.open(lyrics_file_path, 'r', encoding='utf-8') as file:
                return file.read()
        else:
            logger.info(f'Removed existing lyrics file: {lyrics_file_path}')
            lyrics_file_path.unlink()

    url = 'http://api.chartlyrics.com/apiv1.asmx/SearchLyricDirect'
    params = {
        'artist': song.artist.name,
        'song': song.name,
    }
    response = requests.get(url, params=params, timeout=5)
    try:
        response.raise_for_status()
    except requests.RequestException as exc:
        return str(exc)

    # Parse the XML response
    root = ElementTree.fromstring(response.content)  # noqa: S314

    # Define the namespace
    namespace = {'ns': 'http://api.chartlyrics.com/'}

    # Find the .lyric_txt with the namespace
    lyrics = root.find('.//ns:Lyric', namespace)
    artist_el = root.find('.//ns:LyricArtist', namespace)
    song_el = root.find('.//ns:LyricSong', namespace)
    if lyrics is not None and lyrics.text:
        lyrics_txt = lyrics.text
        if '\n' not in lyrics_txt and '\r' not in lyrics_txt:
            lyrics_txt = re.sub(r'(?<!^)([A-Z])', r'\n\1', lyrics_txt)
        # add artist and song
        lyrics_txt = f'{artist_el.text} - {song_el.text}\n\n{lyrics_txt}'
        if use_cache:
            with Path.open(lyrics_file_path, 'w', encoding='utf-8') as file:
                file.write(lyrics_txt)
            logger.info(f'{len(lyrics_txt)} Lyrics written to {lyrics_file_path}')
        return lyrics_txt
    else:
        return 'Lyrics not found.'
