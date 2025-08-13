import datetime
import logging
import re

import pylast
import requests
from bs4 import BeautifulSoup
from django.conf import settings
from django.db.models import F, Max, Sum
from django.utils import timezone
from django.utils.text import slugify
from pylast import LastFMNetwork
from unidecode import unidecode

from main.models import Artist, History, Similar

logger = logging.getLogger(__name__)


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
        return
    logger.info(f'Scrobbling {history}')
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
    except pylast.NetworkError:
        logger.error('Timeout connecting to LastFM')


def update_next_similar_artist():
    """Get similar albums."""
    if not settings.LASTFM_ENABLE:
        return

    # scrape artists that does not yet have similars
    sim_artist_ids = Similar.objects.values('artist_id')
    next_artist = Artist.objects.exclude(id__in=sim_artist_ids).order_by('-rating').first()

    # clear existing rows
    cnt = Similar.objects.filter(artist=next_artist).delete()

    if next_artist:
        logger.info(f'Getting similar artists for {next_artist}')
        network = get_network()
        lastfm_artist = network.get_artist(next_artist.name)
        similar_artists = lastfm_artist.get_similar(limit=100)
        for similar_artist, match in similar_artists:
            sim_artist_name = similar_artist.get_name()
            sim_artist_slug = slugify(unidecode(sim_artist_name))
            score = next_artist.rating * match
            Similar.objects.create(
                artist=next_artist,
                artist_name=sim_artist_name,
                artist_slug=sim_artist_slug,
                match=match,
                rating=next_artist.rating,
                score=score,
                scraped_at=timezone.now(),
            )
    else:
        raise NotImplementedError('need to rehandle similar artists already done')

    excluded_slugs = Artist.objects.values_list('slug', flat=True)
    grouped_artists = (
        Similar.objects.exclude(artist_slug__in=excluded_slugs)
        .values('artist_slug')
        .annotate(total_score=Sum('score'), artist_name=Max('artist_name'))
        .order_by('-total_score')[:10]
    )

    logger.info(f'Similar artists updated for {next_artist} (removed {cnt[0]})')
    return grouped_artists


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
    # update timestamp
    if refresh:
        logger.info(f'Marked {artist.name} discography as scraped.')
        artist.disco_at = timezone.now() + datetime.timedelta(days=30 * artist.count_albums)
        artist.save()
        artist = Artist.objects.order_by(
            F('disco_at').asc(nulls_first=True), 'count_albums'
        ).first()

    wiki_details = {
        'artist': artist,
        'albums': [],
    }
    logger.info(f'Fetching {artist.name} studio albums from {artist.wiki_link}')

    # try getting discography from band page
    url = artist.wiki_link
    url = url.replace('discography', '').strip()
    response = requests.get(url, timeout=20)
    response.raise_for_status()
    soup = BeautifulSoup(response.content, 'html.parser')

    try:
        disc_tag = soup.find('h2', id='Discography').parent
    except AttributeError:
        try:
            disc_tag = soup.find('h2', id='Solo_discography').parent
        except AttributeError:
            url += '(band)'
            response = requests.get(url, timeout=20)
            response.raise_for_status()
            soup = BeautifulSoup(response.content, 'html.parser')
            try:
                disc_tag = soup.find('h2', id='Discography').parent
            except AttributeError as exc:
                raise ValueError(f'Cannot find discography for {artist.name}') from exc

    subheading_tag = disc_tag.find_next(
        string=re.compile(r'\b(Main articles?|Studio)\b', re.IGNORECASE)
    )
    subheading_tag = subheading_tag.parent if subheading_tag else disc_tag

    # Find the first table or ul after the subheading, stopping at next h2
    wrapper_tag = None
    for tag in subheading_tag.find_all_next():
        if tag.name in ['table', 'ul']:
            wrapper_tag = tag
            break
        if tag.name == 'h2':
            break

    if not wrapper_tag:
        raise ValueError(f'Could not find album list table/ul for {artist.name}')

    if wrapper_tag.name == 'table':
        for tr in wrapper_tag.find_all('tr'):
            tds = tr.find_all('td', recursive=False)
            length_of_forgot = 2
            if not tds or len(tds) < length_of_forgot:
                continue  # th row
            cells = tr.find_all(['td', 'th'], recursive=False)
            # first cell is year
            length_of_year = 4
            if len(cells[0].get_text(separator=' ', strip=True)) == length_of_year:
                anchor = cells[1].find('a')
                name = cells[1].get_text(separator=' ', strip=True)
                name = name.split('Released:')[0].strip()
                year = cells[0].get_text(strip=True)
            # else first name then year
            else:
                anchor = cells[0].find('a')
                name = cells[0].get_text(separator='\n', strip=True).split('\n')[0]
                try:
                    year_txt = cells[1].get_text(separator=' ', strip=True)
                    year = re.search(r'\b\d{4}\b', year_txt).group()
                except AttributeError:  # trust company has release in first cell below name
                    year_txt = cells[0].get_text(separator='\n', strip=True).split('\n')[1]
                    year = re.search(r'\b\d{4}\b', year_txt).group()

            wiki_details['albums'].append(
                {
                    'year': year,
                    'name': name,
                    'href': ('https://en.wikipedia.org' + anchor['href']) if anchor else None,
                }
            )
    elif wrapper_tag.name == 'ul':
        for li in wrapper_tag.find_all('li', recursive=False):
            name_txt = li.get_text(separator=' ', strip=True)
            name = name_txt.split('(')[0]
            year = re.search(r'(\d{4})', li.text).group(1)
            anchor = li.find('a')
            wiki_details['albums'].append(
                {
                    'year': year,
                    'name': name.strip(),
                    'href': ('https://en.wikipedia.org' + anchor['href']) if anchor else None,
                }
            )
    else:
        raise ValueError(f'Unknown tag for wrapper {wrapper_tag.name}. Check {artist} manually')

    # strip year prefix from name
    for album_info in wiki_details['albums']:
        if album_info['name'].startswith(album_info['year']):
            album_info['name'] = album_info['name'][5:]

    logger.info(f'Successfully scraped {len(wiki_details["albums"])} albums for {artist}')

    # match albums
    album_names = {a.name for a in artist.albums.all()}
    for album_info in wiki_details['albums']:
        album_info['own'] = album_info['name'] in album_names

    return wiki_details
