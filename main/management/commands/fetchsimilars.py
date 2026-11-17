import logging
import time

from django.core.management.base import BaseCommand

from main.similars import get_similars_progress, has_unfetched_seeds, update_next_similar_song

logger = logging.getLogger(__name__)

# a failed seed stays first in line, so this many failures in a row is an outage
MAX_FAILURES_IN_A_ROW = 5
FAILURE_PAUSE_SECONDS = 30


class Command(BaseCommand):
    help = 'Fetches the similar songs of every seed song not fetched yet. Safe to rerun.'

    def handle(self, *args, **options):
        """Fetch until every seed is done or last.fm keeps failing."""
        failures = 0
        while failures < MAX_FAILURES_IN_A_ROW and has_unfetched_seeds():
            if update_next_similar_song():
                failures = 0
                continue
            failures += 1
            logger.warning(f'⚠️ Similar songs fetch failed: failures_in_a_row={failures}')
            time.sleep(FAILURE_PAUSE_SECONDS)
        self.stdout.write(f'Similar songs: failures={failures}, {get_similars_progress()}')
