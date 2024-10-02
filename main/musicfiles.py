import logging
from datetime import datetime
from pathlib import Path
from typing import List

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Avg, FloatField, Max, Sum
from django.db.models.functions import Cast
from django.utils.text import slugify
from django.utils.timezone import make_aware
from mutagen import id3, mp3, mp4
from unidecode import unidecode

from main.models import Album, Artist, Song

logger = logging.getLogger(__name__)


def scan_directory(*args, **kwargs):
    """Scan directory."""
    missing_audio_songs = validate_songs(delete=False)

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
            slug = slugify(unidecode(rel_path))
            if slug not in existing_slugs:
                song = add_new_audio_file(file_path, rel_path, slug, missing_audio_songs)
                albums.add(song.album)
        logger.info(f'Found {cnt} {pattern} files in directory')

    # update album and artist stats
    artists = set()
    for album in albums:
        album.count_songs = album.songs.count()
        album.total_length = album.songs.aggregate(Sum('track_length'))['track_length__sum']
        album.save()
        artists.add(album.artist)
        logger.info(f'Updated album {album.name}: count_songs={album.count_songs}')
    for artist in artists:
        artist.count_albums = artist.albums.count()
        artist.count_songs = artist.songs.count()
        artist.total_length = artist.albums.aggregate(Sum('total_length'))['total_length__sum']
        logger.info(
            f'Updated artist {artist.name}: '
            f'count_albums={artist.count_albums} count_songs={artist.count_songs}'
        )
        artist.save()

    validate_songs()


def add_new_audio_file(
    file_path: Path, rel_path: str, song_slug: str, missing_audio_files: List[Song]
) -> Song:
    """Add new Artist, Album and Song after parsing ID3 metadata."""
    logger.info(f'Adding new {file_path}')
    metadata = parse_id3_tag(file_path.resolve())

    # check if song file is renamed
    for bad_song in missing_audio_files:
        same_artist = bad_song.artist.name == metadata['artist_name']
        same_album = bad_song.album.name == metadata['album_name']
        song_name = bad_song.name == metadata['song_title']
        if same_artist and same_album and song_name:
            bad_song.slug = song_slug
            bad_song.rel_path = rel_path
            bad_song.save()
            logger.info(f'Song renamed! {bad_song} now at {rel_path}')
            return bad_song

    artist_slug = slugify(unidecode(metadata['artist_name']))
    artist, artist_created = Artist.objects.update_or_create(
        slug=artist_slug,
        defaults={
            'name': metadata['artist_name'],
            'total_length': 0,
        },
    )
    if artist_created:
        logger.info(f'Created {artist}')

    album_slug = artist_slug + '-' + slugify(unidecode(metadata['album_name']))
    album, album_created = Album.objects.update_or_create(
        slug=album_slug,
        defaults={
            'artist': artist,
            'name': metadata['album_name'],
            'year': metadata['year'],
            'total_tracks': metadata['total_tracks'],
            'total_discs': metadata['total_discs'],
            'total_length': 0,
            'genre': artist.genre,
        },
    )
    if album_created:
        logger.info(f'Created {album_created}')

    try:
        song = Song.objects.create(
            artist=artist,
            album=album,
            rel_path=rel_path,
            slug=song_slug,
            name=metadata['song_title'],
            disc_number=metadata['disc_number'],
            track_number=metadata['track_number'],
            track_length=metadata['track_length'],
            genre=artist.genre,
        )
        logger.info(f'Created {song}')
    except IntegrityError as exc:
        if 'main_song.rel_path' not in str(exc):
            raise
        song = Song.objects.get(rel_path=rel_path)
        song.slug = song_slug
        song.save()
        logger.info(f'Updated song slug to: {song_slug}')

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
    audio = mp3.MP3(file_path)
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


def validate_songs(delete: bool = True) -> List[Song]:
    """Ensure songs in db has files."""
    logger.info('Validating songs...')
    listing = []
    songs = Song.objects.all()

    with transaction.atomic():
        for song in songs:
            if not song.file_exists():
                listing.append(song)
                logger.info(f'{"Removing" if delete else "Found"} bad song {song}')
                if delete:
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

    return listing


def get_album_art(song: Song):
    """Get album art from metadata."""
    file_path = settings.MUSIC_DIR / song.rel_path
    audio_file = mp3.MP3(file_path, ID3=id3.ID3)
    for tag in audio_file.tags.values():
        if tag.FrameID == 'APIC':  # APIC frame stores album artwork
            return tag


def recheck_metadata(*args, **kwargs):  # noqa: PLR0912 PLR0915
    """Checks metadata of songs."""
    outdated_albums = set()
    for song in Song.objects.all():
        metadata = parse_id3_tag(song.file_path().resolve())
        song_dirty = False
        album_dirty = False

        artist_slug = slugify(unidecode(metadata['artist_name']))
        if song.artist.slug != artist_slug:
            # check if existing artist exists since slug is unique
            # then switch to that artist,
            # otherwise it can just be changed
            try:
                existing_artist = Artist.objects.get(slug=artist_slug)
                logger.info(f'Switching artist to {existing_artist} from {song.artist}')
                song.artist = existing_artist
                song_dirty = True
            except Artist.DoesNotExist:
                logger.info(f'Renaming artist to {metadata["artist_name"]} from {song.artist}')
                song.artist.slug = artist_slug
                song.artist.name = metadata['artist_name']
                song.artist.save()

        album_slug = artist_slug + '-' + slugify(unidecode(metadata['album_name']))
        if song.album.slug != album_slug:
            # this will always be different if artist was updated,
            # otherwise the album was changed and not the artist
            try:
                existing_album = Album.objects.get(slug=album_slug)
                logger.info(f'Switching album to {existing_album} from {song.album}')
                song.album = existing_album
                song_dirty = True
            except Album.DoesNotExist:
                logger.info(f'Renaming album to {metadata["album_name"]} from {song.album}')
                song.album.artist = song.artist
                song.album.slug = album_slug
                song.album.name = metadata['album_name']
                album_dirty = True

        # check album metadata
        if song.album.year != metadata['year']:
            song.album.year = metadata['year']
            album_dirty = True

        if song.album.total_tracks != metadata['total_tracks']:
            song.album.total_tracks = metadata['total_tracks']
            album_dirty = True

        if song.album.total_discs != metadata['total_discs']:
            song.album.total_discs = metadata['total_discs']
            album_dirty = True

        if album_dirty:
            logger.info(f'Dirty album: {song.album}')
            song.album.save()

        # check song metadata
        if song.name != metadata['song_title']:
            song.name = metadata['song_title']
            song_dirty = True

        if song.disc_number != metadata['disc_number']:
            song.disc_number = metadata['disc_number']
            song_dirty = True

        if song.track_number != metadata['track_number']:
            song.track_number = metadata['track_number']
            song_dirty = True

        if song.track_length != metadata['track_length']:
            song.track_length = metadata['track_length']
            song_dirty = True

        if song_dirty:
            logger.info(f'Dirty song: {song}')
            song.save()

        if album_dirty or song_dirty:
            outdated_albums.add(song.album)

    # update stats on albums
    outdated_artists = set()
    for album in outdated_albums:
        album.refresh_from_db()
        album.count_songs = album.songs.count()
        album.total_length = album.songs.aggregate(Sum('track_length'))['track_length__sum']
        album.count_played = album.songs.aggregate(Sum('count_played'))['count_played__sum']
        album.played_at = album.songs.aggregate(Max('played_at'))['played_at__max']
        # Convert 'played_at' to a numeric format for averaging
        avg_played_at = album.songs.annotate(
            played_at_timestamp=Cast('played_at', FloatField())
        ).aggregate(Avg('played_at_timestamp'))['played_at_timestamp__avg']
        album.avg_played_at = (
            make_aware(datetime.fromtimestamp(avg_played_at)) if avg_played_at else None
        )
        album.count_rated = album.songs.aggregate(Sum('count_rated'))['count_rated__sum']
        album.rated_at = album.songs.aggregate(Max('rated_at'))['rated_at__max']
        album.rating = album.songs.aggregate(Avg('rating'))['rating__avg']
        album.save()
        logger.info(f'Updated stats for {album}')
        outdated_artists.add(album.artist)

    # update stats on artists
    for artist in outdated_artists:
        artist.refresh_from_db()
        artist.count_albums = artist.albums.count()
        artist.count_songs = artist.songs.count()
        artist.total_length = artist.albums.aggregate(Sum('total_length'))['total_length__sum']
        artist.count_played = artist.albums.aggregate(Sum('count_played'))['count_played__sum']
        artist.played_at = artist.albums.aggregate(Max('played_at'))['played_at__max']
        # Convert 'played_at' to a numeric format for averaging
        avg_played_at = artist.songs.annotate(
            played_at_timestamp=Cast('played_at', FloatField())
        ).aggregate(Avg('played_at_timestamp'))['played_at_timestamp__avg']
        artist.avg_played_at = (
            make_aware(datetime.fromtimestamp(avg_played_at)) if avg_played_at else None
        )
        artist.count_rated = artist.albums.aggregate(Sum('count_rated'))['count_rated__sum']
        artist.rated_at = artist.albums.aggregate(Max('rated_at'))['rated_at__max']
        artist.rating = artist.songs.aggregate(Avg('rating'))['rating__avg']
        logger.info(f'Updated stats for {artist}')
        artist.save()

    # ensure to remove dud artists or albums that could be orphans
    validate_songs()
