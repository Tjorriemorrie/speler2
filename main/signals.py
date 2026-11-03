import logging
import time
from typing import Any, Optional, Type

from django.db import OperationalError
from django.db.backends.signals import connection_created
from django.db.models import Model, Q
from django.db.models.signals import post_delete
from django.dispatch import receiver

from main.models import Album, Artist, History, Rating, Song

logger = logging.getLogger(__name__)

LOCKED_RETRY_DELAY = 1


def retry_locked(execute, sql, params, many, context):
    """Retry a statement for as long as the database is locked by another writer.

    Only outside a transaction: inside one this connection may hold the lock the other writer
    waits on, and the statement alone can't be rerun.
    """
    attempt = 0
    while True:
        try:
            return execute(sql, params, many, context)
        except OperationalError as exc:
            if 'database is locked' not in str(exc) or context['connection'].in_atomic_block:
                raise
            attempt += 1
            logger.warning(f'🔒 Database locked, retrying: attempt={attempt}, sql={sql[:60]}')
            time.sleep(LOCKED_RETRY_DELAY)


@receiver(connection_created)
def install_retry_locked(sender: Any, connection: Any, **kwargs: Any) -> None:
    """Every connection retries "database is locked" instead of crashing."""
    connection.execute_wrappers.append(retry_locked)


@receiver(post_delete, sender=Song)
def mark_album_dirty_on_song_delete(
    sender: Type[Model], instance: Song, using: Optional[str], **kwargs: Any
) -> None:
    """Mark the song's album dirty, so cleanstats recounts it (and in turn its artist)."""
    marked = Album.objects.filter(id=instance.album_id).update(is_dirty=True)
    logger.info(
        f'🗑️ Song deleted, album marked dirty: song_id={instance.id}, '
        f'album_id={instance.album_id}, marked={marked}'
    )


@receiver(post_delete, sender=Album)
def mark_artist_dirty_on_album_delete(
    sender: Type[Model], instance: Album, using: Optional[str], **kwargs: Any
) -> None:
    """Mark the album's artist dirty, so cleanstats recounts it."""
    marked = Artist.objects.filter(id=instance.artist_id).update(is_dirty=True)
    logger.info(
        f'🗑️ Album deleted, artist marked dirty: album_id={instance.id}, '
        f'artist_id={instance.artist_id}, marked={marked}'
    )


@receiver(post_delete, sender=Rating)
def mark_surviving_song_dirty(
    sender: Type[Model], instance: Rating, using: Optional[str], **kwargs: Any
) -> None:
    """Mark surviving song dirty."""
    # Check if the winner still exists
    try:
        winner = Song.objects.get(id=instance.winner_id)
        if not winner.is_dirty:
            winner.is_dirty = True
            winner.save(update_fields=['is_dirty'])
            logger.info(f'Marked {winner} as dirty')
    except Song.DoesNotExist:
        pass

    # Check if the loser still exists
    try:
        loser = Song.objects.get(id=instance.loser_id)
        if not loser.is_dirty:
            loser.is_dirty = True
            loser.save(update_fields=['is_dirty'])
            logger.info(f'Marked {loser} as dirty')
    except Song.DoesNotExist:
        pass


@receiver(post_delete, sender=History)
def mark_song_dirty_on_history_delete(
    sender: Type[Model], instance: History, using: Optional[str], **kwargs: Any
) -> None:
    """Mark the related Song as dirty when a History is deleted.

    Unless the Song was also deleted (i.e. via cascading).
    """
    if instance.song_id:
        try:
            log_msg = ''
            song: Song = Song.objects.get(id=instance.song_id)
            if not song.is_dirty:
                song.is_dirty = True
                song.save(update_fields=['is_dirty'])
                log_msg = f'Marked {song} as dirty'

            # delete ratings involving this song before the deleted history timestamp
            cnt, _ = (
                Rating.objects.filter(rated_at__lt=instance.played_at)
                .filter(Q(winner=song) | Q(loser=song))
                .delete()
            )

            if log_msg:
                if cnt:
                    log_msg += f' (removed {cnt} ratings)'
                logger.info(log_msg)

        except Song.DoesNotExist:
            pass
