import logging
from datetime import datetime

from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.html import format_html
from django_tables2 import Column, tables

from main.models import Album, Artist, Song
from main.templatetags.fmt import days_ago, dur, iconrank, perc

logger = logging.getLogger(__name__)


class SongTable(tables.Table):
    rank = Column(
        initial_sort_descending=True,
        attrs={
            'th': {'class': 'text-muted'},
            'td': {'class': 'text-muted'},
        },
    )
    rating = Column(
        initial_sort_descending=True,
        attrs={
            'th': {'class': 'text-end d-none d-lg-table-cell'},
            'td': {'class': 'text-end d-none d-lg-table-cell text-muted small'},
        },
    )
    iconrank = Column(
        empty_values=(),
        verbose_name='',
        attrs={
            'th': {'class': 'text-start d-none d-lg-table-cell'},
            'td': {'class': 'text-start d-none d-lg-table-cell'},
        },
    )
    name = Column(attrs={'td': {'class': 'ellipsis'}})
    track_length = Column(
        verbose_name='Duration',
        attrs={
            'th': {'class': 'd-none d-xl-table-cell'},
            'td': {'class': 'd-none d-xl-table-cell'},
        },
    )
    count_played = Column(
        initial_sort_descending=True,
        verbose_name='Plays',
        attrs={
            'th': {'class': 'd-none d-lg-table-cell'},
            'td': {'class': 'd-none d-lg-table-cell'},
        },
    )
    played_at = Column(
        initial_sort_descending=True,
        verbose_name='Last Played',
        attrs={
            'th': {'class': 'd-none d-xl-table-cell'},
            'td': {'class': 'd-none d-xl-table-cell'},
        },
    )
    genre = Column(
        attrs={
            'th': {'class': 'd-none d-lg-table-cell'},
            'td': {'class': 'd-none d-lg-table-cell'},
        }
    )

    class Meta:
        model = Song
        fields = (
            'rank',
            'rating',
            'iconrank',
            'name',
            'artist',
            'album',
            'track_length',
            'count_played',
            'played_at',
            'genre',
        )
        template_name = 'main/table_song.html'
        attrs = {
            'class': 'table table-sm table-striped small-font-table table-hover',
            'tbody': {'class': 'table-group-divider'},
        }

    def order_rank(self, queryset, is_descending):
        """Order rank."""
        queryset = queryset.order_by(
            ('-' if is_descending else '') + 'rating',
            ('-' if is_descending else '') + 'count_rated',
            ('-' if is_descending else '') + 'rated_at',
        )
        return queryset, True

    def render_rating(self, value: str, record: Song, column) -> str:
        """Render rating."""
        if record.id == self.request.session.get('song_id'):
            column.attrs['td']['class'] += ' fw-bold'
        else:
            column.attrs['td']['class'] = column.attrs['td']['class'].replace(' fw-bold', '')

        return format_html(
            """
            <span class="text-muted small">{cnt} @</span> {rating}
            """,
            cnt=record.count_rated,
            rating=perc(record.rating, 1),
        )

    def render_iconrank(self, record: Song):
        """Render iconrank."""
        return format_html(iconrank(record.rating, 5, 1, 0))

    def render_name(self, value: str, record: Song) -> str:
        """Render name."""
        return format_html(
            """
            <a class="play-icon"
               href="#"
               hx-get="/next-song/?demand=song_{id}"
               hx-target="#player-container"
               hx-swap="innerHTML">
                <i class="bi bi-play-circle"></i>
            </a>
            <span class="text-muted small track-number">{track_number}</span>
            <span class="song-name">{name}</span>
            """,
            url=reverse('next_song') + f'?demand=song_{record.id}',
            id=record.id,
            track_number=record.track_number,
            name=record.name,
        )

    def render_artist(self, value: Artist, record: Song) -> str:
        """Render artist."""
        return format_html(
            """
            <a class="no-blue" href="#"
               hx-get="{url}"
               hx-trigger="click"
               hx-target="#main-container"
               hx-swap="innerHTML">
                {artist_name}
            </a>
            """,
            url=reverse('artist', kwargs={'artist_id': value.id}),
            artist_name=value.name,
        )

    def order_artist(self, queryset, is_descending):
        """Order artist."""
        queryset = queryset.order_by(
            ('-' if is_descending else '') + 'artist__name', 'album__year', 'track_number'
        )
        return queryset, True

    def render_album(self, value: Album, record: Song):
        """Render album."""
        return format_html(
            """
            <a hx-get="{url}" hx-target="#main-container">
                <img class="img-fluid" style="height: 1.6em;"
                     src="{art_url}"/> {album_name}<br/>
            </a>
            """,
            url=reverse('album', kwargs={'album_id': value.id}),
            art_url=reverse('album_art', kwargs={'song_id': record.id}),
            album_name=value.name,
        )

    def order_album(self, queryset, is_descending):
        """Order album."""
        queryset = queryset.order_by(('-' if is_descending else '') + 'album__name', 'track_number')
        return queryset, True

    def render_track_length(self, value: float, record: Song) -> str:
        """Render track length."""
        return dur(value)

    def render_played_at(self, value: datetime, record: Song) -> str:
        """Render played at."""
        return days_ago(value)

    def render_genre(self, value: str, record: Song) -> str:
        """Render genre."""
        genre_html = render_to_string('main/snippet_genre.html', {'facet': 'song', 'obj': record})
        return format_html(genre_html)
