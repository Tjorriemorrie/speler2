from pathlib import Path

from django.conf import settings
from django.core.cache import cache
from django.db import models
from django.utils.http import urlencode
from unidecode import unidecode

from main import managers
from main.constants import BILLBOARD_CHOICES, GENRE_CHOICES, GENRE_HARD_ROCK


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
    total_length = models.FloatField()
    count_played = models.IntegerField(default=0)
    played_at = models.DateTimeField(null=True)
    avg_played_at = models.DateTimeField(null=True)
    count_rated = models.IntegerField(default=0)
    rated_at = models.DateTimeField(null=True)
    rating = models.FloatField(default=0)

    # classification
    genre = models.CharField(max_length=50, choices=GENRE_CHOICES, default=GENRE_HARD_ROCK)
    disco_at = models.DateTimeField(null=True)

    def __str__(self):
        txt = f'<Artist-{self.id} {self.name}>'
        return unidecode(txt)

    @property
    def wiki_link(self) -> str:
        """Get wiki discography search link."""
        params = {'search': f'{self.name.replace("-", "_")}_discography'}
        url = f'https://www.wikipedia.org/w/index.php?{urlencode(params)}'
        return url


class Album(Timestamp, Rank):
    artist = models.ForeignKey(Artist, on_delete=models.CASCADE, related_name='albums')
    name = models.CharField(max_length=150)
    slug = models.SlugField(unique=True)
    year = models.IntegerField()
    total_discs = models.IntegerField()
    total_tracks = models.IntegerField()

    # metadata
    count_songs = models.IntegerField(default=0)
    total_length = models.FloatField()
    count_played = models.IntegerField(default=0)
    played_at = models.DateTimeField(null=True)
    avg_played_at = models.DateTimeField(null=True)
    count_rated = models.IntegerField(default=0)
    rated_at = models.DateTimeField(null=True)
    rating = models.FloatField(default=0)

    # classification
    genre = models.CharField(max_length=50, choices=GENRE_CHOICES, default=GENRE_HARD_ROCK)

    def __str__(self):
        txt = f'<Album-{self.id} {self.name} {self.artist.name}>'
        return unidecode(txt)


class Song(Timestamp, Rank):
    album = models.ForeignKey(Album, on_delete=models.CASCADE, related_name='songs')
    artist = models.ForeignKey(Artist, on_delete=models.CASCADE, related_name='songs')
    rel_path = models.CharField(max_length=255, unique=True)
    slug = models.SlugField(unique=True)
    name = models.CharField(max_length=150)
    disc_number = models.IntegerField()
    track_number = models.IntegerField()
    track_length = models.FloatField()

    # plays
    count_played = models.IntegerField(default=0)
    played_at = models.DateTimeField(null=True)

    # ratings
    count_rated = models.IntegerField(default=0)
    rated_at = models.DateTimeField(null=True)
    rating = models.FloatField(default=0)

    # classification
    genre = models.CharField(max_length=50, choices=GENRE_CHOICES, default=GENRE_HARD_ROCK)

    # managers
    objects = managers.SongManager()

    def __str__(self):
        """Get str."""
        txt = f'<Song-{self.id} {self.name} {self.artist.name}>'
        return unidecode(txt)

    def file_path(self) -> Path:
        """Get audio file path."""
        return settings.MUSIC_DIR / self.rel_path

    def file_exists(self) -> bool:
        """Checks if audio file exists and can be played."""
        return (settings.MUSIC_DIR / self.rel_path).is_file()


class History(Timestamp):
    song = models.ForeignKey(Song, on_delete=models.CASCADE, related_name='histories')
    played_at = models.DateTimeField(null=True)

    class Meta:
        ordering = ['-played_at']

    def __str__(self):
        """Get str."""
        txt = f'<History-{self.id} {self.played_at:%Y-%m-%d} {self.song.name}>'
        return unidecode(txt)


class Rating(Timestamp):
    winner = models.ForeignKey(Song, on_delete=models.CASCADE, related_name='rating_winners')
    loser = models.ForeignKey(Song, on_delete=models.CASCADE, related_name='rating_losers')
    rated_at = models.DateTimeField()

    def __str__(self):
        """Get rating."""
        txt = f'<Rating-{self.id} {self.winner.name} >>> {self.loser.name}>'
        return unidecode(txt)


class Billboard(Timestamp):
    chart = models.CharField(max_length=250, choices=BILLBOARD_CHOICES)
    chart_at = models.DateTimeField()
    pos = models.IntegerField()
    img_src = models.CharField(max_length=250)
    artist_name = models.CharField(max_length=250)
    artist_slug = models.SlugField()
    album_name = models.CharField(max_length=250)
    album_slug = models.SlugField()
    last_week = models.IntegerField(null=True)
    peak_pos = models.IntegerField()
    wks_on_chart = models.IntegerField()

    # meta
    scraped_at = models.DateTimeField()
    finished = models.BooleanField(default=False)

    class Meta:
        unique_together = ['chart', 'artist_slug', 'album_slug']
        ordering = ['chart_at', 'pos']

    def __str__(self):
        txt = f'<Billboard-{self.id} {self.chart} {self.artist_name} {self.album_name}>'
        return unidecode(txt)


class Similar(Timestamp):
    artist = models.ForeignKey(Artist, on_delete=models.CASCADE, related_name='similars')
    artist_name = models.CharField(max_length=250)
    artist_slug = models.SlugField(max_length=250)
    match = models.FloatField()
    rating = models.FloatField()
    score = models.FloatField()
    scraped_at = models.DateTimeField()

    class Meta:
        unique_together = ['artist', 'artist_slug']

    def __str__(self):
        perc = f'{self.score * 100:.0f}%'
        txt = f'<Similar-{self.id} {self.artist.name} => {self.artist_name} {perc}>'
        return unidecode(txt)
