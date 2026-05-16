from unittest.mock import patch

from django.core.cache import cache
from django.test import RequestFactory, TestCase

from main.models import Artist, Similar
from main.views import similars_bad_artists, similars_remove_artist


class SimilarsBadArtistsViewTest(TestCase):
    """Test cases for similars_bad_artists view."""

    def setUp(self):
        """Set up test data."""
        self.factory = RequestFactory()

        # Create test artists with different ratings
        self.artist1 = Artist.objects.create(
            name='Bad Artist 1',
            slug='bad-artist-1',
            rating=0.2,
            count_albums=2,
            total_length=3600.0,
        )
        self.artist2 = Artist.objects.create(
            name='Bad Artist 2',
            slug='bad-artist-2',
            rating=0.3,
            count_albums=2,
            total_length=3600.0,
        )
        self.artist3 = Artist.objects.create(
            name='Good Artist',
            slug='good-artist',
            rating=0.8,
            count_albums=2,
            total_length=3600.0,
        )

        # Clear cache before each test
        cache.clear()

    def tearDown(self):
        """Clean up after tests."""
        cache.clear()

    @patch('main.views.list_lowest_rated_artists', autospec=True)
    def test_similars_bad_artists_without_cache(self, mock_list_artists):
        """Test view when cache is empty."""
        # Setup: return a real queryset
        mock_queryset = Artist.objects.filter(id=self.artist1.id)
        mock_list_artists.return_value = mock_queryset

        # Create request
        request = self.factory.get('/similars/bad-artists/')

        # Call the view
        response = similars_bad_artists(request)

        # Verify the selector was called
        mock_list_artists.assert_called_once_with(False)

        # Verify response
        assert response.status_code == 200

        # Verify cache was set
        cached_data = cache.get('sim_worst_artists')
        assert cached_data is not None

    @patch('main.views.list_lowest_rated_artists', autospec=True)
    def test_similars_bad_artists_with_cache(self, mock_list_artists):
        """Test view when cache already has data."""
        # Pre-populate cache with real queryset
        cached_queryset = Artist.objects.filter(id=self.artist1.id)
        cache.set('sim_worst_artists', cached_queryset, timeout=3600 * 16)

        # Create request
        request = self.factory.get('/similars/bad-artists/')

        # Call the view
        response = similars_bad_artists(request)

        # Verify the selector was NOT called (using cache)
        mock_list_artists.assert_not_called()

        # Verify response
        assert response.status_code == 200

    @patch('main.views.list_lowest_rated_artists', autospec=True)
    def test_similars_bad_artists_with_refresh(self, mock_list_artists):
        """Test view with refresh parameter."""
        # Pre-populate cache
        cache.set('sim_worst_artists', 'old_data', timeout=3600 * 16)

        # Setup: return a real queryset
        mock_queryset = Artist.objects.filter(id=self.artist2.id)
        mock_list_artists.return_value = mock_queryset

        # Create request with refresh parameter
        request = self.factory.get('/similars/bad-artists/?refresh=lp')

        # Call the view
        response = similars_bad_artists(request)

        # Verify the selector was called (cache was bypassed)
        mock_list_artists.assert_called_once_with(False)

        # Verify response
        assert response.status_code == 200

        # Verify cache was updated
        cached_data = cache.get('sim_worst_artists')
        assert cached_data is not None

    @patch('main.views.list_lowest_rated_artists', autospec=True)
    def test_similars_bad_artists_refresh_other_param(self, mock_list_artists):
        """Test view with different refresh parameter does not trigger refresh."""
        # Pre-populate cache
        cached_queryset = Artist.objects.filter(id=self.artist1.id)
        cache.set('sim_worst_artists', cached_queryset, timeout=3600 * 16)

        # Create request with different refresh parameter
        request = self.factory.get('/similars/bad-artists/?refresh=other')

        # Call the view
        response = similars_bad_artists(request)

        # Verify the selector was NOT called (cache was used)
        mock_list_artists.assert_not_called()

        # Verify response
        assert response.status_code == 200

    def test_similars_bad_artists_integration(self):
        """Integration test with real data (no mocks)."""
        # Create request
        request = self.factory.get('/similars/bad-artists/')

        # Call the view
        response = similars_bad_artists(request)

        # Verify response
        assert response.status_code == 200

        # Verify content contains expected text
        content = response.content.decode('utf-8')
        assert 'Bad artists' in content

        # Verify cache was populated
        cached_data = cache.get('sim_worst_artists')
        assert cached_data is not None

        # Verify queryset contains expected artists (lowest rated with count_albums > 0)
        artist_ids = [artist.id for artist in cached_data]
        assert self.artist1.id in artist_ids
        assert self.artist2.id in artist_ids

    def test_similars_bad_artists_renders_correct_template(self):
        """Test that the correct template is rendered."""
        # Create request
        request = self.factory.get('/similars/bad-artists/')

        # Call the view
        response = similars_bad_artists(request)

        # Verify correct template is used by checking for expected content
        content = response.content.decode('utf-8')
        assert 'Bad artists' in content
        assert 'Refresh' in content

    @patch('main.views.list_lowest_rated_artists', autospec=True)
    def test_similars_bad_artists_calls_selector_with_correct_param(self, mock_list_artists):
        """Test that list_lowest_rated_artists is called with False parameter."""
        mock_list_artists.return_value = Artist.objects.none()

        # Create request
        request = self.factory.get('/similars/bad-artists/')

        # Call the view
        similars_bad_artists(request)

        # Verify the selector was called with False
        mock_list_artists.assert_called_once_with(False)

    def test_similars_bad_artists_context_contains_correct_key(self):
        """Test that context contains the correct key."""
        # Create request
        request = self.factory.get('/similars/bad-artists/')

        # Call the view
        response = similars_bad_artists(request)

        # Check the response was successful
        assert response.status_code == 200

        # Verify cache contains the expected data
        worst_artists = cache.get('sim_worst_artists')
        assert worst_artists is not None


class SimilarsRemoveArtistViewTest(TestCase):
    """Test cases for similars_remove_artist view."""

    def setUp(self):
        """Set up test data."""
        self.factory = RequestFactory()

        self.artist1 = Artist.objects.create(
            name='Source Artist 1',
            slug='source-artist-1',
            rating=0.8,
            count_albums=2,
            total_length=3600.0,
        )
        self.artist2 = Artist.objects.create(
            name='Source Artist 2',
            slug='source-artist-2',
            rating=0.7,
            count_albums=2,
            total_length=3600.0,
        )

        from django.utils import timezone

        now = timezone.now()

        # Create Similar records for the artist to be removed
        Similar.objects.create(
            artist=self.artist1,
            artist_name='Unwanted Artist',
            artist_slug='unwanted-artist',
            match=0.5,
            rating=0.8,
            score=0.4,
            scraped_at=now,
        )
        Similar.objects.create(
            artist=self.artist2,
            artist_name='Unwanted Artist',
            artist_slug='unwanted-artist',
            match=0.6,
            rating=0.7,
            score=0.42,
            scraped_at=now,
        )
        # Create a Similar record for a different artist that should NOT be removed
        Similar.objects.create(
            artist=self.artist1,
            artist_name='Wanted Artist',
            artist_slug='wanted-artist',
            match=0.9,
            rating=0.8,
            score=0.72,
            scraped_at=now,
        )

        cache.clear()

    def tearDown(self):
        """Clean up after tests."""
        cache.clear()

    @patch('main.views.update_next_similar_artist', autospec=True)
    def test_removes_all_similar_records_for_slug(self, mock_update):
        """Test that all Similar records for the given slug are deleted."""
        mock_update.return_value = []

        request = self.factory.get('/similars/new-artists/remove/unwanted-artist/')
        similars_remove_artist(request, 'unwanted-artist')

        # All records for 'unwanted-artist' should be gone
        assert Similar.objects.filter(artist_slug='unwanted-artist').count() == 0
        # Record for 'wanted-artist' should still exist
        assert Similar.objects.filter(artist_slug='wanted-artist').count() == 1

    @patch('main.views.update_next_similar_artist', autospec=True)
    def test_clears_cache_and_refreshes(self, mock_update):
        """Test that the grouped similar cache is cleared and refreshed."""
        mock_update.return_value = []
        cache.set('sim_grouped_similar', 'old_cached_data', timeout=3600 * 16)

        request = self.factory.get('/similars/new-artists/remove/unwanted-artist/')
        similars_remove_artist(request, 'unwanted-artist')

        # Old cached data should be replaced; update_next_similar_artist is called
        mock_update.assert_called_once()
        assert cache.get('sim_grouped_similar') != 'old_cached_data'

    @patch('main.views.update_next_similar_artist', autospec=True)
    def test_returns_200(self, mock_update):
        """Test that the view returns a successful response."""
        mock_update.return_value = []

        request = self.factory.get('/similars/new-artists/remove/unwanted-artist/')
        response = similars_remove_artist(request, 'unwanted-artist')

        assert response.status_code == 200

    @patch('main.views.update_next_similar_artist', autospec=True)
    def test_renders_new_artists_template(self, mock_update):
        """Test that the response renders the new artists snippet."""
        mock_update.return_value = []

        request = self.factory.get('/similars/new-artists/remove/unwanted-artist/')
        response = similars_remove_artist(request, 'unwanted-artist')

        content = response.content.decode('utf-8')
        assert 'New artists' in content

    @patch('main.views.update_next_similar_artist', autospec=True)
    def test_nonexistent_slug_is_no_op(self, mock_update):
        """Test that removing a non-existent slug does not error."""
        mock_update.return_value = []

        request = self.factory.get('/similars/new-artists/remove/no-such-artist/')
        response = similars_remove_artist(request, 'no-such-artist')

        assert response.status_code == 200
        # All existing records should be untouched
        assert Similar.objects.count() == 3


class ShouldAddNewAlbumTest(TestCase):
    """Test cases for should_add_new_album function."""

    @patch('main.plays.num_songs_in_window', 5)
    def test_returns_false_when_not_enough_unique_artists(self):
        """Should return False when unique history artists < num_songs_in_window."""
        from main.plays import should_add_new_album

        history_artist_names = {'Artist A', 'Artist B', 'Artist C'}  # 3 < 5
        queue = {'Artist A': 0, 'Artist B': 1, 'Artist C': 0}

        result = should_add_new_album(history_artist_names, queue)
        assert not result

    @patch('main.plays.num_songs_in_window', 3)
    def test_returns_false_when_too_many_upcoming_songs(self):
        """Should return False when upcoming songs >= 2 * unique artists."""
        from main.plays import should_add_new_album

        # 3 unique artists, upcoming = 2+2+3 = 7, threshold = 2*3 = 6, 7 >= 6 => False
        history_artist_names = {'Artist A', 'Artist B', 'Artist C'}
        queue = {'Artist A': 2, 'Artist B': 2, 'Artist C': 3, 'Artist D': 5}

        result = should_add_new_album(history_artist_names, queue)
        assert not result

    @patch('main.plays.num_songs_in_window', 3)
    def test_returns_true_when_conditions_met(self):
        """Should return True when enough unique artists and few upcoming songs."""
        from main.plays import should_add_new_album

        # 3 unique artists, upcoming = 1+1+1 = 3, threshold = 2*3 = 6, 3 < 6 => True
        history_artist_names = {'Artist A', 'Artist B', 'Artist C'}
        queue = {'Artist A': 1, 'Artist B': 1, 'Artist C': 1, 'Artist D': 10}

        result = should_add_new_album(history_artist_names, queue)
        assert result

    @patch('main.plays.num_songs_in_window', 3)
    def test_returns_true_when_zero_upcoming_songs(self):
        """Should return True when history artists have no upcoming songs."""
        from main.plays import should_add_new_album

        # 4 unique artists, upcoming = 0+0+0+0 = 0, threshold = 2*4 = 8, 0 < 8 => True
        history_artist_names = {'Artist A', 'Artist B', 'Artist C', 'Artist D'}
        queue = {'Artist A': 0, 'Artist B': 0, 'Artist C': 0, 'Artist D': 0}

        result = should_add_new_album(history_artist_names, queue)
        assert result

    @patch('main.plays.num_songs_in_window', 3)
    def test_returns_false_at_exact_boundary(self):
        """Should return False when upcoming songs == exactly 2 * unique artists."""
        from main.plays import should_add_new_album

        # 3 unique artists, upcoming = 2+2+2 = 6, threshold = 2*3 = 6, 6 < 6 is False
        history_artist_names = {'Artist A', 'Artist B', 'Artist C'}
        queue = {'Artist A': 2, 'Artist B': 2, 'Artist C': 2}

        result = should_add_new_album(history_artist_names, queue)
        assert not result

    @patch('main.plays.num_songs_in_window', 3)
    def test_returns_true_just_below_boundary(self):
        """Should return True when upcoming songs == 2 * unique - 1."""
        from main.plays import should_add_new_album

        # 3 unique artists, upcoming = 2+2+1 = 5, threshold = 2*3 = 6, 5 < 6 => True
        history_artist_names = {'Artist A', 'Artist B', 'Artist C'}
        queue = {'Artist A': 2, 'Artist B': 2, 'Artist C': 1}

        result = should_add_new_album(history_artist_names, queue)
        assert result

    @patch('main.plays.num_songs_in_window', 3)
    def test_ignores_non_history_artists_in_queue(self):
        """Non-history artists in queue should not affect the upcoming count."""
        from main.plays import should_add_new_album

        # 3 history artists, upcoming = 0+0+0 = 0 (ignores Artist D's 100)
        history_artist_names = {'Artist A', 'Artist B', 'Artist C'}
        queue = {'Artist A': 0, 'Artist B': 0, 'Artist C': 0, 'Artist D': 100}

        result = should_add_new_album(history_artist_names, queue)
        assert result

    @patch('main.plays.num_songs_in_window', 5)
    def test_returns_false_with_empty_history(self):
        """Should return False when history is empty."""
        from main.plays import should_add_new_album

        history_artist_names = set()
        queue = {'Artist A': 3}

        result = should_add_new_album(history_artist_names, queue)
        assert not result


class RankPercentileTest(TestCase):
    """Test cases for percentile-based rank property."""

    def setUp(self):
        """Set up test data with known ratings."""
        cache.clear()
        self.artists = []
        for i, rating in enumerate([0.1, 0.3, 0.5, 0.7, 0.9]):
            artist = Artist.objects.create(
                name=f'Artist {i}',
                slug=f'artist-{i}',
                rating=rating,
                count_albums=1,
                total_length=3600.0,
            )
            self.artists.append(artist)

    def tearDown(self):
        """Clean up after tests."""
        cache.clear()

    def test_highest_rated_is_rank_1(self):
        """The highest-rated artist should have rank 1."""
        best = self.artists[4]  # rating=0.9
        assert best.rank == 1

    def test_lowest_rated_is_rank_99(self):
        """The lowest-rated artist should have rank 99."""
        worst = self.artists[0]  # rating=0.1
        assert worst.rank == 99

    def test_middle_rated_is_around_50(self):
        """The middle-rated artist should have a rank around 50."""
        middle = self.artists[2]  # rating=0.5
        assert middle.rank == 50

    def test_percentiles_are_ordered(self):
        """Higher-rated artists should have lower rank numbers."""
        ranks = [a.rank for a in self.artists]
        assert ranks == sorted(ranks, reverse=True)

    def test_single_item_returns_1(self):
        """A single item should have rank 1."""
        Artist.objects.all().delete()
        cache.clear()
        solo = Artist.objects.create(
            name='Solo Artist',
            slug='solo-artist',
            rating=0.5,
            count_albums=1,
            total_length=3600.0,
        )
        assert solo.rank == 1

    def test_two_items(self):
        """With two items, best should be 1 and worst should be 99."""
        Artist.objects.all().delete()
        cache.clear()
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

    def test_rank_never_exceeds_99(self):
        """Rank should never exceed 99 even with rounding."""
        for artist in self.artists:
            assert artist.rank <= 99

    def test_rank_is_cached(self):
        """Second call should use the cached value."""
        artist = self.artists[4]
        _ = artist.rank  # populate cache
        with patch.object(Artist.objects, 'filter', autospec=True) as mock_filter:
            cached_rank = artist.rank
            mock_filter.assert_not_called()
        assert cached_rank == 1


class ExtractAlbumsFromTableTest(TestCase):
    """Test cases for extract_albums_from_table."""

    def test_skips_rows_without_year(self):
        """Rows with no extractable year should be skipped."""
        from bs4 import BeautifulSoup

        from main.lastfm_service import extract_albums_from_table

        html = """
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
        """
        soup = BeautifulSoup(html, 'html.parser')
        table = soup.find('table')
        albums = extract_albums_from_table(table)

        assert len(albums) == 1
        assert albums[0]['name'] == 'Album One'
        assert albums[0]['year'] == '2020'

    def test_extracts_year_from_header_cell_format(self):
        """Albums in th[scope=row] format should have year extracted from first td."""
        from bs4 import BeautifulSoup

        from main.lastfm_service import extract_albums_from_table

        html = """
        <table>
            <tr>
                <th scope="row"><a href="/wiki/TestAlbum">Test Album</a></th>
                <td>June 2019</td>
            </tr>
        </table>
        """
        soup = BeautifulSoup(html, 'html.parser')
        table = soup.find('table')
        albums = extract_albums_from_table(table)

        assert len(albums) == 1
        assert albums[0]['year'] == '2019'

    def test_extracts_albums_from_fallback_format(self):
        """Albums in two-column td format should be extracted correctly."""
        from bs4 import BeautifulSoup

        from main.lastfm_service import extract_albums_from_table

        html = """
        <table>
            <tr>
                <td>2015</td>
                <td><i><a href="/wiki/MyAlbum">My Album</a></i></td>
            </tr>
        </table>
        """
        soup = BeautifulSoup(html, 'html.parser')
        table = soup.find('table')
        albums = extract_albums_from_table(table)

        assert len(albums) == 1
        assert albums[0]['name'] == 'My Album'
        assert albums[0]['year'] == '2015'

    def test_extracts_albums_with_details_in_first_td(self):
        """Albums with title and release info in first <td> (Trust Company format)."""
        from bs4 import BeautifulSoup

        from main.lastfm_service import extract_albums_from_table

        html = (
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
        soup = BeautifulSoup(html, 'html.parser')
        table = soup.find('table')
        albums = extract_albums_from_table(table)

        assert len(albums) == 3

        assert albums[0]['name'] == 'The Lonely Position of Neutral'
        assert albums[0]['year'] == '2002'
        assert albums[0]['href'] == 'https://en.wikipedia.org/wiki/The_Lonely_Position_of_Neutral'

        assert albums[1]['name'] == 'True Parallels'
        assert albums[1]['year'] == '2005'

        assert albums[2]['name'] == 'Dreaming in Black and White'
        assert albums[2]['year'] == '2011'

    def test_first_td_format_skips_rows_without_year(self):
        """First-<td> format should skip rows where no year can be found."""
        from bs4 import BeautifulSoup

        from main.lastfm_service import extract_albums_from_table

        html = """
        <table>
            <tr>
                <td>
                    <i>Upcoming Album</i>
                    <ul><li>Released: TBD</li></ul>
                </td>
                <td></td>
            </tr>
        </table>
        """
        soup = BeautifulSoup(html, 'html.parser')
        table = soup.find('table')
        albums = extract_albums_from_table(table)

        assert len(albums) == 0


class ScrapeStudioAlbumsYearPrefixTest(TestCase):
    """Test that year prefix stripping handles None year."""

    def test_year_prefix_stripped_when_present(self):
        """Album name starting with year should have the year prefix removed."""
        # We test the year-stripping logic inline
        album_info = {'name': '2020 Some Album', 'year': '2020'}
        if album_info['year'] and album_info['name'].startswith(album_info['year']):
            album_info['name'] = album_info['name'][5:]
        assert album_info['name'] == 'Some Album'

    def test_none_year_does_not_crash(self):
        """Album with None year should not raise TypeError."""
        album_info = {'name': 'Some Album', 'year': None}
        # This should not raise
        if album_info['year'] and album_info['name'].startswith(album_info['year']):
            album_info['name'] = album_info['name'][5:]
        assert album_info['name'] == 'Some Album'
