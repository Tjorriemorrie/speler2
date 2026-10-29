import logging
from typing import Any, Optional, Type

from django.db.models import Model, Q
from django.db.models.signals import post_delete
from django.dispatch import receiver

from main.models import Album, Artist, History, Rating, Song

logger = logging.getLogger(__name__)


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
