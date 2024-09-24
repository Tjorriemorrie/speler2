import logging
import re
from pathlib import Path
from xml.etree import ElementTree

import requests
from bs4 import BeautifulSoup
from django.conf import settings
from unidecode import unidecode

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
        # clean text
        lyrics_txt = clean_text_with_paragraphs(lyrics_txt)
        # add artist and song
        lyrics_txt = f'{artist_el.text} - {song_el.text}\n\n{lyrics_txt}'
        # store text
        if use_cache:
            with Path.open(lyrics_file_path, 'w', encoding='utf-8') as file:
                file.write(lyrics_txt)
            logger.info(f'{len(lyrics_txt)} Lyrics written to {lyrics_file_path}')
        return lyrics_txt
    else:
        return 'Lyrics not found.'


def clean_text_with_paragraphs(html_text):
    """Remove html tags."""
    # Step 1: Replace `</p>` with two newlines
    text_with_breaks = re.sub(r'</p>', '\n\n', html_text)

    # Step 2: Replace `<br>` tags with a single newline
    text_with_breaks = re.sub(r'<br\s*/?>', '\n', text_with_breaks)

    # Remove all other HTML tags, including <p>
    clean_text = re.sub(r'<[^>]+>', '', text_with_breaks)

    # Strip leading line breaks and whitespace
    clean_text = re.sub(r'^\s*\n+', '', clean_text)

    # Strip leading/trailing whitespace
    clean_text = clean_text.strip()

    # Add line breaks before capitals if none is found
    if '\n' not in clean_text and '\r' not in clean_text:
        clean_text = re.sub(r'(?<!^)([A-Z])', r'\n\n\1', clean_text)

    return clean_text


def search_azlyrics(song: Song, use_cache: bool = True) -> str:
    """Scrape AZ Lyrics."""
    lyrics_file_path = Path(settings.LYRICS_DIR) / f'{song.artist.name}-{song.name}-{song.id}.txt'
    if lyrics_file_path.exists():
        if use_cache:
            with Path.open(lyrics_file_path, 'r', encoding='utf-8') as file:
                return file.read()
        else:
            logger.info(f'Removed existing lyrics file: {lyrics_file_path}')
            lyrics_file_path.unlink()

    try:
        lyrics_txt = scrape_azlyrics(song)
    except (requests.RequestException, ValueError) as exc:
        return str(exc)

    lyrics = clean_text_with_paragraphs(lyrics_txt)

    if use_cache:
        with Path.open(lyrics_file_path, 'w', encoding='utf-8') as file:
            file.write(lyrics)
        logger.info(f'{len(lyrics)} Lyrics written to {lyrics_file_path}')

    return lyrics


def scrape_azlyrics(song: Song) -> str:
    """Search AZ lyrics for song."""
    # url = 'https://search.azlyrics.com/search.php'
    #
    # get hash
    # res_x = requests.get(url, timeout=2)
    # res_x.raise_for_status()
    # soup = BeautifulSoup(res_x.content, 'html.parser')
    # hidden_input = soup.find('input', {'name': 'x'})
    # x_value = hidden_input['value']
    # logger.info(f'AZlyrics: found x: {x_value}')

    # get results
    # params = {
    #     'q': f'{song.artist.name} {song.name}',
    #     'x': x_value,
    # }
    # res_s = requests.get(url, params=params, timeout=2)
    # res_s.raise_for_status()
    # if 'your search returned no results' in res_x.text:
    #     raise ValueError('No lyrics found.')
    # soup = BeautifulSoup(res_x.content, 'html.parser')
    # first_row = soup.find('table').find('tr').find('a')
    # url_page = first_row['href']
    # logger.info(f'AZLyrics: found page: {url_page}')

    artists_map = {
        'u2': 'u2band',
        'theblackkeys': 'blackkeys',
        'theoffspring': 'offspring',
    }
    artist_name = unidecode(song.artist.name.casefold())
    artist_name = re.sub(r'[^a-z0-9]', '', artist_name)
    if artist_name in artists_map:
        artist_name = artists_map[artist_name]
    songs_map = {}
    song_name = unidecode(song.name.casefold())
    song_name = re.sub(r'[^a-z0-9]', '', song_name)
    if song_name in songs_map:
        song_name = songs_map[song_name]
    url_page = f'https://www.azlyrics.com/lyrics/{artist_name}/{song_name}.html'

    # get lyrics
    res_l = requests.get(url_page, timeout=2)
    res_l.raise_for_status()
    soup = BeautifulSoup(res_l.content, 'html.parser')
    main_div = soup.find('div', class_='container main-page')
    b_tags = main_div.find_all('b')
    artist_txt = b_tags[0].text.rstrip('Lyrics').strip()
    song_txt = b_tags[1].text.lstrip('"').rstrip('"')
    lyrics_txt = soup.find('div', class_=None, id=None).text.strip()

    lyrics = f'{artist_txt} - {song_txt}\n\n{lyrics_txt}'
    return lyrics
