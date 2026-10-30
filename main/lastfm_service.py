import datetime
import logging
import math
import re
import string
import unicodedata
from typing import List

import bs4
import pylast
import requests
from bs4 import BeautifulSoup
from django.conf import settings
from django.db import transaction
from django.db.models import Count, F, Max, Sum
from django.utils import timezone
from django.utils.text import slugify
from pylast import LastFMNetwork
from unidecode import unidecode

from main.models import Artist, History, Similar, Song

logger = logging.getLogger(__name__)

# fetch enough similar tracks that the best 10 not already owned are left after filtering
SIMILARS_FETCH_LIMIT = 50
SIMILARS_KEEP_LIMIT = 10
# pylast fixes its timeout (5s connect, 10s read) for every call, so the fetch gets more time by
# retrying; a scrobble keeps its single attempt, since playback waits on it
SIMILARS_FETCH_ATTEMPTS = 3
# order in which songs are fetched as seeds and listed as recommenders
# id breaks ties, so a song keeps its place in the progress count between renders
SIMILARS_SEED_ORDERING = ('-count_played', '-rating', '-artist__rating', 'id')
# only the top decile of songs are seeds; once all are fetched they are refetched oldest first
SIMILARS_SEED_SHARE = 0.1
SIMILARS_SONGS_SHOWN = 10


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


def _owned_tracks(artist_slugs: set[str]) -> set[tuple[str, str]]:
    """Get (artist_slug, track_slug) of every library song by these artists."""
    songs = Song.objects.filter(artist__slug__in=artist_slugs).values_list('artist__slug', 'name')
    owned = {(slug, track_slug(name)) for slug, name in songs}
    logger.info(f'🎵 Listed owned tracks: artists_count={len(artist_slugs)}, owned={len(owned)}')
    return owned


def _get_similar_tracks(track: pylast.Track) -> list[pylast.SimilarItem]:
    """Get the track's similar tracks, retrying network errors such as a timed out handshake."""
    for attempt in range(1, SIMILARS_FETCH_ATTEMPTS + 1):
        try:
            similar_tracks = track.get_similar(limit=SIMILARS_FETCH_LIMIT)
        except pylast.NetworkError as exc:
            if attempt == SIMILARS_FETCH_ATTEMPTS:
                logger.warning(
                    f'⚠️ LastFM network error on the last attempt, giving up: track={track}, '
                    f'attempts={attempt}'
                )
                raise
            logger.warning(
                f'⚠️ LastFM network error, retrying: track={track}, attempt={attempt}, error={exc}'
            )
            continue
        logger.info(
            f'🎵 Fetched similar tracks: track={track}, attempt={attempt}, '
            f'count={len(similar_tracks)}'
        )
        return similar_tracks


def _get_seed_ids() -> list[int]:
    """Ids of the seed songs: the top decile of the library, best first."""
    limit = math.ceil(Song.objects.count() * SIMILARS_SEED_SHARE)
    return list(
        Song.objects.order_by(*SIMILARS_SEED_ORDERING).values_list('id', flat=True)[:limit]
    )


def get_similars_progress() -> tuple[int, int] | None:
    """Place of the latest fetched seed among the seeds, and how many seeds there are."""
    seed_ids = _get_seed_ids()
    latest_id = (
        Song.objects.filter(id__in=seed_ids, similars_at__isnull=False)
        .order_by('-similars_at')
        .values_list('id', flat=True)
        .first()
    )
    if latest_id is None:
        return None
    return seed_ids.index(latest_id) + 1, len(seed_ids)


def update_next_similar_song():
    """Store the best similar tracks not owned yet for the seed song fetched longest ago."""
    if not settings.LASTFM_ENABLE:
        logger.info('🎵 LastFM disabled, not updating similar songs')
        return

    # never fetched comes first, best seed first; after that the oldest fetch is redone
    seed = (
        Song.objects.filter(id__in=_get_seed_ids())
        .select_related('artist')
        .order_by(F('similars_at').asc(nulls_first=True), *SIMILARS_SEED_ORDERING)
        .first()
    )
    if not seed:
        logger.info('🎵 No songs in the library, nothing to update')
        return

    seed_artist = straighten_quotes(seed.artist.name)
    seed_title = straighten_quotes(seed.name)
    logger.info(
        f'🎵 Fetching similar songs: song_id={seed.id}, artist={seed_artist}, title={seed_title}'
    )
    try:
        lastfm_track = get_network().get_track(seed_artist, seed_title)
        similar_tracks = _get_similar_tracks(lastfm_track)
    except pylast.PyLastError as exc:
        # unknown track is final, so it must not block the songs after it; anything else is retried
        if not (
            isinstance(exc, pylast.WSError) and exc.status == str(pylast.STATUS_INVALID_PARAMS)
        ):
            logger.warning(
                f'⚠️ Fetching similar songs from LastFM failed, retrying next update: '
                f'song_id={seed.id}, artist={seed_artist}, title={seed_title}, error={exc}'
            )
            return
        logger.warning(
            f'⚠️ Song not found on LastFM, marking it done: song_id={seed.id}, '
            f'artist={seed_artist}, title={seed_title}'
        )
        similar_tracks = []

    tracks = [
        (similar.item.artist.name, similar.item.title, similar.match) for similar in similar_tracks
    ]
    # owned tracks are skipped, and so are repeats that slug the same (e.g. a live version)
    skip = _owned_tracks({artist_slug(name) for name, _, _ in tracks})
    count_skipped = 0
    now = timezone.now()
    similars = []
    for track_artist, track_name, match in tracks:
        key = (artist_slug(track_artist), track_slug(track_name))
        # an empty slug (e.g. a title only in brackets) cannot be put in the remove url
        if not all(key) or key in skip:
            count_skipped += 1
            continue
        skip.add(key)
        similars.append(
            Similar(
                song=seed,
                artist_name=track_artist,
                artist_slug=key[0],
                track_name=track_name,
                track_slug=key[1],
                match=match,
                rating=seed.rating,
                score=seed.rating * match,
                scraped_at=now,
            )
        )
        if len(similars) == SIMILARS_KEEP_LIMIT:
            break

    # a refetch replaces the seed's previous tracks rather than adding to them
    with transaction.atomic():
        count_replaced, _ = Similar.objects.filter(song=seed).delete()
        Similar.objects.bulk_create(similars)
        seed.similars_at = now
        seed.save(update_fields=['similars_at'])
    logger.info(
        f'🎵 Similar songs updated: song_id={seed.id}, artist={seed_artist}, title={seed_title}, '
        f'fetched={len(tracks)}, skipped={count_skipped}, saved={len(similars)}, '
        f'replaced={count_replaced}'
    )


def get_recommended_song() -> dict | None:
    """Get the track most similar across the library, with the best songs that recommended it."""
    ranked = (
        Similar.objects.values('artist_slug', 'track_slug')
        .annotate(
            total_score=Sum('score'),
            count_songs=Count('id'),
            artist_name=Max('artist_name'),
            track_name=Max('track_name'),
        )
        .order_by('-total_score')
    )
    for best in ranked:
        # its album may have been added to the library since it was fetched
        if (best['artist_slug'], best['track_slug']) not in _owned_tracks({best['artist_slug']}):
            break
        deleted, _ = Similar.objects.filter(
            artist_slug=best['artist_slug'], track_slug=best['track_slug']
        ).delete()
        logger.info(
            f'🎵 Dropped recommendation now in library: artist={best["artist_name"]}, '
            f'track={best["track_name"]}, deleted={deleted}'
        )
    else:
        logger.info('🎵 No recommended song yet')
        return None

    best['songs'] = list(
        Song.objects.filter(
            similars__artist_slug=best['artist_slug'], similars__track_slug=best['track_slug']
        )
        .select_related('artist', 'album')
        # reuses the filter's join, so each song gets the match of its own row
        .annotate(match=F('similars__match'))
        .order_by('-match')[:SIMILARS_SONGS_SHOWN]
    )
    logger.info(
        f'🎵 Recommended song: artist={best["artist_name"]}, track={best["track_name"]}, '
        f'total_score={best["total_score"]:.3f}, count_songs={best["count_songs"]}'
    )
    return best


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
