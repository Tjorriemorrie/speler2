import logging

from django.conf import settings
from pylast import LastFMNetwork

from main.models import History

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


# class LastFm(LastFMNetwork):
#     love_cutoff = 0.97
#
#     def __init__(self):
#         """Pass in params."""
#         super().__init__(
#         )
#
#     def scrobble(self, history):
#         """Scrobble song to lastfm"""
#         params = {
#             'artist': history.song.artist.name,
#             'album': history.song.album.name,
#             'title': history.song.name,
#             'track_number': history.song.track_number,
#             'timestamp': int(history.played_at.timestamp()),
#         }
#         logger.info('scrobbling: {}'.format(params))
#         self.network.scrobble(**params)
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
#
#     def get_similar_tracks(self, artist, title):
#         """Get similar tracks to this song"""
#         track = self.network.get_track(artist, title)
#         similar = track.get_similar()
#         logger.info('Found {} similar tracks for {} {}'.format(len(similar), artist, title))
#         return similar
