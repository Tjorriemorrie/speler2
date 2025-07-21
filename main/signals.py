import logging
from typing import Any, Optional, Type

from django.db.models import Model
from django.db.models.signals import post_delete
from django.dispatch import receiver

from main.models import History, Rating, Song

logger = logging.getLogger(__name__)


@receiver(post_delete, sender=Rating)
def mark_surviving_song_dirty(
    sender: Type[Model], instance: Rating, using: Optional[str], **kwargs: Any
) -> None:
    """Mark surviving song dirty."""
    # Check if the winner still exists
    try:
        winner = Song.objects.get(id=instance.winner_id)
        winner.is_dirty = True
        winner.save(update_fields=['is_dirty'])
        logger.info(f'Marked {winner} as dirty')
    except Song.DoesNotExist:
        pass

    # Check if the loser still exists
    try:
        loser = Song.objects.get(id=instance.loser_id)
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
            song: Song = Song.objects.get(id=instance.song_id)
            song.is_dirty = True
            song.save(update_fields=['is_dirty'])
            logger.info(f'Marked {song} as dirty')
        except Song.DoesNotExist:
            pass
