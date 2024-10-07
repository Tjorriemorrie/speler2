import logging

import django_filters
from django.db.models import Case, IntegerField, Q, QuerySet, When

from main.models import Song

logger = logging.getLogger(__name__)


class SongFilter(django_filters.FilterSet):
    query = django_filters.CharFilter(label='', method='universal_search')

    class Meta:
        model = Song
        fields = ['query']

    def universal_search(self, queryset: QuerySet[Song], name: str, value: str):
        """Universal search."""
        # Create Q objects for filtering
        name_match = Q(name__icontains=value)
        album_match = Q(album__name__icontains=value)
        artist_match = Q(artist__name__icontains=value)

        # Annotate the queryset with weights
        queryset = queryset.annotate(
            relevance=Case(
                When(name_match, then=3),  # Highest weight for name matches
                When(album_match, then=2),  # Lower weight for album matches
                When(artist_match, then=1),  # Lowest weight for artist matches
                default=0,
                output_field=IntegerField(),
            )
        )

        # Order by relevance in descending order
        return queryset.filter(name_match | album_match | artist_match).order_by('-relevance')
