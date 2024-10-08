# Generated by Django 5.1.1 on 2024-09-22 10:50

from django.db import migrations, models


def update_song_lengths(apps, schema_editor):
    """Store song length."""
    from pathlib import Path

    from django.conf import settings
    from django.db.models import Sum
    from mutagen import MutagenError, mp3

    # Load the Song model
    Song = apps.get_model('main', 'Song')
    Album = apps.get_model('main', 'Album')
    Artist = apps.get_model('main', 'Artist')

    # Iterate over all songs
    for song in Song.objects.all():
        # Get the file path for the song
        file_path = Path(settings.MUSIC_DIR) / song.rel_path

        # Ensure the file exists
        if file_path.is_file():
            # Use mutagen to get the track length
            try:
                audio = mp3.MP3(file_path)
                song.track_length = audio.info.length
                song.save()
            except MutagenError as e:
                print(f'Error processing {file_path}: {e}')
        else:
            print(f'File not found for song {song.name}: {file_path}')

    for album in Album.objects.all():
        album.total_length = album.songs.aggregate(Sum('track_length'))['track_length__sum']
        album.save()

    for artist in Artist.objects.all():
        artist.total_length = artist.albums.aggregate(Sum('total_length'))['total_length__sum']
        artist.save()


class Migration(migrations.Migration):
    dependencies = [
        ('main', '0005_alter_album_name_alter_artist_name_alter_song_name'),
    ]

    operations = [
        migrations.AddField(
            model_name='album',
            name='total_length',
            field=models.FloatField(default=0),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='artist',
            name='total_length',
            field=models.FloatField(default=0),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='song',
            name='track_length',
            field=models.FloatField(default=0),
            preserve_default=False,
        ),
        migrations.RunPython(update_song_lengths),
    ]
