from datetime import timedelta
from unittest.mock import patch

import pytest
from bs4 import BeautifulSoup
from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone

from main.lastfm_service import extract_albums_from_table
from main.models import Album, Artist, History, Similar, Song
from main.plays import MIN_HISTORY_FOR_NEW_SONGS, get_next_song
from main.views import similars_bad_artists, similars_remove_artist


@pytest.fixture(autouse=True)
def _clear_cache():
    """Keep cached querysets, ranks and priority values from leaking between tests."""
    cache.clear()
    yield
    cache.clear()


# similars_bad_artists view


@pytest.fixture()
def bad_artists(db):
    """Two low rated artists and one good one, all with albums."""
    return [
        Artist.objects.create(
            name='Bad Artist 1',
            slug='bad-artist-1',
            rating=0.2,
            count_albums=2,
            total_length=3600.0,
        ),
        Artist.objects.create(
            name='Bad Artist 2',
            slug='bad-artist-2',
            rating=0.3,
            count_albums=2,
            total_length=3600.0,
        ),
        Artist.objects.create(
            name='Good Artist',
            slug='good-artist',
            rating=0.8,
            count_albums=2,
            total_length=3600.0,
        ),
    ]


@patch('main.views.list_lowest_rated_artists', autospec=True)
def test_similars_bad_artists_without_cache(mock_list_artists, rf, bad_artists):
    """The selector is called and its result cached when the cache is empty."""
    mock_list_artists.return_value = Artist.objects.filter(id=bad_artists[0].id)

    response = similars_bad_artists(rf.get('/similars/bad-artists/'))

    mock_list_artists.assert_called_once_with(False)
    assert response.status_code == 200
    assert cache.get('sim_worst_artists') is not None


@patch('main.views.list_lowest_rated_artists', autospec=True)
def test_similars_bad_artists_with_cache(mock_list_artists, rf, bad_artists):
    """A populated cache is served without calling the selector."""
    cache.set('sim_worst_artists', Artist.objects.filter(id=bad_artists[0].id), timeout=3600 * 16)

    response = similars_bad_artists(rf.get('/similars/bad-artists/'))

    mock_list_artists.assert_not_called()
    assert response.status_code == 200


@patch('main.views.list_lowest_rated_artists', autospec=True)
def test_similars_bad_artists_with_refresh(mock_list_artists, rf, bad_artists):
    """A refresh of this panel bypasses the cache and refills it."""
    cache.set('sim_worst_artists', 'old_data', timeout=3600 * 16)
    mock_list_artists.return_value = Artist.objects.filter(id=bad_artists[1].id)

    response = similars_bad_artists(rf.get('/similars/bad-artists/?refresh=lp'))

    mock_list_artists.assert_called_once_with(False)
    assert response.status_code == 200
    assert cache.get('sim_worst_artists') is not None


@patch('main.views.list_lowest_rated_artists', autospec=True)
def test_similars_bad_artists_refresh_other_param(mock_list_artists, rf, bad_artists):
    """A refresh value for another panel leaves this cache alone."""
    cache.set('sim_worst_artists', Artist.objects.filter(id=bad_artists[0].id), timeout=3600 * 16)

    response = similars_bad_artists(rf.get('/similars/bad-artists/?refresh=other'))

    mock_list_artists.assert_not_called()
    assert response.status_code == 200


def test_similars_bad_artists_integration(rf, bad_artists):
    """Without mocks the view renders and caches the lowest rated artists."""
    response = similars_bad_artists(rf.get('/similars/bad-artists/'))

    assert response.status_code == 200
    assert 'Bad artists' in response.content.decode('utf-8')
    artist_ids = [artist.id for artist in cache.get('sim_worst_artists')]
    assert bad_artists[0].id in artist_ids
    assert bad_artists[1].id in artist_ids


def test_similars_bad_artists_renders_correct_template(rf, bad_artists):
    """The bad artists snippet, with its refresh control, is rendered."""
    response = similars_bad_artists(rf.get('/similars/bad-artists/'))

    content = response.content.decode('utf-8')
    assert 'Bad artists' in content
    assert 'Refresh' in content


@patch('main.views.list_lowest_rated_artists', autospec=True)
def test_similars_bad_artists_calls_selector_with_correct_param(mock_list_artists, rf, db):
    """The selector is asked for artists with any album count."""
    mock_list_artists.return_value = Artist.objects.none()

    similars_bad_artists(rf.get('/similars/bad-artists/'))

    mock_list_artists.assert_called_once_with(False)


# similars_remove_artist view


@pytest.fixture()
def _similar_records(db):
    """Two similars for the slug being removed and one for a slug that stays."""
    now = timezone.now()
    artist1 = Artist.objects.create(
        name='Source Artist 1',
        slug='source-artist-1',
        rating=0.8,
        count_albums=2,
        total_length=3600.0,
    )
    artist2 = Artist.objects.create(
        name='Source Artist 2',
        slug='source-artist-2',
        rating=0.7,
        count_albums=2,
        total_length=3600.0,
    )
    Similar.objects.create(
        artist=artist1,
        artist_name='Unwanted Artist',
        artist_slug='unwanted-artist',
        match=0.5,
        rating=0.8,
        score=0.4,
        scraped_at=now,
    )
    Similar.objects.create(
        artist=artist2,
        artist_name='Unwanted Artist',
        artist_slug='unwanted-artist',
        match=0.6,
        rating=0.7,
        score=0.42,
        scraped_at=now,
    )
    Similar.objects.create(
        artist=artist1,
        artist_name='Wanted Artist',
        artist_slug='wanted-artist',
        match=0.9,
        rating=0.8,
        score=0.72,
        scraped_at=now,
    )


@pytest.mark.usefixtures('_similar_records')
@patch('main.views.update_next_similar_artist', autospec=True)
def test_remove_artist_removes_all_records_for_slug(mock_update, rf):
    """Every similar carrying the slug goes, others are untouched."""
    mock_update.return_value = []
    request = rf.get('/similars/new-artists/remove/unwanted-artist/')

    similars_remove_artist(request, 'unwanted-artist')

    assert Similar.objects.filter(artist_slug='unwanted-artist').count() == 0
    assert Similar.objects.filter(artist_slug='wanted-artist').count() == 1


@pytest.mark.usefixtures('_similar_records')
@patch('main.views.update_next_similar_artist', autospec=True)
def test_remove_artist_clears_cache_and_refreshes(mock_update, rf):
    """The grouped similar cache is rebuilt after the removal."""
    mock_update.return_value = []
    cache.set('sim_grouped_similar', 'old_cached_data', timeout=3600 * 16)
    request = rf.get('/similars/new-artists/remove/unwanted-artist/')

    similars_remove_artist(request, 'unwanted-artist')

    mock_update.assert_called_once()
    assert cache.get('sim_grouped_similar') != 'old_cached_data'


@pytest.mark.usefixtures('_similar_records')
@patch('main.views.update_next_similar_artist', autospec=True)
def test_remove_artist_renders_new_artists_snippet(mock_update, rf):
    """The response is the new artists snippet."""
    mock_update.return_value = []
    request = rf.get('/similars/new-artists/remove/unwanted-artist/')

    response = similars_remove_artist(request, 'unwanted-artist')

    assert response.status_code == 200
    assert 'New artists' in response.content.decode('utf-8')


@pytest.mark.usefixtures('_similar_records')
@patch('main.views.update_next_similar_artist', autospec=True)
def test_remove_artist_nonexistent_slug_is_no_op(mock_update, rf):
    """Removing an unknown slug leaves every record in place."""
    mock_update.return_value = []
    request = rf.get('/similars/new-artists/remove/no-such-artist/')

    response = similars_remove_artist(request, 'no-such-artist')

    assert response.status_code == 200
    assert Similar.objects.count() == 3


# get_next_song: skipping unplayed songs while the history window is short


def _make_song(slug: str, rating: float, count_played: int = 0, days_ago: int = 0) -> Song:
    """Create an artist/album/song trio, played days_ago when count_played is set."""
    artist = Artist.objects.create(name=slug, slug=slug, total_length=3600.0)
    album = Album.objects.create(
        artist=artist,
        name=slug,
        slug=slug,
        year=2000,
        total_discs=1,
        total_tracks=1,
        total_length=240.0,
    )
    return Song.objects.create(
        album=album,
        artist=artist,
        rel_path=f'{slug}.mp3',
        slug=slug,
        name=slug,
        disc_number=1,
        track_number=1,
        track_length=240.0,
        rating=rating,
        count_played=count_played,
        played_at=timezone.now() - timedelta(days=days_ago) if count_played else None,
    )


def _play(song: Song, times: int):
    """Put the given number of plays of the song in the recent window."""
    for _ in range(times):
        History.objects.create(song=song, played_at=timezone.now())


@pytest.fixture()
def catalog(db):
    """One played candidate, two unplayed ones and a song used to fill history."""
    return {
        'played': _make_song('played', rating=0.9, count_played=3, days_ago=10),
        'new': _make_song('new-a', rating=0.5),
        'other_new': _make_song('new-b', rating=0.4),
        'history': _make_song('history', rating=0.1, count_played=1, days_ago=1),
    }


def test_skips_new_songs_while_history_is_short(catalog):
    """A played song is picked over the higher priority unplayed ones."""
    _play(catalog['history'], 1)

    assert get_next_song() == catalog['played']


@patch('main.plays.next_song_lookup_limit', 2)
def test_picks_new_song_when_all_candidates_are_new(catalog):
    """With nothing played to skip to, the top priority song wins as usual."""
    _play(catalog['history'], 1)

    assert get_next_song() == catalog['new']


@patch('main.plays.sa')
def test_falls_back_to_a_played_song_when_every_artist_is_queued(mock_sa, catalog):
    """The random fallback stays on played songs while new ones are skipped."""
    _play(catalog['played'], 1)
    _play(catalog['history'], 1)

    assert get_next_song() in (catalog['played'], catalog['history'])


def test_picks_new_song_once_history_is_long_enough(catalog):
    """Once the window holds enough plays to rate, new songs are eligible again."""
    _play(catalog['history'], MIN_HISTORY_FOR_NEW_SONGS)

    assert get_next_song() == catalog['new']


# percentile based rank property


@pytest.fixture()
def rated_artists(db):
    """Five artists spread evenly across the rating range, worst first."""
    return [
        Artist.objects.create(
            name=f'Artist {i}',
            slug=f'artist-{i}',
            rating=rating,
            count_albums=1,
            total_length=3600.0,
        )
        for i, rating in enumerate([0.1, 0.3, 0.5, 0.7, 0.9])
    ]


def test_highest_rated_is_rank_1(rated_artists):
    """The highest-rated artist should have rank 1."""
    assert rated_artists[4].rank == 1


def test_lowest_rated_is_rank_99(rated_artists):
    """The lowest-rated artist should have rank 99."""
    assert rated_artists[0].rank == 99


def test_middle_rated_is_around_50(rated_artists):
    """The middle-rated artist should have a rank around 50."""
    assert rated_artists[2].rank == 50


def test_percentiles_are_ordered(rated_artists):
    """Higher-rated artists should have lower rank numbers."""
    ranks = [artist.rank for artist in rated_artists]

    assert ranks == sorted(ranks, reverse=True)


def test_single_item_returns_1(db):
    """A single item should have rank 1."""
    solo = Artist.objects.create(
        name='Solo Artist',
        slug='solo-artist',
        rating=0.5,
        count_albums=1,
        total_length=3600.0,
    )

    assert solo.rank == 1


def test_two_items(db):
    """With two items, best should be 1 and worst should be 99."""
    low = Artist.objects.create(
        name='Low Artist',
        slug='low-artist',
        rating=0.2,
        count_albums=1,
        total_length=3600.0,
    )
    high = Artist.objects.create(
        name='High Artist',
        slug='high-artist',
        rating=0.8,
        count_albums=1,
        total_length=3600.0,
    )

    assert high.rank == 1
    assert low.rank == 99


def test_rank_is_cached(rated_artists):
    """Second call should use the cached value."""
    artist = rated_artists[4]
    _ = artist.rank  # populate cache

    with patch.object(Artist.objects, 'filter', autospec=True) as mock_filter:
        cached_rank = artist.rank
        mock_filter.assert_not_called()

    assert cached_rank == 1


# extract_albums_from_table


def _albums_from(html: str) -> list:
    """Run the wikipedia table parser over a table snippet."""
    return extract_albums_from_table(BeautifulSoup(html, 'html.parser').find('table'))


def test_skips_rows_without_year():
    """Rows with no extractable year should be skipped."""
    albums = _albums_from("""
        <table>
            <tr>
                <th scope="row"><a href="/wiki/Album1">Album One</a></th>
                <td>Released: March 15, 2020</td>
            </tr>
            <tr>
                <th scope="row"><a href="/wiki/Album2">Album Two</a></th>
                <td>TBD</td>
            </tr>
        </table>
    """)

    assert len(albums) == 1
    assert albums[0]['name'] == 'Album One'
    assert albums[0]['year'] == '2020'


def test_extracts_year_from_header_cell_format():
    """Albums in th[scope=row] format should have year extracted from first td."""
    albums = _albums_from("""
        <table>
            <tr>
                <th scope="row"><a href="/wiki/TestAlbum">Test Album</a></th>
                <td>June 2019</td>
            </tr>
        </table>
    """)

    assert len(albums) == 1
    assert albums[0]['year'] == '2019'


def test_extracts_albums_from_fallback_format():
    """Albums in two-column td format should be extracted correctly."""
    albums = _albums_from("""
        <table>
            <tr>
                <td>2015</td>
                <td><i><a href="/wiki/MyAlbum">My Album</a></i></td>
            </tr>
        </table>
    """)

    assert len(albums) == 1
    assert albums[0]['name'] == 'My Album'
    assert albums[0]['year'] == '2015'


def test_extracts_albums_with_details_in_first_td():
    """Albums with title and release info in the first cell are extracted."""
    albums = _albums_from(
        '<table>'
        '<tr><th>Album details</th><th>Chart positions</th></tr>'
        '<tr><td>'
        '<i><a href="/wiki/The_Lonely_Position_of_Neutral">'
        'The Lonely Position of Neutral</a></i>'
        '<ul><li>Released: July 23, 2002</li><li>Label: Geffen</li></ul>'
        '</td><td>11</td></tr>'
        '<tr><td>'
        '<i><a href="/wiki/True_Parallels">True Parallels</a></i>'
        '<ul><li>Released: March 22, 2005</li><li>Label: Geffen</li></ul>'
        '</td><td>32</td></tr>'
        '<tr><td>'
        '<i><a href="/wiki/Dreaming_in_Black_and_White">'
        'Dreaming in Black and White</a></i>'
        '<ul><li>Released: March 8, 2011</li>'
        '<li>Label: Entertainment One</li></ul>'
        '</td><td>175</td></tr>'
        '</table>'
    )

    assert len(albums) == 3
    assert albums[0]['name'] == 'The Lonely Position of Neutral'
    assert albums[0]['year'] == '2002'
    assert albums[0]['href'] == 'https://en.wikipedia.org/wiki/The_Lonely_Position_of_Neutral'
    assert albums[1]['name'] == 'True Parallels'
    assert albums[1]['year'] == '2005'
    assert albums[2]['name'] == 'Dreaming in Black and White'
    assert albums[2]['year'] == '2011'


def test_first_td_format_skips_rows_without_year():
    """First-cell format should skip rows where no year can be found."""
    albums = _albums_from("""
        <table>
            <tr>
                <td>
                    <i>Upcoming Album</i>
                    <ul><li>Released: TBD</li></ul>
                </td>
                <td></td>
            </tr>
        </table>
    """)

    assert len(albums) == 0


# song title inline edit view


@pytest.fixture()
def editable_song(db):
    """A song whose title can be renamed through the view."""
    artist = Artist.objects.create(
        name='Edit Artist',
        slug='edit-artist',
        count_albums=1,
        total_length=100.0,
    )
    album = Album.objects.create(
        artist=artist,
        name='Edit Album',
        slug='edit-artist-edit-album',
        year=2000,
        total_discs=1,
        total_tracks=1,
        total_length=100.0,
    )
    return Song.objects.create(
        artist=artist,
        album=album,
        rel_path='edit-artist/edit-album/01 song.mp3',
        slug='edit-artist-edit-album-01-song-mp3',
        name='Bad Title [HQ]',
        disc_number=1,
        track_number=1,
        track_length=100.0,
    )


@pytest.fixture()
def song_title_url(editable_song):
    """The inline title endpoint for the editable song."""
    return reverse('song_title', kwargs={'song_id': editable_song.id})


def test_get_renders_title_with_edit_pencil(client, song_title_url):
    """Plain GET should render the title and the pencil link."""
    response = client.get(song_title_url)

    content = response.content.decode('utf-8')
    assert response.status_code == 200
    assert 'Bad Title [HQ]' in content
    assert 'bi-pencil' in content
    assert '<input' not in content


def test_get_edit_renders_form(client, song_title_url):
    """GET with edit=1 should render the input pre-filled with the title."""
    response = client.get(song_title_url, {'edit': '1'})

    content = response.content.decode('utf-8')
    assert response.status_code == 200
    assert 'name="name"' in content
    assert 'value="Bad Title [HQ]"' in content


@patch('main.views.write_song_title', autospec=True)
def test_post_updates_db_and_file(mock_write, client, song_title_url, editable_song):
    """A valid POST should write the file and update the song."""
    response = client.post(song_title_url, {'name': 'Good Title'})

    content = response.content.decode('utf-8')
    mock_write.assert_called_once_with(editable_song, 'Good Title')
    editable_song.refresh_from_db()
    assert editable_song.name == 'Good Title'
    assert 'Good Title' in content
    assert '<input' not in content


@patch('main.views.write_song_title', autospec=True)
def test_post_strips_whitespace(mock_write, client, song_title_url, editable_song):
    """Surrounding whitespace should be trimmed off the new title."""
    client.post(song_title_url, {'name': '  Good Title  '})

    mock_write.assert_called_once_with(editable_song, 'Good Title')
    editable_song.refresh_from_db()
    assert editable_song.name == 'Good Title'


@patch('main.views.write_song_title', autospec=True)
def test_post_empty_title_is_rejected(mock_write, client, song_title_url, editable_song):
    """An empty title should not touch the file or the song."""
    response = client.post(song_title_url, {'name': '   '})

    content = response.content.decode('utf-8')
    mock_write.assert_not_called()
    editable_song.refresh_from_db()
    assert editable_song.name == 'Bad Title [HQ]'
    assert 'Title cannot be empty' in content
    assert 'name="name"' in content


@patch('main.views.write_song_title', autospec=True)
def test_post_keeps_db_unchanged_when_file_write_fails(
    mock_write, client, song_title_url, editable_song
):
    """A failed file write should leave the song name as it was."""
    mock_write.side_effect = OSError('file is locked')

    response = client.post(song_title_url, {'name': 'Good Title'})

    content = response.content.decode('utf-8')
    editable_song.refresh_from_db()
    assert editable_song.name == 'Bad Title [HQ]'
    assert 'file is locked' in content
    assert 'value="Good Title"' in content
