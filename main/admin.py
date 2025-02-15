import logging

from django.contrib import admin

from main.models import Album, Artist, Billboard, History, Song
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
    list_display = ('played_at', 'song__id', 'song_name')
    search_fields = ('song__id',)

    @admin.display()
    def song_name(self, history: History):
        """Get song name."""
        return history.song.name


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
