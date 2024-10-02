import logging
import re
from datetime import datetime
from pathlib import Path
from xml.etree import ElementTree

import requests
from bs4 import BeautifulSoup
from django.conf import settings
from django.db.models import Max
from django.utils import timezone
from django.utils.text import slugify
from unidecode import unidecode

from main.constants import (
    AZLYRICS_ARTISTS,
    AZLYRICS_INSTRUMENTALS,
    AZLYRICS_SONGS,
    BILLBOARD_CHART_URLS,
)
from main.models import Billboard, Song

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
    response = requests.get(url, params=params, timeout=15)
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
    artist_name = unidecode(song.artist.name.casefold())
    artist_name = re.sub(r'[^a-z0-9]', '', artist_name)

    song_name = unidecode(song.name.casefold())
    song_name = re.sub(r'[^a-z0-9]', '', song_name)

    lyrics_file_path = Path(settings.LYRICS_DIR) / f'{artist_name}-{song_name}-{song.id}.txt'
    if lyrics_file_path.exists():
        if use_cache:
            with Path.open(lyrics_file_path, 'r', encoding='utf-8') as file:
                return file.read()
        else:
            logger.info(f'Removed existing lyrics file: {lyrics_file_path}')
            lyrics_file_path.unlink()

    lyrics_txt = scrape_azlyrics(artist_name, song_name)

    lyrics = clean_text_with_paragraphs(lyrics_txt)

    with Path.open(lyrics_file_path, 'w', encoding='utf-8') as file:
        file.write(lyrics)
    logger.info(f'{len(lyrics)} Lyrics written to {lyrics_file_path}')

    return lyrics


def scrape_azlyrics(artist_name: str, song_name: str) -> str:
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

    # Check if the name starts with 'the ' and remove it
    if artist_name.startswith('the'):
        artist_name = artist_name[3:]
    if artist_name in AZLYRICS_ARTISTS:
        artist_name = AZLYRICS_ARTISTS[artist_name]
    # logger.info(f'AZLyrics: artist name: {artist_name}')

    if song_name in AZLYRICS_SONGS:
        song_name = AZLYRICS_SONGS[song_name]
    # logger.info(f'AZLyrics: song name: {song_name}')

    instrumental_name = f'{artist_name}-{song_name}'
    # logger.info(f'Checking if {instrumental_name} is instrumental...')
    if instrumental_name in AZLYRICS_INSTRUMENTALS:
        raise ValueError('[Instrumental]')

    # get lyrics
    url_page = f'https://www.azlyrics.com/lyrics/{artist_name}/{song_name}.html'
    res_l = requests.get(url_page, timeout=15)
    res_l.raise_for_status()
    soup = BeautifulSoup(res_l.content, 'html.parser')
    main_div = soup.find('div', class_='container main-page')
    if 'detected unusual activity from your IP address' in soup.text:
        raise ValueError('Browser check required!')
    b_tags = main_div.find_all('b')
    if len(b_tags) < 2:  # noqa: PLR2004
        logger.info(f'{soup.prettify()}')
        logger.info(b_tags)
        raise ValueError(f'not enough b_tags: {len(b_tags)}')
    artist_txt = b_tags[0].text.rstrip('Lyrics').strip()
    song_txt = b_tags[1].text.lstrip('"').rstrip('"')
    lyrics_txt = soup.find('div', class_=None, id=None).text.strip()

    lyrics = f'{artist_txt} - {song_txt}\n\n{lyrics_txt}'
    return lyrics


def scrape_billboards(*args, **kwargs):
    """Get top rock albums from billboard."""
    latest_charts = Billboard.objects.values('chart').annotate(latest_chart_at=Max('chart_at'))
    all_after_now = all(entry['latest_chart_at'] > timezone.now() for entry in latest_charts)
    if all_after_now and len(latest_charts) == len(BILLBOARD_CHART_URLS):
        logger.info('All billboards already scraped.')
        return

    for chart, url in BILLBOARD_CHART_URLS.items():
        logger.info(f'Scraping billboard {chart}: {url}')
        res = requests.get(url, timeout=30)
        res.raise_for_status()

        soup = BeautifulSoup(res.content, 'html.parser')
        # get date of chart
        date_str = soup.find(string=re.compile('Week of ')).text
        chart_day = datetime.strptime(date_str.replace('Week of', '').strip(), '%B %d, %Y')
        chart_at = chart_day.replace(hour=23, minute=59, second=59)

        rows = soup.find_all('div', class_='o-chart-results-list-row-container')
        for ix, row in enumerate(rows):
            if ix >= 25:  # noqa: PLR2004
                break
            lis = row.find_all('li')
            pos_str = lis[0].text
            pos = int(re.search(r'\d+', pos_str).group())
            artist_name = lis[4].find('span').text.strip()
            img = lis[1].find('img')['src']
            album_name = lis[4].find('h3').text.strip()
            last_week = lis[7].text.strip()
            last_week = None if last_week == '-' else int(last_week)
            peak_pos = int(lis[8].text)
            wks_on_chart = int(lis[9].text)

            billboard, _ = Billboard.objects.update_or_create(
                chart=chart,
                artist_slug=slugify(unidecode(artist_name)),
                album_slug=slugify(unidecode(album_name)),
                defaults={
                    'pos': pos,
                    'artist_name': artist_name,
                    'album_name': album_name,
                    'chart_at': chart_at,
                    'img_src': img,
                    'last_week': last_week,
                    'peak_pos': peak_pos,
                    'wks_on_chart': wks_on_chart,
                    'scraped_at': timezone.now(),
                },
            )
            logger.info(f'Processed {billboard}')
    logger.info('Finished scraping billboards!')
