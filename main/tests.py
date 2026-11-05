import os
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

import pylast
import pytest
from bs4 import BeautifulSoup
from django.core.cache import cache, caches
from django.core.management import call_command
from django.db import OperationalError
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify
from unidecode import unidecode

from main.discography import get_missing_songs
from main.lastfm_service import (
    artist_slug,
    extract_albums_from_table,
    get_album_tracks,
    get_artist_top_albums,
    get_artist_top_tracks,
    get_similar_artists,
    get_track_album,
    scrobble,
)
from main.models import Album, Artist, History, Rating, Similar, Song
from main.musicfiles import recheck_metadata
from main.plays import MIN_HISTORY_FOR_NEW_SONGS, _slope_steps_remaining, get_next_song
from main.ratings import filled_mean, set_match_result
from main.selectors import (
    get_recent_artists,
    list_lowest_rated_albums,
    upkeep_album,
    upkeep_artist,
)
from main.signals import retry_locked
from main.similars import (
    SIMILARS_FETCH_LIMIT,
    get_recommended_album,
    update_next_similar_artist,
)
from main.templatetags.fmt import days_ago
from main.views import (
    similars_bad_albums,
    similars_bad_artists,
    similars_missing_albums_view,
    similars_recommended_view,
    similars_remove_artist,
)


@pytest.fixture(autouse=True)
def _clear_cache(settings):
    """Keep cached querysets, ranks and priority values from leaking between tests."""
    # never let a test touch the countdown persisted on disk
    settings.CACHES = {
        **settings.CACHES,
        'persistent': {
            'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
            'LOCATION': 'tests',
        },
    }
    cache.clear()
    caches['persistent'].clear()
    yield
    cache.clear()
    caches['persistent'].clear()


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


# list_lowest_rated_albums: flag albums with a song that has not had enough chances


def _make_album(slug: str, rating: float, songs: list[tuple[int, int]]) -> Album:
    """Create an album with one song per (count_played, count_rated) pair."""
    artist = Artist.objects.create(name=slug, slug=slug, total_length=3600.0)
    album = Album.objects.create(
        artist=artist,
        name=slug,
        slug=slug,
        year=2000,
        total_discs=1,
        total_tracks=len(songs),
        total_length=240.0 * len(songs),
        rating=rating,
    )
    for track, (count_played, count_rated) in enumerate(songs, start=1):
        Song.objects.create(
            album=album,
            artist=artist,
            rel_path=f'{slug}-{track}.mp3',
            slug=f'{slug}-{track}',
            name=f'{slug} {track}',
            disc_number=1,
            track_number=track,
            track_length=240.0,
            count_played=count_played,
            count_rated=count_rated,
        )
    return album


def test_lowest_rated_albums_flags_albums_with_a_song_lacking_plays_or_ratings(db):
    """One song short on plays or ratings flags its album, which is still listed."""
    _make_album('rated', rating=0.4, songs=[(3, 10), (5, 17)])
    _make_album('few-plays', rating=0.1, songs=[(3, 10), (1, 17)])
    _make_album('few-ratings', rating=0.2, songs=[(3, 9), (5, 17)])

    flags = [(album.slug, album.needs_more_chances) for album in list_lowest_rated_albums()]

    assert flags == [('few-plays', True), ('few-ratings', True), ('rated', False)]


def test_lowest_rated_albums_sum_the_plays_and_ratings_left(db):
    """Each song adds what it is short of either minimum, and nothing once past it."""
    _make_album('short', rating=0.1, songs=[(0, 4), (1, 12)])

    album = list_lowest_rated_albums()[0]

    assert (album.plays_left, album.ratings_left) == (3, 6)


def test_similars_bad_albums_drops_album_removed_since_last_render(rf, db):
    """An album pruned after a render does not linger and break the artist link."""
    _make_album('kept', rating=0.4, songs=[(3, 11)])
    pruned = _make_album('pruned', rating=0.1, songs=[(3, 11)])
    similars_bad_albums(rf.get('/'))
    pruned.artist.delete()

    response = similars_bad_albums(rf.get('/'))

    assert b'pruned' not in response.content


# album and artist ratings: bayesian filled means


@pytest.mark.parametrize(
    ('ratings', 'expected'),
    [([1.0], 0.55), ([1.0] * 10, 1.0)],
    ids=['short-is-filled', 'full-is-plain-mean'],
)
def test_filled_mean_only_fills_short_lists(ratings, expected):
    """Missing items count as the filler, a full list is its plain mean."""
    assert filled_mean(ratings, 10, 0.5) == pytest.approx(expected)


@pytest.fixture()
def rated_songs(db):
    """A winner and a loser on one album, and an unrated song on another artist's album."""
    winner, loser = _make_album('two-songs', rating=0, songs=[(0, 0)] * 2).songs.order_by('id')
    unrated = _make_album('one-song', rating=0, songs=[(0, 0)]).songs.get()
    return winner, loser, unrated


# song ratings 1, 0, 0 make the song mean 1/3, which fills the 2 song album up to 10
TWO_SONG_ALBUM_RATING = (1 + 0 + 8 / 3) / 10


def test_set_match_result_fills_album_and_artist_ratings(rated_songs):
    """The artist averages its album with 2 more of the mean album rating."""
    winner, loser, _ = rated_songs

    set_match_result(winner.id, [loser.id])

    # the other album's stored rating is still 0
    album_mean = TWO_SONG_ALBUM_RATING / 2
    expected = (TWO_SONG_ALBUM_RATING + 2 * album_mean) / 3
    assert Artist.objects.get(id=winner.artist_id).rating == pytest.approx(expected)


def test_set_match_result_skips_missing_loser(rated_songs):
    """A loser pruned from the library is skipped, the winner still beats the rest."""
    winner, loser, gone = rated_songs
    gone_id = gone.id
    gone.delete()

    missing_ids = set_match_result(winner.id, [winner.id, loser.id, gone_id])

    assert missing_ids == [gone_id]
    assert Rating.objects.filter(winner=winner, loser=loser).count() == 1


def test_set_match_result_missing_winner_rates_nothing(rated_songs):
    """Without the winner there is nothing to rate."""
    gone, loser, _ = rated_songs
    gone_id = gone.id
    gone.delete()

    set_match_result(gone_id, [gone_id, loser.id])

    assert not Rating.objects.exists()


def test_upkeep_fills_album_and_artist_ratings(rated_songs):
    """Upkeep from the admin rates the album and artist the same way."""
    winner, _, _ = rated_songs
    Song.objects.filter(id=winner.id).update(rating=1.0)

    upkeep_album(winner.album)
    upkeep_artist(winner.artist)

    album_mean = TWO_SONG_ALBUM_RATING / 2
    expected = (TWO_SONG_ALBUM_RATING + 2 * album_mean) / 3
    assert Artist.objects.get(id=winner.artist_id).rating == pytest.approx(expected)


def test_cleanstats_all_recalculates_rows_not_marked_dirty(rated_songs):
    """--all fixes stale counts and ratings on rows nothing marked dirty."""
    winner, loser, _ = rated_songs
    Rating.objects.create(winner=winner, loser=loser, rated_at=timezone.now())

    call_command('cleanstats', '--all')

    album = Album.objects.get(id=winner.album_id)
    artist = Artist.objects.get(id=winner.artist_id)
    assert album.count_songs == 2
    assert artist.count_albums == 1
    assert artist.total_length == 480.0
    # the one song album is filled with the song mean too: (0 + 9 / 3) / 10
    album_mean = (TWO_SONG_ALBUM_RATING + 0.3) / 2
    assert artist.rating == pytest.approx((TWO_SONG_ALBUM_RATING + 2 * album_mean) / 3)


# deletes and moves mark the stats they leave behind dirty, for cleanstats


def test_deleting_a_song_marks_its_album_dirty(db):
    """The album the song leaves gets recounted by cleanstats."""
    album = _make_album('shrinking', rating=0, songs=[(0, 0)] * 2)

    album.songs.first().delete()

    assert Album.objects.get(id=album.id).is_dirty


def test_deleting_an_album_marks_its_artist_dirty(db):
    """The artist the album leaves gets recounted by cleanstats."""
    album = _make_album('emptied', rating=0, songs=[(0, 0)])

    album.delete()

    assert Artist.objects.get(id=album.artist_id).is_dirty


def _locked_once():
    calls = []

    def execute(*args):
        calls.append(args)
        if len(calls) == 1:
            raise OperationalError('database is locked')
        return 'done'

    return execute


@patch('main.signals.time.sleep')
def test_retry_locked_reruns_the_statement_until_unlocked(mock_sleep):
    execute = _locked_once()
    context = {'connection': SimpleNamespace(in_atomic_block=False)}

    assert retry_locked(execute, 'UPDATE', (), False, context) == 'done'


@patch('main.signals.time.sleep')
def test_retry_locked_raises_inside_a_transaction(mock_sleep):
    execute = _locked_once()
    context = {'connection': SimpleNamespace(in_atomic_block=True)}

    with pytest.raises(OperationalError):
        retry_locked(execute, 'UPDATE', (), False, context)


def test_retry_locked_raises_other_errors():
    def execute(*args):
        raise OperationalError('no such table: x')

    context = {'connection': SimpleNamespace(in_atomic_block=False)}

    with pytest.raises(OperationalError):
        retry_locked(execute, 'SELECT', (), False, context)


@pytest.fixture()
def song_file(editable_song, settings, tmp_path):
    """The editable song with its audio file on disk."""
    settings.MUSIC_DIR = tmp_path
    file_path = editable_song.file_path()
    file_path.parent.mkdir(parents=True)
    file_path.touch()
    return editable_song


def _tags(song, **overrides):
    """Parsed metadata matching the song as stored."""
    return {
        'artist_name': song.artist.name,
        'album_name': song.album.name,
        'year': song.album.year,
        'total_tracks': song.album.total_tracks,
        'total_discs': song.album.total_discs,
        'song_title': song.name,
        'disc_number': song.disc_number,
        'track_number': song.track_number,
        'track_length': song.track_length,
        **overrides,
    }


@patch('main.musicfiles.validate_songs', autospec=True)
@patch('main.musicfiles.parse_id3_tag', autospec=True)
def test_recheck_metadata_marks_the_album_a_song_moved_from_dirty(
    mock_parse, mock_validate, song_file
):
    """A song retagged onto another album leaves its old album to be recounted."""
    old_album_id = song_file.album_id
    Album.objects.create(
        artist=song_file.artist,
        name='Other Album',
        slug='edit-artist-other-album',
        year=2000,
        total_discs=1,
        total_tracks=1,
        total_length=100.0,
    )
    mock_parse.return_value = _tags(song_file, album_name='Other Album')

    recheck_metadata()

    assert Album.objects.get(id=old_album_id).is_dirty


@patch('main.musicfiles.parse_id3_tag', autospec=True)
def test_recheck_metadata_records_when_the_file_was_checked(mock_parse, song_file):
    """The next run can tell the file has not changed since."""
    mock_parse.return_value = _tags(song_file)

    recheck_metadata()

    assert Song.objects.get(id=song_file.id).checked_at


@patch('main.musicfiles.parse_id3_tag', autospec=True)
def test_recheck_metadata_skips_files_unmodified_since_checked(mock_parse, song_file):
    """Only files edited after their last check are parsed."""
    Song.objects.filter(id=song_file.id).update(checked_at=timezone.now() + timedelta(days=1))

    recheck_metadata()

    mock_parse.assert_not_called()


@patch('main.musicfiles.parse_id3_tag', autospec=True)
def test_recheck_metadata_all_parses_unmodified_files(mock_parse, song_file):
    """--all rechecks every file regardless of when it was checked."""
    Song.objects.filter(id=song_file.id).update(checked_at=timezone.now() + timedelta(days=1))
    mock_parse.return_value = _tags(song_file, song_title='Retagged')

    recheck_metadata(check_all=True)

    assert Song.objects.get(id=song_file.id).name == 'Retagged'


def test_recheck_metadata_keeps_songs_whose_file_moved(editable_song, settings, tmp_path):
    """A missing file is skipped, not a crash, and the song keeps its stats for scan."""
    settings.MUSIC_DIR = tmp_path

    recheck_metadata()

    assert Song.objects.filter(id=editable_song.id).exists()


@pytest.fixture()
def cached_art(song_file, settings, tmp_path):
    """The song's album art cached as b'old'."""
    settings.ALBUMS_DIR = tmp_path
    album = song_file.album
    path = tmp_path / f'{album.artist.slug}-{album.slug}-{album.id}.jpg'
    path.write_bytes(b'old')
    return path


@patch('main.views.get_album_art', return_value=SimpleNamespace(data=b'new'))
def test_album_art_reextracts_art_cached_before_the_file_changed(mock_art, client, cached_art):
    """New art written into the tags replaces the cached copy."""
    os.utime(cached_art, (0, 0))

    response = client.get(reverse('album_art', kwargs={'song_id': Song.objects.get().id}))

    assert response.content == b'new'


def test_album_art_serves_the_cache_when_the_file_is_missing(client, cached_art):
    """A moved file, not yet scanned, keeps its cached art."""
    song = Song.objects.get()
    song.file_path().unlink()

    response = client.get(reverse('album_art', kwargs={'song_id': song.id}))

    assert response.content == b'old'


def test_album_art_not_modified_since_the_file_changed(client, cached_art):
    song = Song.objects.get()
    response = client.get(reverse('album_art', kwargs={'song_id': song.id}))

    response = client.get(
        reverse('album_art', kwargs={'song_id': song.id}),
        HTTP_IF_MODIFIED_SINCE=response['Last-Modified'],
    )

    assert response.status_code == 304


# similar artists: fetched from last.fm per library artist, recommended by their top album


def _make_album_song(album, name, **fields):
    """Create a song on the album."""
    slug = slugify(unidecode(f'{album.slug}-{name}'))
    return Song.objects.create(
        artist=album.artist,
        album=album,
        rel_path=f'{slug}.mp3',
        slug=slug,
        name=name,
        disc_number=1,
        track_number=1,
        track_length=100.0,
        **fields,
    )


def _make_similar(artist, artist_name, score):
    """Create a similar artist recommended by the library artist."""
    return Similar.objects.create(
        artist=artist,
        artist_name=artist_name,
        artist_slug=artist_slug(artist_name),
        match=score,
        rating=1.0,
        score=score,
        scraped_at=timezone.now(),
    )


@pytest.fixture()
def seed_songs(db):
    """Two songs by the best artist, and Måneskin's Beggin' by a worse artist already owned."""
    seed_artist = Artist.objects.create(
        name='Seed Artist', slug='seed-artist', count_albums=1, total_length=100.0, rating=0.8
    )
    seed_album = Album.objects.create(
        artist=seed_artist,
        name='Seed Album',
        slug='seed-artist-seed-album',
        year=2000,
        total_discs=1,
        total_tracks=2,
        total_length=100.0,
    )
    owned_artist = Artist.objects.create(
        name='Måneskin', slug='maneskin', count_albums=1, total_length=100.0, rating=0.5
    )
    owned_album = Album.objects.create(
        artist=owned_artist,
        name='Owned Album',
        slug='maneskin-owned-album',
        year=2000,
        total_discs=1,
        total_tracks=1,
        total_length=100.0,
    )
    _make_album_song(owned_album, 'Beggin’ (Live)')
    top = _make_album_song(seed_album, 'Top Song’s', count_played=5, rating=0.8)
    low = _make_album_song(seed_album, 'Low Song', count_played=1, rating=0.9)
    return top, low


@pytest.fixture()
def seed_artists(seed_songs):
    """The seed artist and Måneskin."""
    return Artist.objects.get(name='Seed Artist'), Artist.objects.get(name='Måneskin')


@pytest.fixture()
def lastfm(settings):
    """Last.fm enabled with the network mocked."""
    settings.LASTFM_ENABLE = True
    with patch('main.lastfm_service.get_network', autospec=True) as mock_network:
        yield mock_network.return_value


@pytest.fixture()
def similar_artists(settings):
    """Last.fm enabled with the similar artists fetch mocked."""
    settings.LASTFM_ENABLE = True
    with patch('main.similars.get_similar_artists', autospec=True, return_value=[]) as mock:
        yield mock


def test_similar_artists_retries_network_error(lastfm):
    """A timed out handshake is retried, so one slow connection does not lose the update."""
    lastfm.get_artist.return_value.get_similar.side_effect = [
        pylast.NetworkError(None, TimeoutError('handshake timed out')),
        [pylast.SimilarItem(SimpleNamespace(name='New Band'), 0.5)],
    ]

    assert get_similar_artists('Band', 50) == [('New Band', 0.5)]


def test_similar_artists_gives_up_after_network_errors(lastfm, caplog):
    """Every attempt failing raises, without logging the network's keys."""
    # the error holds the network, whose repr carries the api key, secret and session key
    lastfm.get_artist.return_value.get_similar.side_effect = pylast.NetworkError(
        'api-secret', TimeoutError('handshake timed out')
    )

    with pytest.raises(pylast.NetworkError):
        get_similar_artists('Band', 50)

    assert 'api-secret' not in caplog.text


def test_update_similars_queries_best_seed_artist(similar_artists, seed_songs):
    """The best rated artist is fetched first."""
    update_next_similar_artist()

    similar_artists.assert_called_once_with('Seed Artist', SIMILARS_FETCH_LIMIT)


def test_update_similars_saves_only_new_artists(similar_artists, seed_songs):
    """Owned artists (accents aside), repeated and unsluggable artists are skipped."""
    similar_artists.return_value = [
        ('Maneskin', 1.0),
        ('New Band', 0.5),
        ('New Band', 0.4),
        ('(-)', 0.3),
    ]

    update_next_similar_artist()

    saved = list(Similar.objects.values_list('artist__name', 'artist_slug', 'score'))
    assert saved == [('Seed Artist', 'new-band', 0.8 * 0.5)]


def test_update_similars_marks_seed_done(similar_artists, seed_artists):
    """The artist is not fetched again."""
    seed, _ = seed_artists

    update_next_similar_artist()

    seed.refresh_from_db()
    assert seed.similars_at is not None


def test_update_similars_marks_unknown_artist_done(similar_artists, seed_artists):
    """An artist last.fm does not know must not block the artists after it."""
    seed, _ = seed_artists
    similar_artists.side_effect = pylast.WSError(None, '6', 'Artist not found')

    update_next_similar_artist()

    seed.refresh_from_db()
    assert seed.similars_at is not None


def test_update_similars_retries_after_outage(similar_artists, seed_artists):
    """A last.fm outage leaves the artist to be fetched on the next update."""
    seed, _ = seed_artists
    similar_artists.side_effect = pylast.WSError(
        None, 503, 'Connection to the API failed with HTTP code 503'
    )

    update_next_similar_artist()

    seed.refresh_from_db()
    assert seed.similars_at is None


def test_update_similars_seeds_only_top_decile(similar_artists, seed_artists):
    """An artist outside the top decile is never fetched, the fetched top one is redone instead."""
    seed, _ = seed_artists
    seed.similars_at = timezone.now() - timedelta(days=2)
    seed.save()

    update_next_similar_artist()

    similar_artists.assert_called_once_with('Seed Artist', SIMILARS_FETCH_LIMIT)


def test_update_similars_drops_former_seed(similar_artists, seed_artists):
    """An artist fallen out of the seeds loses its similars and is fetched anew if back."""
    _, owned = seed_artists
    _make_similar(owned, 'New Band', 0.3)
    Artist.objects.filter(id=owned.id).update(similars_at=timezone.now())

    update_next_similar_artist()

    assert Artist.objects.filter(similars__isnull=False).count() == 0
    assert Artist.objects.get(id=owned.id).similars_at is None


def test_update_similars_refetches_oldest_seed(similar_artists, seed_artists, monkeypatch):
    """Once every seed is fetched, the one fetched longest ago is fetched again."""
    monkeypatch.setattr('main.similars.SIMILARS_SEED_SHARE', 1)
    _, owned = seed_artists
    Artist.objects.update(similars_at=timezone.now() - timedelta(days=2))
    Artist.objects.filter(id=owned.id).update(similars_at=timezone.now() - timedelta(days=3))

    update_next_similar_artist()

    similar_artists.assert_called_once_with('Måneskin', SIMILARS_FETCH_LIMIT)


def test_update_similars_skips_refetch_within_interval(similar_artists, seed_artists):
    """Once every seed is fetched, nothing is redone within a day of the last fetch."""
    Artist.objects.update(similars_at=timezone.now() - timedelta(days=2))
    Artist.objects.filter(name='Seed Artist').update(similars_at=timezone.now())

    update_next_similar_artist()

    similar_artists.assert_not_called()


def test_update_similars_refetch_replaces_old_artists(similar_artists, seed_artists):
    """A refetch drops the seed's previous artists instead of adding duplicates."""
    seed, _ = seed_artists
    _make_similar(seed, 'New Band', 0.3)
    similar_artists.return_value = [('New Band', 0.5)]

    update_next_similar_artist()

    assert list(Similar.objects.values_list('match', flat=True)) == [0.5]


def test_update_similars_empty_library_skips_lastfm(similar_artists, db):
    """Nothing is fetched without artists."""
    update_next_similar_artist()

    similar_artists.assert_not_called()


def test_update_similars_disabled_skips_lastfm(similar_artists, settings, seed_songs):
    """Without last.fm credentials nothing is fetched."""
    settings.LASTFM_ENABLE = False

    update_next_similar_artist()

    similar_artists.assert_not_called()


@pytest.fixture()
def lastfm_top_albums():
    """Every artist's top album is '<artist> Album', except Empty Band, which has none."""
    with (
        patch('main.similars.get_artist_top_albums', autospec=True) as mock_albums,
        patch('main.similars.get_track_playcounts', autospec=True, return_value={}),
        patch('main.similars.get_album_tracks', autospec=True, return_value=[]),
        patch('main.similars.get_stand_out_tracks', autospec=True) as mock_tracks,
    ):
        mock_albums.side_effect = lambda name, limit: (
            [] if name == 'Empty Band' else [(f'{name} Album', 100, f'url-{name}')]
        )
        mock_tracks.return_value = [{'name': 'Hit', 'playcount': 500}]
        yield mock_albums


def test_recommended_album_cold_start(db):
    """Nothing is recommended before any similars are fetched."""
    assert get_recommended_album() is None


def test_recommended_album_sums_scores_across_albums(lastfm_top_albums, seed_artists):
    """Two weaker recommendations beat one strong one."""
    seed, owned = seed_artists
    _make_similar(seed, 'New Band', 0.3)
    _make_similar(owned, 'New Band', 0.4)
    _make_similar(seed, 'Solo Band', 0.6)

    assert get_recommended_album()['name'] == 'New Band Album'


def test_recommended_album_carries_stand_out_tracks(lastfm_top_albums, seed_artists):
    """The recommended album's stand-out tracks are shown with it."""
    seed, _ = seed_artists
    _make_similar(seed, 'New Band', 0.6)

    assert get_recommended_album()['tracks'] == [{'name': 'Hit', 'playcount': 500}]


def test_recommended_album_lists_library_artists_most_similar_first(
    lastfm_top_albums, seed_artists
):
    """The library artists that recommended the artist are listed by their match."""
    seed, owned = seed_artists
    _make_similar(seed, 'New Band', 0.3)
    _make_similar(owned, 'New Band', 0.4)

    assert get_recommended_album()['artists'] == [owned, seed]


def test_recommended_album_drops_artist_added_to_library(lastfm_top_albums, seed_artists):
    """An artist added since it was fetched is deleted, the next one is shown."""
    seed, _ = seed_artists
    _make_similar(seed, 'Maneskin', 0.9)
    _make_similar(seed, 'New Band', 0.3)

    get_recommended_album()

    assert list(Similar.objects.values_list('artist_slug', flat=True)) == ['new-band']


def test_recommended_album_skips_artist_without_albums(lastfm_top_albums, seed_artists):
    """An artist last.fm has no albums for is passed over."""
    seed, _ = seed_artists
    _make_similar(seed, 'Empty Band', 0.9)
    _make_similar(seed, 'New Band', 0.3)

    assert get_recommended_album()['artist_name'] == 'New Band'


@patch('main.views.update_next_similar_artist', autospec=True)
def test_recommended_view_requests_refresh_after_render(mock_update, rf, db):
    """The stored result renders without waiting on last.fm, then asks for the refresh."""
    response = similars_recommended_view(rf.get('/similars/recommended/'))

    mock_update.assert_not_called()
    assert 'hx-trigger="load"' in response.content.decode('utf-8')


@patch('main.views.update_next_similar_artist', autospec=True)
def test_recommended_view_refresh_updates_once(mock_update, rf, db):
    """The refresh fetches one artist and does not ask for another."""
    response = similars_recommended_view(rf.get('/similars/recommended/?refresh=1'))

    mock_update.assert_called_once()
    assert 'hx-trigger="load"' not in response.content.decode('utf-8')


@pytest.mark.parametrize(
    ('days_ago', 'shown'), [(0, '{:%H:%M:%S}'), (1, '{0.day} {0:%b %H:%M:%S}')]
)
@patch('main.views.update_next_similar_artist', autospec=True)
def test_recommended_view_shows_last_updated(mock_update, rf, seed_songs, days_ago, shown):
    """The time of the latest fetch is shown to the second, with the date only when not today."""
    similars_at = timezone.localtime() - timedelta(days=days_ago)
    Artist.objects.update(similars_at=similars_at)

    response = similars_recommended_view(rf.get('/similars/recommended/'))

    assert f'last updated: {shown.format(similars_at)}' in response.content.decode('utf-8')


@patch('main.views.update_next_similar_artist', autospec=True)
def test_recommended_view_shows_progress(mock_update, rf, seed_artists, monkeypatch):
    """During the first pass the number of fetched seeds is shown next to the time."""
    monkeypatch.setattr('main.similars.SIMILARS_SEED_SHARE', 1)
    _, owned = seed_artists
    owned.similars_at = timezone.now()
    owned.save()

    response = similars_recommended_view(rf.get('/similars/recommended/'))

    assert '(1/2)' in response.content.decode('utf-8')


@patch('main.views.update_next_similar_artist', autospec=True)
def test_recommended_view_shows_redone_seed(mock_update, rf, seed_artists, monkeypatch):
    """Once every seed is fetched, the place of the latest redone seed is shown."""
    monkeypatch.setattr('main.similars.SIMILARS_SEED_SHARE', 1)
    _, owned = seed_artists
    Artist.objects.update(similars_at=timezone.now() - timedelta(days=1))
    Artist.objects.filter(id=owned.id).update(similars_at=timezone.now())

    response = similars_recommended_view(rf.get('/similars/recommended/'))

    assert '(2 done - redid #2)' in response.content.decode('utf-8')


@patch('main.views.get_recommended_album', autospec=True)
def test_recommended_view_shows_lastfm_error(mock_album, rf, db):
    """A last.fm failure is shown in the column."""
    mock_album.side_effect = pylast.WSError(None, '8', 'Operation failed')

    response = similars_recommended_view(rf.get('/similars/recommended/'))

    assert 'Operation failed' in response.content.decode('utf-8')


def test_remove_artist_deletes_only_that_artist(rf, lastfm_top_albums, seed_artists):
    """Every row of the removed artist goes, and the next one is shown."""
    seed, owned = seed_artists
    _make_similar(seed, 'New Band', 0.4)
    _make_similar(owned, 'New Band', 0.3)
    _make_similar(seed, 'Solo Band', 0.6)

    response = similars_remove_artist(rf.get('/similars/recommended/remove/new-band/'), 'new-band')

    assert 'Solo Band Album' in response.content.decode('utf-8')


# more from artist: a new album with its best missing songs, else songs on owned albums


def test_lastfm_endpoints_return_plain_data(lastfm):
    """Top tracks, top albums and album tracks come back without pylast types."""
    artist = lastfm.get_artist.return_value
    artist.get_top_tracks.return_value = [
        pylast.TopItem(SimpleNamespace(title='Hit'), '12'),
    ]
    artist.get_top_albums.return_value = [
        pylast.TopItem(SimpleNamespace(title='Album', get_url=lambda: 'url'), '34'),
    ]
    lastfm.get_album.return_value.get_tracks.return_value = [SimpleNamespace(title='Hit')]
    lastfm.get_track.return_value.get_album.return_value = SimpleNamespace(
        get_title=lambda: 'Album', get_url=lambda: 'url'
    )

    fetched = (
        get_artist_top_tracks('Band', 5),
        get_artist_top_albums('Band', 5),
        get_album_tracks('Band', 'Album'),
        get_track_album('Band', 'Hit'),
    )

    assert fetched == ([('Hit', 12)], [('Album', 34, 'url')], ['Hit'], ('Album', 'url'))


def test_track_album_none_when_lastfm_has_none(lastfm):
    """A track last.fm puts on no album gives None."""
    lastfm.get_track.return_value.get_album.return_value = None

    assert get_track_album('Band', 'Hit') is None


@pytest.fixture()
def lastfm_missing():
    """Seed Artist on last.fm: Seed Album owned (as a deluxe edition), New Album not."""
    track_albums = {
        'Hit': ('Seed Album (Deluxe Edition)', 'url-seed'),
        'Deep Cut': ('New Album', 'url-new'),
        'Other': ('New Album', 'url-new'),
        'Filler': ('New Album', 'url-new'),
    }
    with (
        patch('main.discography.get_artist_top_tracks', autospec=True) as mock_tracks,
        patch('main.discography.get_track_album', autospec=True) as mock_track_album,
        patch('main.discography.get_album_tracks', autospec=True) as mock_album_tracks,
    ):
        mock_tracks.return_value = [
            ("Top Song's", 900),
            ('Hit', 500),
            ('Hit (Live)', 450),
            ('Deep Cut', 400),
            ('Other', 300),
            ('Filler', 10),
        ]
        mock_track_album.side_effect = lambda artist, title: track_albums[title]
        mock_album_tracks.side_effect = lambda artist, title: (
            ['Deep Cut'] if title == 'Single' else ['Deep Cut', 'Other', 'Filler', 'Unknown']
        )
        yield track_albums


def test_missing_songs_suggest_first_new_album(lastfm_missing, seed_songs):
    """Owned songs and albums are passed over; the new album leads with the song that found it."""
    top, _ = seed_songs

    assert get_missing_songs(top.artist) == {
        'album': {
            'name': 'New Album',
            'url': 'url-new',
            'tracks': [
                {'name': 'Deep Cut', 'playcount': 400},
                {'name': 'Other', 'playcount': 300},
            ],
        },
        'songs': [],
    }


def test_missing_songs_on_owned_albums_listed(lastfm_missing, seed_songs):
    """A single or no album is no new album; only the songs on owned albums are listed."""
    top, _ = seed_songs
    lastfm_missing['Deep Cut'] = ('Single', 'url-single')
    lastfm_missing['Other'] = None

    assert get_missing_songs(top.artist) == {
        'album': None,
        'songs': [{'name': 'Hit', 'playcount': 500, 'album': 'Seed Album (Deluxe Edition)'}],
    }


@patch('main.views.get_missing_songs', autospec=True, return_value={'album': None, 'songs': []})
def test_artist_albums_view_refresh_moves_to_next_artist(mock_albums, rf, seed_songs):
    """The artist is marked reviewed and the one reviewed longest ago after it is shown."""
    Artist.objects.filter(slug='maneskin').update(disco_at=timezone.now())

    response = similars_missing_albums_view(rf.get('/similars/missing_albums/?refresh=ad'))

    assert 'Måneskin' in response.content.decode('utf-8')


@patch('main.views.get_missing_songs', autospec=True, return_value={'album': None, 'songs': []})
def test_artist_albums_view_says_when_nothing_found(mock_albums, rf, seed_songs):
    """No albums left is stated, not left blank."""
    response = similars_missing_albums_view(rf.get('/similars/missing_albums/'))

    assert 'No other stand-out songs' in response.content.decode('utf-8')


@patch('main.views.get_missing_songs', autospec=True)
def test_artist_albums_view_shows_lastfm_error(mock_albums, rf, seed_songs):
    """A last.fm failure is shown in the column."""
    mock_albums.side_effect = pylast.WSError(None, '8', 'Operation failed')

    response = similars_missing_albums_view(rf.get('/similars/missing_albums/'))

    assert 'Operation failed' in response.content.decode('utf-8')


# get_next_song: skipping unplayed songs while the history window is short


def _make_song(
    slug: str, rating: float, count_played: int = 0, days_ago: int = 0, count_rated: int = 0
) -> Song:
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
        count_rated=count_rated,
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


def test_never_picks_excluded_songs(catalog):
    """Excluded ids (e.g. songs whose file is missing) are not candidates."""
    _play(catalog['history'], 1)

    assert get_next_song(exclude_ids=[catalog['played'].id]) != catalog['played']


def test_skips_new_songs_while_history_is_short(catalog):
    """A played song is picked over the higher priority unplayed ones."""
    _play(catalog['history'], 1)

    assert get_next_song() == catalog['played']


@patch('main.plays.NEXT_SONG_LOOKUP_LIMIT', 2)
def test_picks_new_song_when_all_candidates_are_new(catalog):
    """With nothing played to skip to, the top priority song wins as usual."""
    _play(catalog['history'], 1)

    assert get_next_song() == catalog['new']


@patch('main.plays.NUM_SLOTS_IN_WINDOW', 2)
@patch('main.plays.sa')
def test_falls_back_to_a_played_song_when_every_artist_is_queued(mock_sa, catalog):
    """The random fallback stays on played songs while new ones are skipped."""
    _play(catalog['played'], 1)
    History.objects.create(song=catalog['history'], played_at=timezone.now() - timedelta(days=1))

    assert get_next_song() in (catalog['played'], catalog['history'])


@patch('main.plays.NUM_SLOTS_IN_WINDOW', MIN_HISTORY_FOR_NEW_SONGS)
def test_skips_new_songs_when_history_is_only_outside_the_window(catalog):
    """Older plays filling the recent history do not count towards the window."""
    for days_ago in range(1, MIN_HISTORY_FOR_NEW_SONGS + 1):
        History.objects.create(
            song=catalog['history'], played_at=timezone.now() - timedelta(days=days_ago)
        )

    assert get_next_song() == catalog['played']


def test_skipped_new_songs_count_towards_next_artist_queue(catalog, caplog):
    """New songs skipped ahead of the picked artist still show as queued for it."""
    played = catalog['played']
    Song.objects.create(
        album=played.album,
        artist=played.artist,
        rel_path='played-2.mp3',
        slug='played-2',
        name='played-2',
        disc_number=1,
        track_number=2,
        track_length=240.0,
    )
    _play(catalog['history'], 1)

    with caplog.at_level('INFO', logger='main.plays'):
        get_next_song()

    assert '>>>>> played +' in caplog.messages


def test_picks_new_song_once_history_is_long_enough(catalog):
    """Once the window holds enough plays to rate, new songs are eligible again."""
    _play(catalog['history'], MIN_HISTORY_FOR_NEW_SONGS)

    assert get_next_song() == catalog['new']


@patch('main.plays.NUM_SLOTS_IN_WINDOW', 2)
def test_recent_artists_falls_back_to_latest_plays(catalog):
    """With the window empty, the latest slot-count plays are still returned."""
    History.objects.create(song=catalog['history'], played_at=timezone.now() - timedelta(days=1))
    History.objects.create(song=catalog['played'], played_at=timezone.now() - timedelta(days=2))
    History.objects.create(song=catalog['played'], played_at=timezone.now() - timedelta(days=3))

    assert [h.song for h in get_recent_artists()] == [catalog['history'], catalog['played']]


@patch('main.plays.NUM_SLOTS_IN_WINDOW', 1)
def test_recent_artists_uses_window_when_it_holds_enough(catalog):
    """A window holding at least the slot count returns every play in it."""
    _play(catalog['history'], 3)

    assert get_recent_artists().count() == 3


def test_countdown_extrapolates_from_two_points():
    """Two falling points are enough to fit a line down to zero."""
    assert _slope_steps_remaining([0.5, 0.4], 0.4) == 4


@patch('main.plays.NUM_SLOTS_IN_WINDOW', 10)
def test_countdown_shrinks_while_rising(catalog):
    """An unbounded estimate drops one point more than it adds."""
    caches['persistent'].set('add_album_countdown', [0.1] * 9, timeout=None)

    get_next_song()

    assert len(caches['persistent'].get('add_album_countdown')) == 8


@patch('main.plays.NUM_SLOTS_IN_WINDOW', 10)
@patch('main.plays.COUNTDOWN_ALPHA', 0.0)
@patch('main.plays.COUNTDOWN_ALPHA_RISING', 1.0)
def test_countdown_rises_with_faster_alpha(catalog):
    """A gate above the last smoothed point is followed with the rising alpha."""
    caches['persistent'].set('add_album_countdown', [0.0], timeout=None)

    get_next_song()

    # the normal alpha of 0 would have held it at 0
    assert caches['persistent'].get('add_album_countdown')[-1] > 0


@patch('main.plays.NUM_SLOTS_IN_WINDOW', 1)
def test_countdown_backlog_uses_only_the_highest_queued_slots(catalog, caplog):
    """A window holding more artists than slots averages only the top queue counts."""
    _play(catalog['history'], 1)
    _play(catalog['other_new'], 1)

    with caplog.at_level('INFO', logger='main.plays'):
        get_next_song()

    # backlog of 1 over 1 slot, less the 3 spaces per artist
    assert any('-> -2.00' in m for m in caplog.messages)


@patch('main.plays.NUM_SLOTS_IN_WINDOW', 10)
def test_countdown_grows_while_falling(catalog):
    """A falling estimate keeps every point and adds the new one."""
    caches['persistent'].set('add_album_countdown', [20.0] * 6, timeout=None)

    get_next_song()

    assert len(caches['persistent'].get('add_album_countdown')) == 7


# get_next_song: bumping the songs that keep a bad album struck through


def test_bumps_only_the_bad_album_song_short_of_a_fair_chance(db):
    """Both albums are listed as bad, but only the song short of ratings is bumped."""
    _make_song('fair', rating=0.9, count_played=3, count_rated=10, days_ago=10)
    short = _make_song('short', rating=0.5, count_played=3, count_rated=9, days_ago=10)

    assert get_next_song() == short


def test_bad_albums_are_held_for_the_ratings_window(db):
    """An album missing from the cached list is not bumped until the list expires."""
    fair = _make_song('fair', rating=0.9, count_played=3, count_rated=10, days_ago=10)
    get_next_song()
    _make_song('short', rating=0.5, count_played=3, count_rated=9, days_ago=10)

    assert get_next_song() == fair


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


# next_rating_view


def test_next_rating_missing_song_returns_message(client, db):
    """A session pointing at a deleted song renders a message instead of a 500."""
    session = client.session
    session['song_id'] = 999999
    session.save()

    response = client.get(reverse('next_rating'))

    assert response.content.startswith(b'<p>Song not found')


@patch('main.views.set_match_result', autospec=True)
def test_next_rating_winner_without_match_is_ignored(mock_set, client, editable_song):
    """A winner click after the matches ran out records nothing instead of crashing."""
    session = client.session
    session['song_id'] = editable_song.id
    session['match_ids'] = None
    session.save()

    response = client.get(reverse('next_rating'), {'winner_id': editable_song.id})

    assert response.status_code == 200
    mock_set.assert_not_called()


def test_next_rating_names_song_missing_from_match(client, editable_song):
    """A match song pruned before the click is named in the rating box."""
    session = client.session
    session['song_id'] = editable_song.id
    session['match_ids'] = [editable_song.id, 999999]
    session['match_names'] = [['Bad Title [HQ]', 'Edit Artist'], ['Dosed', 'RHCP']]
    session.save()

    response = client.get(reverse('next_rating'), {'winner_id': editable_song.id})

    assert '<span class="title-font">Dosed</span>' in response.content.decode('utf-8')


def test_parsemusic_validate_accepts_command_options(db):
    """The validate sub-command runs with the options Django passes to every command."""
    call_command('parsemusic', 'validate', '--no-delete')


# next_song_view: counting the previous play


@pytest.fixture()
def playing_session(client, editable_song):
    """A session with a song handed out to the player."""
    session = client.session
    session['song_id'] = editable_song.id
    session.save()
    return editable_song


@patch('main.views.Song.file_exists', autospec=True, return_value=True)
@patch('main.views.set_played', autospec=True)
def test_next_song_counts_previous_song(mock_played, mock_exists, client, playing_session):
    """Moving on from a song (ended or skipped) counts it, however long it was paused."""
    with patch('main.views.get_next_song', return_value=playing_session):
        client.get(reverse('next_song'))

    mock_played.assert_called_once_with(playing_session)


@patch('main.views.Song.file_exists', autospec=True, return_value=True)
@patch('main.views.set_played', autospec=True)
def test_next_song_ignores_previous_song_on_refresh(
    mock_played, mock_exists, client, playing_session
):
    """A page refresh does not count the song left over in the session."""
    with patch('main.views.get_next_song', return_value=playing_session):
        client.get(reverse('next_song'), {'refresh': '1'})

    mock_played.assert_not_called()


@patch('main.views.get_next_song', autospec=True)
def test_next_song_skips_missing_file_without_validating(mock_next, client, catalog):
    """A song whose file is gone is skipped and named in a warning, not deleted."""
    missing, present = catalog['new'], catalog['played']
    mock_next.side_effect = [missing, present]
    with patch('main.views.Song.file_exists', autospec=True, side_effect=lambda s: s == present):
        response = client.get(reverse('next_song'), {'refresh': '1'})

    mock_next.assert_called_with(exclude_ids=[missing.id])
    assert 'audio file not found' in response.content.decode()
    assert Song.objects.filter(id=missing.id).exists()


# scrobble: last.fm outages


@patch('main.lastfm_service.get_network', autospec=True)
def test_scrobble_swallows_lastfm_server_error(mock_network, settings, editable_song):
    """A 503 from last.fm is logged, not raised, so the next song still plays."""
    settings.LASTFM_ENABLE = True
    mock_network.return_value.scrobble.side_effect = pylast.WSError(
        None, 503, 'Connection to the API failed with HTTP code 503'
    )
    history = History.objects.create(song=editable_song, played_at=timezone.now())

    scrobble(history)


@pytest.mark.parametrize(('days', 'shown'), [(360, '{0.day} {0:%b}'), (400, "{0:%b '%y}")])
def test_days_ago_shows_month_and_year_after_360_days(days, shown):
    """Plays older than 360 days show the month and year instead of the day and month."""
    value = timezone.localtime() - timedelta(days=days)

    assert days_ago(value).endswith(f'({shown.format(value)})')
