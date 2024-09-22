import logging
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.utils.text import slugify
from mutagen import id3, mp3, mp4

from main.models import Album, Artist, Song

logger = logging.getLogger(__name__)


def scan_directory(*args, **kwargs):
    """Scan directory."""
    validate_songs()

    logger.info(f'Scanning {settings.MUSIC_DIR}')

    patterns = []
    if settings.USE_MP3:
        patterns.append('*.mp3')
    if not patterns:
        raise ValueError('Require at least one pattern. Recommend USE_MP3')

    existing_slugs = Song.objects.values_list('slug', flat=True)
    logger.info(f'Checking music path against {len(existing_slugs)} existing paths.')

    # find new files
    albums = set()
    for pattern in patterns:
        logger.info(f'Checking files: {pattern}')
        cnt = 0
        for file_path in settings.MUSIC_DIR.rglob(pattern):
            if not file_path.is_file():
                continue
            cnt += 1
            rel_path = file_path.relative_to(settings.MUSIC_DIR).as_posix()
            slug = slugify(rel_path)
            if slug not in existing_slugs:
                song = add_new_audio_file(file_path, rel_path, slug)
                albums.add(song.album)
        logger.info(f'Found {cnt} {pattern} files in directory')

    # update album and artist stats
    artists = set()
    for album in albums:
        album.count_songs = album.songs.count()
        album.save()
        artists.add(album.artist)
        logger.info(f'Updated album {album.name}: count_songs={album.count_songs}')
    for artist in artists:
        artist.count_albums = artist.albums.count()
        artist.count_songs = artist.songs.count()
        logger.info(
            f'Updated artist {artist.name}: '
            f'count_albums={artist.count_albums} count_songs={artist.count_songs}'
        )
        artist.save()


def add_new_audio_file(file_path: Path, rel_path: str, song_slug: str) -> Song:
    """Add new Artist, Album and Song after parsing ID3 metadata."""
    logger.info(f'Adding new {file_path}')
    metadata = parse_id3_tag(file_path.resolve())

    artist_slug = slugify(metadata['artist_name'])
    artist, artist_created = Artist.objects.update_or_create(
        slug=artist_slug,
        defaults={
            'name': metadata['artist_name'],
        },
    )
    if artist_created:
        logger.info(f'Created {artist}')

    album_slug = artist_slug + '-' + slugify(metadata['album_name'])
    album, album_created = Album.objects.update_or_create(
        slug=album_slug,
        defaults={
            'artist': artist,
            'name': metadata['album_name'],
            'year': metadata['year'],
            'total_tracks': metadata['total_tracks'],
            'total_discs': metadata['total_discs'],
        },
    )
    if album_created:
        logger.info(f'Created {album_created}')

    song = Song.objects.create(
        artist=artist,
        album=album,
        rel_path=rel_path,
        slug=song_slug,
        name=metadata['song_title'],
        disc_number=metadata['disc_number'],
        track_number=metadata['track_number'],
    )
    logger.info(f'Created {song}')

    return song


def parse_id3_tag(file_path: str) -> dict:
    """Get metadata based on file type."""
    logger.info(f'Parsing ID3 tag for {file_path}')
    if file_path.suffix == '.mp3':
        metadata = get_mp3_metadata(file_path)
    elif file_path.suffix == '.m4a':
        metadata = get_m4a_metadata(file_path)
    else:
        raise NotImplementedError(f'Unsupported file extension for {file_path}')
    logger.info(f'Parsed metadata: {metadata}')
    return metadata


def get_mp3_metadata(file_path: str) -> dict:
    """Extract metadata from MP3 files."""
    info = {}

    # Access audio properties
    audio = mp3.MP3('path/to/your/file.mp3')
    info['track_length'] = audio.info.length

    # Access id3 properties
    meta = id3.ID3(file_path)
    info['song_title'] = str(meta['TIT2'])
    track_info = str(meta['TRCK'])
    info['track_number'], info['total_tracks'] = (
        map(int, track_info.split('/')) if '/' in track_info else (int(track_info), None)
    )
    info['artist_name'] = str(meta['TPE1'])
    info['album_name'] = str(meta['TALB'])
    tpos = str(meta['TPOS']).split('/')
    info['disc_number'] = int(tpos[0])
    info['total_discs'] = int(tpos[1]) if len(tpos) > 1 else 1
    info['year'] = int(str(meta['TDRC'])[:4])

    return info


def get_m4a_metadata(file_path) -> dict:
    """Extract metadata from M4A files."""
    info = {}
    meta = mp4.MP4(file_path)
    info['song_title'] = meta.get('\xa9nam', ['Unknown Title'])[0]
    info['track_number'] = int(meta.get('trkn', [(1, 1)])[0][0])
    info['total_tracks'] = int(meta.get('trkn', [(1, 1)])[0][1])
    info['artist_name'] = meta.get('\xa9ART', ['Unknown Artist'])[0]
    info['album_name'] = meta.get('\xa9alb', ['Unknown Album'])[0]
    disk_info = meta.get('disk', [(1, 1)])
    info['disc_number'] = int(disk_info[0][0])
    info['total_discs'] = int(disk_info[0][1])
    info['year'] = int(meta.get('\xa9day', ['0000'])[0])
    return info


def validate_songs():
    """Ensure songs in db has files."""
    logger.info('Validating songs...')
    songs = Song.objects.all()

    with transaction.atomic():
        for song in songs:
            if not song.file_exists():
                logger.info(f'Removing bad song {song}')
                song.delete()

        # Remove albums with no songs left
        albums = Album.objects.all()
        for album in albums:
            if not album.songs.exists():
                logger.info(f'Removing album {album} with no songs')
                album.delete()

        # Remove artists with no albums left
        artists = Artist.objects.all()
        for artist in artists:
            if not artist.albums.exists():
                logger.info(f'Removing artist {artist} with no albums')
                artist.delete()


def get_album_art(song: Song):
    """Get album art from metadata."""
    file_path = settings.MUSIC_DIR / song.rel_path
    audio_file = mp3.MP3(file_path, ID3=id3.ID3)
    for tag in audio_file.tags.values():
        if tag.FrameID == 'APIC':  # APIC frame stores album artwork
            return tag
