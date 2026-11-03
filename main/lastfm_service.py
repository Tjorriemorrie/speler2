import datetime
import logging
import re
import string
import unicodedata
from typing import List

import bs4
import pylast
import requests
from bs4 import BeautifulSoup
from django.conf import settings
from django.db.models import F
from django.utils import timezone
from django.utils.text import slugify
from pylast import LastFMNetwork
from unidecode import unidecode

from main.models import Artist, History, Song

logger = logging.getLogger(__name__)

# pylast fixes its timeout (5s connect, 10s read) for every call, so the fetch gets more time by
# retrying; a scrobble keeps its single attempt, since playback waits on it
SIMILARS_FETCH_ATTEMPTS = 3


def get_network() -> LastFMNetwork:
    """Get network."""
    return LastFMNetwork(
        api_key=settings.LASTFM_API_KEY,
        api_secret=settings.LASTFM_SECRET,
        session_key=settings.LASTFM_SESSION_FILE.read_text().strip(),
    )


def scrobble(history: History):
    """Scrobble history."""
    if not settings.LASTFM_ENABLE:
        logger.info(f'🎧 LastFM disabled, not scrobbling {history}')
        return
    logger.info(f'🎧 Scrobbling {history}')
    song = history.song
    timestamp = int(history.played_at.timestamp())
    network = get_network()
    try:
        network.scrobble(
            artist=song.artist.name,
            title=song.name,
            timestamp=timestamp,
            album=song.album.name,
            track_number=song.track_number,
        )
    except pylast.PyLastError as exc:
        # last.fm outages (503 etc) must not break playback
        logger.warning(
            f'⚠️ Scrobble to LastFM failed: history_id={history.id}, artist={song.artist.name}, '
            f'title={song.name}, album={song.album.name}, timestamp={timestamp}, error={exc}'
        )
        return
    logger.info(f'🎧 Scrobbled {history}')


def artist_slug(name: str) -> str:
    """Slug an artist name the way musicfiles slugs Artist.slug, so Maneskin matches Måneskin."""
    return slugify(unidecode(name))


def track_slug(name: str) -> str:
    """Slug a track name with bracketed suffixes like (Remastered) or [Live] dropped."""
    return slugify(unidecode(re.sub(r'\s*[(\[][^)\]]*[)\]]', '', name)))


def straighten_quotes(text: str) -> str:
    """Replace curly apostrophes, which last.fm does not match to straight ones."""
    return text.replace('’', "'").replace('‘', "'")


def _owned_artists(artist_slugs: set[str]) -> set[str]:
    """Get the slugs of these artists that are in the library."""
    owned = set(Artist.objects.filter(slug__in=artist_slugs).values_list('slug', flat=True))
    logger.info(f'🎵 Listed owned artists: artists_count={len(artist_slugs)}, owned={len(owned)}')
    return owned


def _owned_tracks(artist_slugs: set[str]) -> set[tuple[str, str]]:
    """Get (artist_slug, track_slug) of every library song by these artists."""
    songs = Song.objects.filter(artist__slug__in=artist_slugs).values_list('artist__slug', 'name')
    owned = {(slug, track_slug(name)) for slug, name in songs}
    logger.info(f'🎵 Listed owned tracks: artists_count={len(artist_slugs)}, owned={len(owned)}')
    return owned


def get_similar_artists(artist_name: str, limit: int) -> list[tuple[str, float]]:
    """Get the artist's similar artists as (name, match), retrying network errors."""
    lastfm_artist = get_network().get_artist(artist_name)
    for attempt in range(1, SIMILARS_FETCH_ATTEMPTS + 1):
        try:
            similar_artists = lastfm_artist.get_similar(limit=limit)
        except pylast.NetworkError as exc:
            if attempt == SIMILARS_FETCH_ATTEMPTS:
                logger.warning(
                    f'⚠️ LastFM network error on the last attempt, giving up: '
                    f'artist={artist_name}, attempts={attempt}'
                )
                raise
            logger.warning(
                f'⚠️ LastFM network error, retrying: artist={artist_name}, attempt={attempt}, '
                f'error={exc}'
            )
            continue
        logger.info(
            f'🎵 Fetched similar artists: artist={artist_name}, attempt={attempt}, '
            f'count={len(similar_artists)}'
        )
        return [(similar.item.name, similar.match) for similar in similar_artists]


def get_artist_top_tracks(artist_name: str, limit: int) -> list[tuple[str, int]]:
    """Get the artist's most played tracks as (title, playcount)."""
    top_tracks = get_network().get_artist(artist_name).get_top_tracks(limit=limit)
    logger.info(f'🎵 Fetched artist top tracks: artist={artist_name}, count={len(top_tracks)}')
    return [(top.item.title, int(top.weight)) for top in top_tracks]


def get_artist_top_albums(artist_name: str, limit: int) -> list[tuple[str, int, str]]:
    """Get the artist's most played albums as (title, playcount, url)."""
    top_albums = get_network().get_artist(artist_name).get_top_albums(limit=limit)
    logger.info(f'🎵 Fetched artist top albums: artist={artist_name}, count={len(top_albums)}')
    return [(top.item.title, int(top.weight), top.item.get_url()) for top in top_albums]


def get_album_tracks(artist_name: str, album_title: str) -> list[str]:
    """Get the titles of the album's tracks."""
    tracks = get_network().get_album(artist_name, album_title).get_tracks()
    logger.info(
        f'🎵 Fetched album tracks: artist={artist_name}, album={album_title}, count={len(tracks)}'
    )
    return [track.title for track in tracks]


# class LastFm(LastFMNetwork):
#     love_cutoff = 0.97
#
#     def __init__(self):
#         """Pass in params."""
#         super().__init__(
#         )
#
#     def show_some_love(self, songs):
#         """Sets track to love or not"""
#         logger.info('showing some love for {} songs'.format(len(songs)))
#         for song in songs:
#             # .session.refresh(song)
#             network_track = self.network.get_track(song.artist.name, song.name)
#             is_loved = song.rating >= self.LOVE_CUTOFF
#             logger.info('[{:.0f}%] {} loving {}'.format(
#                 song.rating * 100, is_loved, network_track))
#             if is_loved:
#                 network_track.love()
#             else:
#                 network_track.unlove()
#             # is_loved = network_track.get_userloved()
#             # app.logger.debug('found network track {} loved {}'.format(network_track, is_loved))
#             # if is_loved:
#             #     if song.rating < self.LOVE_CUTOFF:
#             #         app.logger.info('lost love {} [{:.0f}%]'.format(network_track, song.rating *
#             #                                                        100))
#             #         res = network_track.unlove()
#             #         app.logger.debug(res)
#             #     else:
#             #    app.logger.info('still loving {} [{:.0f}%]'.format(network_track, song.rating *
#             #                                                          100))
#             # else:
#             #     res = network_track.unlove()
#             #     app.logger.debug(res)
#             #     if song.rating >= self.LOVE_CUTOFF:
#             #         app.logger.info('new love {} [{:.0f}%]'.format(network_track, song.rating *
#             #                                                        100))
#             #         res = network_track.love()
#             #         app.logger.debug(res)
#             #     else:
#             #         app.logger.info('still no love for {} [{:.0f}%]'.format(network_track,
#             #                                                              song.rating * 100))
#
#     def get_user_top_albums(self, user_name, period=None):
#         """Get top albums for user"""
#         period = period or PERIOD_12MONTHS
#         user = self.network.get_user(user_name)
#         return user.get_top_albums(period)
#
#     def get_user_playcount(self, user):
#         """Get playcount of user"""


BAD_ALBUMS = ['Seether Disclaimer II', 'Nightwish Human. :II: Nature.']


def scrape_studio_albums(refresh: bool = False) -> dict:  # noqa: PLR0915, PLR0912
    """Scrapes studio album names and their links from a Wikipedia discography page."""
    artist = Artist.objects.order_by(F('disco_at').asc(nulls_first=True), 'count_albums').first()
    if refresh:
        logger.info(f'Marked {artist.name} discography as scraped.')
        artist.disco_at = timezone.now() + datetime.timedelta(days=30 * artist.count_albums)
        artist.save()
        artist = Artist.objects.order_by(
            F('disco_at').asc(nulls_first=True), 'count_albums'
        ).first()

    wiki_details = {'artist': artist, 'albums': []}
    logger.info(f'Fetching {artist.name} studio albums from {artist.wiki_link}')

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
        '(KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36'
    }
    url = artist.wiki_link
    for suffix in ['', ' (band)', ' (musician)']:
        url_used = url + suffix
        response = requests.get(url_used, headers=headers, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')

        id_heading = 'Discography'
        if artist.name == 'Prime Circle':
            id_heading = 'Discography_2'

        disc_heading = find_discography_heading(soup, id_heading)
        if disc_heading:
            break
    else:
        raise ValueError(f'Could not find artist home wiki page: {url}')

    hatnote_tag = find_hatnote_tag(disc_heading)

    albums_tag = find_albums_tag(hatnote_tag)

    if albums_tag.name == 'ul':
        wiki_details['albums'] = extract_albums_from_ul(albums_tag)
        # Collect albums from additional <ul> blocks (e.g. "As Blyss" / "As Lifehouse")
        tag = albums_tag
        while True:
            tag = tag.find_next_sibling()
            if tag is None or (tag.name == 'div' and 'mw-heading2' in tag.get('class', [])):
                break
            if tag.name == 'ul':
                wiki_details['albums'].extend(extract_albums_from_ul(tag))
    elif albums_tag.name == 'table':
        wiki_details['albums'] = extract_albums_from_table(albums_tag)

    # Strip year prefix from name if present
    for album_info in wiki_details['albums']:
        if album_info['year'] and album_info['name'].startswith(album_info['year']):
            album_info['name'] = album_info['name'][5:]

    logger.info(f'Successfully scraped {len(wiki_details["albums"])} albums for {artist}')

    # Mark which albums the artist already owns
    album_names = {clean_name(a.name) for a in artist.albums.all()}
    for album_info in wiki_details['albums']:
        name_clean = clean_name(album_info['name'])
        album_info['own'] = name_clean in album_names

    return wiki_details


def find_discography_heading(soup: bs4.BeautifulSoup, id_heading: str) -> bs4.element.Tag:
    """Find discography tag."""
    # disc_heading = soup.find(id=re.compile(r'(Discography|Solo_discography)', re.I))
    # if not disc_heading:
    #     raise ValueError(f"Cannot find discography for {artist.name}")

    disc_heading = soup.find(id=id_heading)
    """
    <div class="mw-heading mw-heading2">
        <h2 id="Discography">Discography</h2>
        <span class="mw-editsection">
            <span class="mw-editsection-bracket">[</span>
            <a href="/w/index.php?title=Jack_Johnson_(musician)&amp;action=edit&amp;section=11">
                <span>edit</span>
            </a>
            <span class="mw-editsection-bracket">]</span>
        </span>
    </div>
    """
    # move back up to parent if it is a holder
    if disc_heading:
        parent_div = disc_heading.find_parent('div', class_='mw-heading mw-heading2')
        if parent_div:
            return parent_div
    return disc_heading


def find_hatnote_tag(disc_tag: bs4.element.Tag) -> bs4.element.Tag:
    """Check for studio albums heading or otherwise find link."""
    hatnote = disc_tag.find_next(lambda tag: tag.name and 'Main article' in tag.get_text())

    if not hatnote:
        logger.warning('No hatnote found')
        return disc_tag

    return hatnote


def find_albums_tag(studio_tag: bs4.element.Tag) -> bs4.element.Tag:
    """Find the tag that contains the album list."""
    for next_tag in studio_tag.find_all_next():
        tag_name = next_tag.name

        # direct hit
        if tag_name in ('ul', 'table'):
            # infobox special-case: skip to the next table
            if tag_name == 'table' and 'infobox' in next_tag.get('class', []):
                next_real = next_tag.find_next('table')
                if next_real:
                    logger.info('Found discography table after infobox')
                    return next_real
                raise ValueError('Infobox found, but no discography table after it')

            logger.info(f'Found album list as {tag_name} tag')
            return next_tag

        # wrapped in <p> or <div>
        if tag_name in ('p', 'div'):
            inner = next_tag.find(['ul', 'table'])
            if inner:
                # same infobox check for wrapped tables
                if inner.name == 'table' and 'infobox' in inner.get('class', []):
                    next_real = inner.find_next('table')
                    if next_real:
                        logger.info('Found discography table after infobox (wrapped)')
                        return next_real
                    raise ValueError('Infobox found, but no discography table after it')

                logger.info(f'Found album list nested in {tag_name}')
                return inner

    raise ValueError('Could not find album list')


def extract_albums_from_ul(albums_tag: bs4.element.Tag) -> List[dict]:
    """Extract album details, excluding unreleased albums (e.g., TBD)."""
    albums = []
    for li in albums_tag.find_all('li', recursive=False):
        anchor = li.find('a')
        text = li.get_text(strip=True)

        # Try to find a 4-digit year
        year_match = re.search(r'\b\d{4}\b', text)
        if not year_match:
            # Skip entries without a concrete year (TBD / upcoming)
            continue

        name = anchor.get_text(strip=True) if anchor else text
        year = year_match.group()

        album_info = {
            'name': name,
            'year': year,
            'href': ('https://en.wikipedia.org' + anchor['href']) if anchor else None,
        }
        logger.info(f'Extracted album {album_info}')
        albums.append(album_info)

    return albums


def extract_albums_from_table(albums_tag: bs4.element.Tag) -> list[dict[str, str]]:  # noqa: PLR0912, PLR0915
    """Extract album details from a table, handling multiple formats."""
    albums = []

    for tr in albums_tag.find_all('tr'):
        # Try the first format (album name in <th scope="row">)
        header_cell = tr.find('th', scope='row')

        if header_cell:
            # Album name is directly in the <th>
            name = header_cell.get_text(' ', strip=True)
            anchor = header_cell.find('a')
            href = (
                'https://en.wikipedia.org' + anchor['href']
                if anchor and anchor.get('href')
                else None
            )

            # Try to extract year from album details cell
            year = None
            cells = tr.find_all('td', recursive=False)
            if cells:
                album_details = cells[0]

                # Case 1: look for explicit "Release date:"
                li_date = album_details.find('li', string=lambda s: s and 'Release date:' in s)
                if li_date:
                    match = re.search(r'\b(\d{4})\b', li_date.get_text())
                    if match:
                        year = match.group(1)

                # Case 2: fallback — just search any 4-digit year in the cell text
                if year is None:
                    match = re.search(r'\b(\d{4})\b', album_details.get_text(' ', strip=True))
                    if match:
                        year = match.group(1)

        else:
            cells = tr.find_all('td', recursive=False)
            if not cells:
                continue  # skip header rows

            # Format 2: first <td> has album title (<i>) + release details (<ul>)
            # e.g. Trust Company — <td><i>Album</i><ul><li>Released: …</li></ul></td>
            first_i = cells[0].find('i')
            if first_i:
                name = first_i.get_text(' ', strip=True)
                anchor = first_i.find('a')
                href = (
                    'https://en.wikipedia.org' + anchor['href']
                    if anchor and anchor.get('href')
                    else None
                )
                year = None
                li_date = cells[0].find(
                    'li',
                    string=lambda s: s and 'Released' in s,
                )
                if li_date:
                    match = re.search(r'\b(\d{4})\b', li_date.get_text())
                    if match:
                        year = match.group(1)
                if year is None:
                    match = re.search(
                        r'\b(\d{4})\b',
                        cells[0].get_text(' ', strip=True),
                    )
                    year = match.group(1) if match else None

            # Format 3: year in first <td>, album in second <td>
            else:
                cells_req = 2
                if len(cells) < cells_req:
                    continue  # skip non-album rows

                year_text = cells[0].get_text(strip=True)
                match = re.search(r'\b(\d{4})\b', year_text)
                year = match.group(1) if match else None

                album_cell = cells[1]
                i_tag = album_cell.find('i')
                if i_tag:
                    name = i_tag.get_text(' ', strip=True)
                    anchor = i_tag.find('a')
                    href = (
                        'https://en.wikipedia.org' + anchor['href']
                        if anchor and anchor.get('href')
                        else None
                    )
                else:
                    name = album_cell.get_text(' ', strip=True)
                    anchor = album_cell.find('a')
                    href = (
                        'https://en.wikipedia.org' + anchor['href']
                        if anchor and anchor.get('href')
                        else None
                    )

        # Skip entries without a concrete year (TBD / upcoming)
        if not year:
            continue

        albums.append(
            {
                'name': name,
                'year': year,
                'href': href,
            }
        )

    return albums


def clean_name(text: str) -> str:
    """Return album name with bracketed text stripped, normalized, and punctuation removed."""
    # 1. Drop every substring that starts with '(' and ends with ')'
    text = re.sub(r'\s*\([^)]*\)', '', text)

    # 2. Collapse any double spaces that might be left behind
    text = re.sub(r'\s{2,}', ' ', text)

    # 3. Normalize unicode (convert curly quotes, accented letters, etc.)
    text = unicodedata.normalize('NFKC', text)

    # 4. Replace common “smart punctuation” with ASCII equivalents
    substitutions = {
        '’': "'",
        '‘': "'",
        '“': '"',
        '”': '"',
        '–': '-',
        '—': '-',
        '…': '...',
    }
    for bad, good in substitutions.items():
        text = text.replace(bad, good)

    # 5. Strip punctuation
    text = text.translate(str.maketrans('', '', string.punctuation))

    # 6. Trim & casefold
    text = text.strip().casefold()

    return text
