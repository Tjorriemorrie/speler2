import logging

import requests
from bs4 import BeautifulSoup
from django.conf import settings
from django.core.cache import cache
from django.db.models import F, Max, Sum
from django.utils import timezone
from django.utils.text import slugify
from pylast import LastFMNetwork
from unidecode import unidecode

from main.models import Album, Artist, History, Similar

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
    song = history.song
    timestamp = int(history.played_at.timestamp())
    network = get_network()
    network.scrobble(
        artist=song.artist.name,
        title=song.name,
        timestamp=timestamp,
        album=song.album.name,
        track_number=song.track_number,
    )
    logger.info(f'Scrobbled {history}')


def update_next_similar_artist():
    """Get similar albums."""
    if not settings.LASTFM_ENABLE:
        return

    # scrape artists that does not yet have similars
    sim_artist_ids = Similar.objects.values('artist_id')
    next_artist = Artist.objects.exclude(id__in=sim_artist_ids).order_by('-rating').first()

    if next_artist:
        logger.info(f'Getting similar artists for {next_artist}')
        network = get_network()
        lastfm_artist = network.get_artist(next_artist.name)
        similar_artists = lastfm_artist.get_similar(limit=100)
        logger.info(f'Processing {len(similar_artists)}...')
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
        .order_by('-total_score')
    )

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


def scrape_studio_albums():
    """Scrapes studio album names and their links from a Wikipedia discography page."""
    cache_key = 'wiki_studio_albums'
    if album_details := cache.get(cache_key):
        logger.info(f'Cache found for {album_details}')
        return album_details

    artist = Artist.objects.order_by(F('disco_at').asc(nulls_first=True)).first()
    logger.info(f'Fetching studio albums from {artist.wiki_link}')
    response = requests.get(artist.wiki_link, timeout=10)
    response.raise_for_status()
    soup = BeautifulSoup(response.content, 'html.parser')
    album_tables = soup.find_all('table', {'class': 'wikitable'})
    if not album_tables:
        album_details = (artist, ': cannot read wiki page')
    else:
        for row in album_tables[0].find_all('tr')[2:]:
            th_cell = row.find('th')
            if not th_cell:
                logger.info(f'No th header for: {row.text}')
                continue  # "—" denotes a release that did not chart or was not issued in that
            album_title = th_cell.get_text()
            if th_anchor := th_cell.find('a'):
                album_link = f"https://en.wikipedia.org{th_anchor['href']}"
            else:
                album_link = None

            album_slug = f'{artist.slug}-{slugify(unidecode(album_title))}'
            try:
                artist.albums.get(slug=album_slug)
                logger.info(f'Studio album exists: {album_title}')
            except Album.DoesNotExist:
                logger.info(f'Missing album found: {album_title}')
                if f'{artist.name} {album_title}' in BAD_ALBUMS:
                    logger.info(f'Ignoring album {album_title}')
                    continue
                album_details = (artist, album_title, album_link)
                cache.set(cache_key, album_details, timeout=3600)
                break
        else:
            album_details = (artist,)
            logger.info(f'No missing studio albums found for {artist}')

    artist.disco_at = timezone.now()
    artist.save()
    return album_details
