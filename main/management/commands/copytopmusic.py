import logging
import random
import shutil
from pathlib import Path
from statistics import mean

from django.conf import settings
from django.core.management.base import BaseCommand

from main.models import Artist

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

    def handle(self, *args, **options):
        """Copy top-rated songs to external directory up to size limit."""
        limit_gb = options['limit']
        limit_bytes = limit_gb * (1024**3)

        external_dir: Path = settings.EXTERNAL_DIR
        external_dir.mkdir(parents=True, exist_ok=True)

        total_size = 0
        has_space = True

        selected = []
        i = 0
        rating_cutoff = 0
        while has_space:
            ratings = []
            added = 0
            for artist in Artist.objects.all():
                song = artist.songs.order_by('-rating', '-count_played')[i]
                if song.rating > rating_cutoff:
                    src = song.file_path()
                    if not src.is_file():
                        logger.warning(f'Missing file: {src}')
                        continue

                    size = src.stat().st_size
                    if total_size + size > limit_bytes:
                        logger.info(
                            f'Reached size limit '
                            f'({total_size / (1024 ** 3):.2f} GB / {limit_gb:.2f} GB)'
                        )
                        has_space = False
                        break

                    total_size += size
                    ratings.append(song.rating)
                    selected.append(song)
                    added += 1
                    # logger.info(f'Added {i + 1}: {song}')

            logger.info(
                f'Added {added} songs at iteration {i} with rating cutoff {rating_cutoff:.2f}'
            )

            # adjust rating cutoff for next song for each artist
            cut_off = 10
            if len(ratings) < cut_off:
                logger.info('Not enough songs to continue selection.')
                break
            rating_cutoff = mean(ratings)
            i += 1

        random.shuffle(selected)
        for idx, song in enumerate(selected, start=1):
            src = song.file_path()

            prefix = str(idx).zfill(3)  # "001", "002", etc.
            dest_filename = f'{prefix}_{src.name}'
            dest = external_dir / dest_filename

            try:
                shutil.copy2(src, dest)
            except Exception as e:
                logger.error(f'Failed to copy {src}: {e}')
                continue

            logger.info(f'Copied {dest_filename}')

        logger.info(
            f'✅ Copied {len(selected)} songs, '
            f'total {(total_size / (1024 ** 3)):.2f} GB to {external_dir}'
        )
