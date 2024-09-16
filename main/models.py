from django.db import models

from main import managers


class Timestamp(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Artist(Timestamp):
    name = models.CharField(max_length=50, unique=True)
    slug = models.SlugField(unique=True)

    count_albums = models.IntegerField(default=0)
    count_songs = models.IntegerField(default=0)
    count_played = models.IntegerField(default=0)
    played_at = models.DateTimeField(null=True)
    count_rated = models.IntegerField(default=0)
    rated_at = models.DateTimeField(null=True)
    rating = models.FloatField(default=1)


class Album(Timestamp):
    artist = models.ForeignKey(Artist, on_delete=models.CASCADE, related_name='albums')
    name = models.CharField(max_length=50, unique=True)
    slug = models.SlugField(unique=True)
    year = models.IntegerField()
    disc_number = models.IntegerField()
    total_discs = models.IntegerField()
    total_tracks = models.IntegerField()

    count_songs = models.IntegerField(default=0)
    count_played = models.IntegerField(default=0)
    played_at = models.DateTimeField(null=True)
    count_rated = models.IntegerField(default=0)
    rated_at = models.DateTimeField(null=True)
    rating = models.FloatField(default=1)


class Song(Timestamp):
    album = models.ForeignKey(Album, on_delete=models.CASCADE, related_name='songs')
    artist = models.ForeignKey(Artist, on_delete=models.CASCADE, related_name='songs')
    rel_path = models.CharField(max_length=255, unique=True)
    slug = models.SlugField(unique=True)
    name = models.CharField(max_length=50)
    track_number = models.IntegerField()

    # plays
    count_played = models.IntegerField(default=0)
    played_at = models.DateTimeField(null=True)

    # ratings
    count_rated = models.IntegerField(default=0)
    rated_at = models.DateTimeField(null=True)
    rating = models.FloatField(default=1)

    # managers
    objects = managers.SongManager()


class History(Timestamp):
    song = models.ForeignKey(Song, on_delete=models.CASCADE, related_name='histories')
    played_at = models.DateTimeField(null=True)

    class Meta:
        ordering = ['-played_at']


class Rating(Timestamp):
    winner = models.ForeignKey(Song, on_delete=models.CASCADE, related_name='rating_winners')
    loser = models.ForeignKey(Song, on_delete=models.CASCADE, related_name='rating_losers')
    rated_at = models.DateTimeField()


# class Similar(db.Model):
#     id = db.Column(db.Integer, primary_key=True)
#     song_id = db.Column(db.Integer, db.ForeignKey('song.id'))
#     artist_name = db.Column(db.String(255))
#     album_name = db.Column(db.String(255))
#     track_name = db.Column(db.String(255))
#     similarity = db.Column(db.Float)
#     scraped_at = db.Column(db.DateTime, server_default=db.func.now())
#
#     @property
#     def key(self):
#         return '{}_{}'.format(self.artist_name, self.album_name)
#
#     def __repr__(self):
#         return '<{} {} {} {}>'.format(
#             self.__class__.__name__, self.id, self.artist_name, self.album_name)
