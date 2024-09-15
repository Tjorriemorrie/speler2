from django.db import models


class Timestamp(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Artist(Timestamp):
    name = models.CharField(max_length=50, unique=True)
    slug = models.SlugField(unique=True)
    count_songs = models.IntegerField(default=0)
    count_albums = models.IntegerField(default=0)
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
    disc_number = models.IntegerField(default=1)
    total_discs = models.IntegerField(default=1)
    total_tracks = models.IntegerField(default=0)
    count_songs = models.IntegerField(default=0)
    count_played = models.IntegerField(default=0)
    played_at = models.DateTimeField(null=True)
    count_rated = models.IntegerField(default=0)
    rated_at = models.DateTimeField(null=True)
    rating = models.FloatField(default=1)


class Song(Timestamp):
    album = models.ForeignKey(Album, on_delete=models.CASCADE, related_name='songs')
    file_path = models.CharField(max_length=255, unique=True)
    # web_path = models.CharField(max_length=255, unique=True)
    # path_name = models.CharField(max_length=255, unique=True)

    # info
    id3_parsed = models.BooleanField(default=False)
    name = models.CharField(max_length=50)
    track_number = models.IntegerField()

    # plays
    count_played = models.IntegerField(default=0)
    played_at = models.DateTimeField(null=True)

    # ratings
    rated_at = models.DateTimeField(null=True)
    count_rated = models.IntegerField(default=0)
    rating = models.FloatField(default=1)

    # similars
    # similars = models.relationship('Similar', backref='song', cascade="all,delete-orphan")


#     def __init__(self, path):
#         self.abs_path = path
#         self.web_path = path[9:]
#         self.path_name = self.web_path[len('/static/music/'):]
#         self.similar = []
#
#     @hybrid_property
#     def time_since_played(self):
#         return (datetime.datetime.now() - self.played_at).days
#
#     @time_since_played.expression
#     def time_since_played(cls):
#         return db.func.cast(
#             db.func.extract(db.text('DAY'), db.func.now() - cls.played_at),
#             db.Float)
#
#     @hybrid_property
#     def max_played(self):
#         return max(self.count_played, 1)
#
#     @max_played.expression
#     def max_played(cls):
#         return db.func.cast(
#             db.select([
#                 db.func.greatest(db.func.max(cls.count_played), 1)
#             ]).label('max_played'),
#             db.Float)
#
#     @hybrid_property
#     def priority(self):
#         return self.rating - (
#             self.count_played / self.max_played
#         ) + (
#             self.time_since_played / app.config['AVG_DAYS_LAST_PLAYED']
#         )
#
#     @priority.expression
#     def priority(cls):
#         return cls.rating - (cls.count_played / cls.max_played) + (
#         cls.time_since_played / app.config['AVG_DAYS_LAST_PLAYED'])
#
#     def __json__(self):
#         return [
#             'id', 'path_name', 'web_path',
#             'name', 'track_number',
#             'count_played', 'count_rated', 'rating',
#             'priority', 'played_at',
#             'artist', 'album'
#         ]
#
#     def __repr__(self):
#         return '<{} {}>'.format(self.__class__.__name__, self.id)
#
#     def __str__(self):
#         return '{} - {} - {}'.format(
#             self.artist and self.artist.name or 'arty',
#             self.album and self.album.name or 'alby',
#             self.name)


# class Queue(Timestamp):
#     song = models.ForeignKey(Song, on_delete=models.CASCADE, related_name='queue')
#     src = models.Column(models.String(255), nullable=False)


class History(Timestamp):
    song = models.ForeignKey(Song, on_delete=models.CASCADE, related_name='histories')
    played_at = models.DateTimeField(null=True)


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
