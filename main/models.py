from django.core.cache import cache
from django.db import models

from main import managers


class Timestamp(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Rank:
    @property
    def rank(self):
        """Get item rank."""
        # Create a cache key based on the instance's class and primary key
        cache_key = f'{self.__class__.__name__}_rank_{self.pk}'
        rank = cache.get(cache_key)

        if rank is None:
            # Use self.__class__.objects to access the manager at the class level
            rank = self.__class__.objects.filter(rating__gt=self.rating).count() + 1
            cache.set(cache_key, rank, timeout=3600)  # Cache for 1 hour

        return rank


class Artist(Timestamp, Rank):
    name = models.CharField(max_length=150, unique=True)
    slug = models.SlugField(unique=True)

    count_albums = models.IntegerField(default=0)
    count_songs = models.IntegerField(default=0)
    count_played = models.IntegerField(default=0)
    played_at = models.DateTimeField(null=True)
    count_rated = models.IntegerField(default=0)
    rated_at = models.DateTimeField(null=True)
    rating = models.FloatField(default=0)


class Album(Timestamp, Rank):
    artist = models.ForeignKey(Artist, on_delete=models.CASCADE, related_name='albums')
    name = models.CharField(max_length=150)
    slug = models.SlugField(unique=True)
    year = models.IntegerField()
    total_discs = models.IntegerField()
    total_tracks = models.IntegerField()

    count_songs = models.IntegerField(default=0)
    count_played = models.IntegerField(default=0)
    played_at = models.DateTimeField(null=True)
    count_rated = models.IntegerField(default=0)
    rated_at = models.DateTimeField(null=True)
    rating = models.FloatField(default=0)


class Song(Timestamp, Rank):
    album = models.ForeignKey(Album, on_delete=models.CASCADE, related_name='songs')
    artist = models.ForeignKey(Artist, on_delete=models.CASCADE, related_name='songs')
    rel_path = models.CharField(max_length=255, unique=True)
    slug = models.SlugField(unique=True)
    name = models.CharField(max_length=150)
    disc_number = models.IntegerField()
    track_number = models.IntegerField()

    # plays
    count_played = models.IntegerField(default=0)
    played_at = models.DateTimeField(null=True)

    # ratings
    count_rated = models.IntegerField(default=0)
    rated_at = models.DateTimeField(null=True)
    rating = models.FloatField(default=0)

    # managers
    objects = managers.SongManager()

    def __str__(self):
        return f'<Song-{self.id} {self.name} {self.artist.name}>'


class History(Timestamp):
    song = models.ForeignKey(Song, on_delete=models.CASCADE, related_name='histories')
    played_at = models.DateTimeField(null=True)

    class Meta:
        ordering = ['-played_at']

    def __str__(self):
        return f'<History-{self.id} {self.played_at:%Y-%m-%d} {self.song.name}>'


class Rating(Timestamp):
    winner = models.ForeignKey(Song, on_delete=models.CASCADE, related_name='rating_winners')
    loser = models.ForeignKey(Song, on_delete=models.CASCADE, related_name='rating_losers')
    rated_at = models.DateTimeField()
