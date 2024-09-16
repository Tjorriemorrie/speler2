from django.db import models


class SongManager(models.Manager):
    def get_queryset(self):
        """Always prefetch album and artist."""
        return super().get_queryset().select_related('album', 'artist')
