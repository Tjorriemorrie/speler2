import logging

from django.contrib import admin

from main.models import Album, Artist, Billboard, History, Rating, Song
from main.selectors import upkeep_album, upkeep_artist, upkeep_song

logger = logging.getLogger(__name__)


@admin.register(Artist)
class ArtistAdmin(admin.ModelAdmin):
    list_display = ('name', 'count_albums', 'count_songs', 'rating', 'avg_played_at')
    search_fields = ('name',)


@admin.register(Album)
class AlbumAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'rating', 'artist_name', 'year', 'avg_played_at', 'created_at')
    search_fields = ('name', 'artist__name')

    @admin.display()
    def artist_name(self, album: Album):
        """Get artist name."""
        return album.artist.name


@admin.action(description='Upkeep song stats')
def upkeep_song_act(modeladmin, request, queryset):
    """Upkeep song action."""
    logger.info('Running upkeep song action...')
    for obj in queryset:
        upkeep_song(obj)
        upkeep_album(obj.album)
        upkeep_artist(obj.artist)


@admin.register(Song)
class SongAdmin(admin.ModelAdmin):
    list_display = (
        'pk',
        'name',
        'rating',
        'album_name',
        'artist_name',
        'track_number',
        'count_played',
        'played_at',
        'rel_path',
    )
    search_fields = ('name', 'album__name', 'artist__name')
    actions = [upkeep_song_act]

    @admin.display()
    def album_name(self, song: Song):
        """Get album name."""
        return song.album.name

    @admin.display()
    def artist_name(self, song: Song):
        """Get artist name."""
        return song.artist.name


@admin.register(History)
class HistoryAdmin(admin.ModelAdmin):
    list_display = ('played_at', 'song_id', 'song_name', 'album_name', 'artist_name')
    search_fields = (
        'song__id',
        'song__name',
        'song__album__name',
        'song__artist__name',
    )
    ordering = ('song__artist__name', 'song__album__name', 'song__name')

    @admin.display(description='Song')
    def song_name(self, obj: History):
        """Get song name."""
        return obj.song.name

    @admin.display(description='Album')
    def album_name(self, obj: History):
        """Get album name."""
        return obj.song.album.name if obj.song.album else '-'

    @admin.display(description='Artist')
    def artist_name(self, obj: History):
        """Get artist name."""
        return obj.song.artist.name if obj.song.artist else '-'


@admin.register(Billboard)
class BillboardAdmin(admin.ModelAdmin):
    list_display = (
        'chart',
        'chart_at',
        'artist_name',
        'album_name',
        'pos',
        'last_week',
        'peak_pos',
        'wks_on_chart',
    )


@admin.register(Rating)
class RatingAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'winner_name',
        'winner_artist',
        'loser_name',
        'loser_artist',
        'rated_at',
    )
    search_fields = (
        'winner__name',
        'loser__name',
    )
    list_filter = ('rated_at', 'winner__artist', 'loser__artist')
    ordering = ('-rated_at',)  # newest ratings first

    @admin.display(description='Winner')
    def winner_name(self, obj: Rating):
        """Get winner name."""
        return obj.winner.name

    @admin.display(description='Winner Artist')
    def winner_artist(self, obj: Rating):
        """Get winner artist name."""
        return obj.winner.artist.name if obj.winner.artist else '-'

    @admin.display(description='Loser')
    def loser_name(self, obj: Rating):
        """Get loser name."""
        return obj.loser.name

    @admin.display(description='Loser Artist')
    def loser_artist(self, obj: Rating):
        """Get loser artist name."""
        return obj.loser.artist.name if obj.loser.artist else '-'
