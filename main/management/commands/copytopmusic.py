import logging
import shutil
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from main.constants import GENRE_METAL
from main.models import Song

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Copy top-rated songs up to a given GB limit to EXTERNAL_DIR'

    def add_arguments(self, parser):
        """Add command-line arguments."""
        parser.add_argument(
            '--limit',
            type=float,
            default=32,
            help='Limit in GB (default: 32)',
        )
        parser.add_argument(
            '--no-metal',
            action='store_true',
            help='Exclude metal genre songs',
        )

    def handle(self, *args, **options):
        """Copy top-rated songs to external directory up to size limit."""
        limit_gb = options['limit']
        limit_bytes = limit_gb * (1024**3)
        no_metal = options['no_metal']

        external_dir: Path = settings.EXTERNAL_DIR
        external_dir.mkdir(parents=True, exist_ok=True)

        songs_qs = Song.objects.select_related('artist', 'album').order_by(
            '-count_played', '-rating'
        )
        if no_metal:
            songs_qs = (
                songs_qs.exclude(genre=GENRE_METAL)
                .exclude(artist__genre=GENRE_METAL)
                .exclude(album__genre=GENRE_METAL)
            )

        total_size = 0
        selected = []
        for song in songs_qs.iterator():
            src = song.file_path()
            if not src.is_file():
                logger.warning(f'Missing file: {src}')
                continue

            size = src.stat().st_size
            if total_size + size > limit_bytes:
                logger.info(
                    f'Reached size limit ({total_size / (1024**3):.2f} GB / {limit_gb:.2f} GB)'
                )
                break

            total_size += size
            selected.append(song)

        for song in selected:
            src = song.file_path()

            suffix = src.suffix
            dest_filename = (
                f'{song.artist.name} - {song.album.name} - '
                f'{song.track_number:02d} {song.name}{suffix}'
            )
            dest_filename = _sanitize_filename(dest_filename)
            dest = external_dir / dest_filename

            try:
                shutil.copy2(src, dest)
            except Exception as e:
                logger.error(f'Failed to copy {src}: {e}')
                continue

            logger.info(f'Copied {dest_filename}')

        logger.info(
            f'✅ Copied {len(selected)} songs, '
            f'total {(total_size / (1024**3)):.2f} GB to {external_dir}'
        )


def _sanitize_filename(name: str) -> str:
    """Replace characters that are invalid in filenames on Windows/other FS."""
    invalid = '<>:"/\\|?*'
    for ch in invalid:
        name = name.replace(ch, '_')
    return name
