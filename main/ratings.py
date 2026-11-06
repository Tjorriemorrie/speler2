import logging
from collections import defaultdict
from typing import Iterable, List, Optional, Type

from django.db import connection
from django.db.models import Avg, Max, Q, Sum
from django.utils import timezone

from main.models import Album, Artist, History, Rating, Song

logger = logging.getLogger(__name__)

RATINGS_PER_PLAY = 5
# album and artist ratings are bayesian averages: an album short of ALBUM_FILL_SONGS songs is
# filled up with the library's mean song rating, an artist short of ARTIST_FILL_ALBUMS albums
# with the mean album rating, so one great single (or album) can't outrank a run of great ones
ALBUM_FILL_SONGS = 10
ARTIST_FILL_ALBUMS = 3


def filled_mean(ratings: Iterable[float], size: int, filler: float) -> float:
    """Average the ratings, filled up to size with the filler rating."""
    ratings = list(ratings)
    padding = max(0, size - len(ratings))
    return (sum(ratings) + padding * filler) / (len(ratings) + padding)


def get_mean_rating(model: Type[Song] | Type[Album]) -> float:
    """Get the library's mean rating of songs or albums, the filler for short albums/artists."""
    return model.objects.aggregate(Avg('rating'))['rating__avg'] or 0


def get_album_rating(album: Album, song_mean: float) -> float:
    """Get the album rating: its song ratings filled up with the library's mean song rating."""
    ratings = album.songs.values_list('rating', flat=True)
    return filled_mean(ratings, ALBUM_FILL_SONGS, song_mean)


def get_artist_rating(artist: Artist, album_mean: float) -> float:
    """Get the artist rating: its album ratings filled up with the library's mean album rating.

    Reads the stored album ratings, so update the albums first.
    """
    ratings = artist.albums.values_list('rating', flat=True)
    return filled_mean(ratings, ARTIST_FILL_ALBUMS, album_mean)


def get_match(current_song: Song) -> Optional[List[Song]]:
    """Get next match."""
    rate_count_cut_off = current_song.count_played * RATINGS_PER_PLAY
    if current_song.count_rated > rate_count_cut_off:
        logger.info(
            f'Get match: is rated {current_song.count_rated} '
            f'(more than {rate_count_cut_off} cut off)'
        )
        return

    rated_with = defaultdict(set)
    for winner_id, loser_id in Rating.objects.values_list('winner_id', 'loser_id'):
        rated_with[winner_id].add(loser_id)
        rated_with[loser_id].add(winner_id)

    # every played song, latest play first, so the most recent ones are matched first
    played_ids = History.objects.exclude(song=current_song).values_list('song_id', flat=True)
    song_ids = [i for i in dict.fromkeys(played_ids) if i not in rated_with[current_song.id]]

    for ix, c_id in enumerate(song_ids):
        for b_id in song_ids[:ix]:
            if c_id not in rated_with[b_id]:
                found = Song.objects.in_bulk([b_id, c_id])
                match = [current_song, found[b_id], found[c_id]]
                logger.info(f'Get match: {match}')
                return match

    logger.warning(f'Could not find any match for {current_song}: {len(song_ids)} unrated songs')


def set_match_result(winner_id: int, loser_ids: List[int]) -> List[int]:
    """Set winner against the losers, skipping songs no longer in the library.

    Returns the ids of the skipped songs. Without the winner or any loser nothing is rated.
    """
    found = Song.objects.in_bulk([winner_id, *loser_ids])
    missing_ids = [i for i in dict.fromkeys([winner_id, *loser_ids]) if i not in found]
    losers = [found[i] for i in loser_ids if i != winner_id and i in found]
    if winner_id not in found or not losers:
        logger.warning(
            f'⚠️ Set match result: nothing left to rate: winner_id={winner_id}, '
            f'loser_ids={loser_ids}, missing_ids={missing_ids}'
        )
        return missing_ids

    winner = found[winner_id]
    songs = {winner}
    for loser in losers:
        rating = Rating.objects.create(winner=winner, loser=loser, rated_at=timezone.now())
        logger.info(f'⚖️ Created rating: {rating}')
        songs.add(loser)

    albums = set()
    for song in songs:
        ratings = Rating.objects.filter(Q(winner=song) | Q(loser=song))
        count_wins = Rating.objects.filter(winner=song).count()
        song.count_rated = ratings.count()
        song.rated_at = ratings.aggregate(Max('rated_at'))['rated_at__max']
        song.rating = count_wins / ratings.count()
        song.save()
        albums.add(song.album)

    artists = set()
    song_mean = get_mean_rating(Song)
    for album in albums:
        album.count_rated = album.songs.aggregate(Sum('count_rated'))['count_rated__sum']
        album.rated_at = album.songs.aggregate(Max('rated_at'))['rated_at__max']
        album.rating = get_album_rating(album, song_mean)
        album.save()
        artists.add(album.artist)

    album_mean = get_mean_rating(Album)
    for artist in artists:
        artist.count_rated = artist.albums.aggregate(Sum('count_rated'))['count_rated__sum']
        artist.rated_at = artist.albums.aggregate(Max('rated_at'))['rated_at__max']
        artist.rating = get_artist_rating(artist, album_mean)
        artist.save()

    logger.info(
        f'⚖️ Set match result: winner_id={winner_id}, losers={len(loser_ids)}, '
        f'missing_ids={missing_ids}, albums={len(albums)}, artists={len(artists)}, '
        f'song_mean={song_mean:.3f}, album_mean={album_mean:.3f}'
    )
    return missing_ids


def get_median_rating():
    """Get median rating."""
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT AVG(rating)
            FROM (
                SELECT rating
                FROM your_app_album
                ORDER BY rating
                LIMIT 2
                OFFSET (SELECT (COUNT(*) - 1) / 2 FROM your_app_album)
            );
        """)
        result = cursor.fetchone()
    return result[0] if result else None
