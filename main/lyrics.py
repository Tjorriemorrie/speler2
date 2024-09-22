import logging
from pathlib import Path
from xml.etree import ElementTree

import requests
from django.conf import settings

from main.models import Song

logger = logging.getLogger(__name__)


def get_lyrics_chartlyrics(song: Song) -> str:
    """Get .lyric_txt from chartlyricsa api."""
    # Define file path to store lyrics in settings.LYRICS_DIR
    lyrics_file_path = Path(settings.LYRICS_DIR) / f'{song.artist.slug}-{song.slug}-{song.id}.txt'
    if lyrics_file_path.exists():
        with Path.open(lyrics_file_path, 'r', encoding='utf-8') as file:
            return file.read()

    url = 'http://api.chartlyrics.com/apiv1.asmx/SearchLyricDirect'
    params = {
        'artist': song.artist.name,
        'song': song.name,
    }
    response = requests.get(url, params=params, timeout=5)
    logger.info(f'Getting logging from : {response.request.url}')
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
    if lyrics is not None and lyrics.text:
        logger.info(f'{len(lyrics.text)} Lyrics written to {lyrics_file_path}')
        with Path.open(lyrics_file_path, 'w', encoding='utf-8') as file:
            file.write(lyrics.text)
        return lyrics.text
    else:
        return 'Lyrics not found.'
