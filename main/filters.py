import logging

import django_filters
from django.db.models import Case, IntegerField, Q, QuerySet, When

from main.models import Album, Song

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


class AlbumFilter(django_filters.FilterSet):
    query = django_filters.CharFilter(label='', method='universal_search')

    class Meta:
        model = Album
        fields = ['query']

    def universal_search(self, queryset: QuerySet[Album], name: str, value: str):
        """Universal search."""
        # Create Q objects for filtering
        name_match = Q(name__icontains=value)
        artist_match = Q(artist__name__icontains=value)

        # Initialize year_match as None
        year_match = None
        try:
            # Check if the value is a valid year (integer)
            year_value = int(value)
            year_match = Q(year=year_value)
        except ValueError:
            pass  # If not a valid year, we don't use the year condition

        # Annotate the queryset with weights
        conditions = [
            When(name_match, then=3),  # Highest weight for name matches
            When(artist_match, then=2),  # Lower weight for artist matches
        ]
        if year_match:
            conditions.append(When(year_match, then=1))  # Add year condition if valid

        queryset = queryset.annotate(
            relevance=Case(
                *conditions,
                default=0,
                output_field=IntegerField(),
            )
        )

        # Filter by the applicable Q objects and order by relevance in descending order
        final_filter = name_match | artist_match
        if year_match:
            final_filter |= year_match

        return queryset.filter(final_filter).order_by('-relevance')


class ArtistFilter(django_filters.FilterSet):
    query = django_filters.CharFilter(label='', method='universal_search')

    class Meta:
        model = Album
        fields = ['query']

    def universal_search(self, queryset: QuerySet[Album], name: str, value: str):
        """Universal search."""
        return queryset.filter(name__icontains=value)
