import logging
from datetime import timedelta
from itertools import combinations
from typing import List, Optional

from django.db import connection
from django.db.models import Avg, Max, Q, Sum
from django.utils import timezone

from main.constants import RATINGS_WINDOW
from main.models import History, Rating, Song

logger = logging.getLogger(__name__)

RATINGS_PER_PLAY = 5


def get_recent_songs_from_history() -> List[Song]:
    """Get recent histories of last half hour, limited to 10."""
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
    logger.info(f'Get match: is rated {current_song.count_rated} < {rate_count_cut_off}')
    if current_song.count_rated > rate_count_cut_off:
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
    logger.info(f'Could not find any match for {song_ids}')


def set_match_result(winner_id: int, loser_ids: List[int]):
    """Set winner against the losers."""
    winner = Song.objects.get(id=winner_id)
    songs = {winner}
    for loser_id in loser_ids:
        if loser_id == winner_id:
            continue
        loser = Song.objects.get(id=loser_id)
        rating = Rating.objects.create(winner=winner, loser=loser, rated_at=timezone.now())
        logger.info(f'Created rating: {rating}')
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
    for album in albums:
        album.count_rated = album.songs.aggregate(Sum('count_rated'))['count_rated__sum']
        album.rated_at = album.songs.aggregate(Max('rated_at'))['rated_at__max']
        album.rating = album.songs.aggregate(Avg('rating'))['rating__avg']
        album.save()
        artists.add(album.artist)

    for artist in artists:
        artist.count_rated = artist.albums.aggregate(Sum('count_rated'))['count_rated__sum']
        artist.rated_at = artist.albums.aggregate(Max('rated_at'))['rated_at__max']
        artist.rating = artist.songs.aggregate(Avg('rating'))['rating__avg']
        artist.save()


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
