from django.contrib import admin

from main.models import Album, Artist, History, Song


@admin.register(Artist)
class ArtistAdmin(admin.ModelAdmin):
    list_display = ('name', 'count_albums', 'count_songs', 'rating')
    search_fields = ('name',)


@admin.register(Album)
class AlbumAdmin(admin.ModelAdmin):
    list_display = ('name', 'rating', 'artist_name', 'year')
    search_fields = ('name', 'artist__name')

    @admin.display()
    def artist_name(self, album: Album):
        """Get artist name."""
        return album.artist.name


@admin.register(Song)
class SongAdmin(admin.ModelAdmin):
    list_display = (
        'name',
        'rating',
        'album_name',
        'artist_name',
        'track_number',
        'count_played',
        'played_at',
    )
    search_fields = ('name', 'album__name', 'album_artist_name')

    @admin.display()
    def album_name(self, song: Song):
        """Get album name."""
        return song.album.name

    @admin.display()
    def artist_name(self, song: Song):
        """Get artist name."""
        return song.album.artist.name


@admin.register(History)
class HistoryAdmin(admin.ModelAdmin):
    list_display = ('played_at', 'song_name')

    @admin.display()
    def song_name(self, history: History):
        """Get song name."""
        return history.song.name
