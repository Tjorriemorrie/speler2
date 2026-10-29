import logging
from datetime import timedelta
from itertools import combinations
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


def get_recent_songs_from_history() -> List[Song]:
    """Get recent histories of last half hour, limited to 10."""
    from main.plays import RATINGS_WINDOW  # noqa: PLC0415  circular import

    time_ago = timezone.now() - timedelta(seconds=RATINGS_WINDOW)
    histories = History.objects.prefetch_related('song').filter(played_at__gt=time_ago).all()
    songs = []
    for h in histories:
        if h.song not in songs:
            songs.append(h.song)
    return songs


def get_match(current_song: Song) -> Optional[List[Song]]:
    """Get next match."""
    rate_count_cut_off = current_song.count_played * RATINGS_PER_PLAY
    if current_song.count_rated > rate_count_cut_off:
        logger.info(
            f'Get match: is rated {current_song.count_rated} '
            f'(more than {rate_count_cut_off} cut off)'
        )
        return

    songs = get_recent_songs_from_history()
    songs.insert(0, current_song)
    song_ids = [s.id for s in songs]
    # logger.info(f'Searching {song_ids} for a match...')

    # Filter ratings for the relevant song pairs
    ratings = Rating.objects.filter(
        Q(winner_id__in=song_ids) | Q(loser_id__in=song_ids)
    ).values_list('winner_id', 'loser_id')

    # Convert ratings to a set for faster lookup
    rated_pairs = set()
    for winner, loser in ratings:
        rated_pairs.add((winner, loser))
        rated_pairs.add((loser, winner))  # Add reverse pair for bidirectional check

    # Find combinations of songs that have no ratings between them
    songs_bag = []
    for ix, song in enumerate(songs):
        logger.debug(f'Get match: song bag {ix}: {song}')
        songs_bag.append(song)
        for b, c in combinations(songs_bag, 2):
            # Ensure current_song is not one of b or c
            if current_song in (b, c):
                continue
            # logger.info(f'Get match: checking {b} && {c}')
            comb_ids = {current_song.id, b.id, c.id}
            # Check if any pair in comb_ids has been rated
            if not any((winner in comb_ids and loser in comb_ids) for winner, loser in rated_pairs):
                match = [current_song, b, c]
                logger.info(f'Get match: {match}')
                return match

    logger.warning(f'Could not find any match for {song_ids}')


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
