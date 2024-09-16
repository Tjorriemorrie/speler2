import logging
from datetime import timedelta
from itertools import combinations
from typing import List, Optional, Set

from django.db.models import Avg, Max, Q, Sum
from django.utils import timezone

from main.models import History, Rating, Song

logger = logging.getLogger(__name__)


def get_recent_songs_from_history() -> Set[Song]:
    """Get recent histories of last half hour, limited to 10."""
    hour_ago = timezone.now() - timedelta(minutes=30)
    histories = History.objects.prefetch_related('song').filter(played_at__gte=hour_ago).all()
    songs = set([h.song for h in histories])
    return songs[:5]


def get_match() -> Optional[List[Song]]:
    """Get next match."""
    songs = get_recent_songs_from_history()
    song_ids = [s.id for s in songs]

    # Filter ratings for the relevant song pairs
    ratings = Rating.objects.filter(
        Q(winner_id__in=song_ids) & Q(loser_id__in=song_ids)
    ).values_list('winner_id', 'loser_id')

    # Convert ratings to a set for faster lookup
    rated_pairs = set()
    for winner, loser in ratings:
        rated_pairs.add((winner, loser))
        rated_pairs.add((loser, winner))  # Add reverse pair for bidirectional check

    # Find combinations of songs that have no ratings between them
    for a, b, c in combinations(songs, 3):
        comb_ids = {a.id, b.id, c.id}
        # Check if any pair in comb_ids has been rated
        if not any((winner in comb_ids and loser in comb_ids) for winner, loser in rated_pairs):
            match = [a, b, c]
            logger.info(f'Found match: {match}')
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
