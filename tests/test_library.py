"""Tests for the song library storage and the refresh job.

These run against SQLite, which takes the same code path as Postgres apart from
the placeholder style. No network: the chart and preview lookups are stubbed.
"""
import os
import sys
import tempfile
from datetime import datetime

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault('SCORES_DB', os.path.join(tempfile.mkdtemp(), 'library_test.db'))

import library  # noqa: E402
from tools import refresh_library  # noqa: E402


@pytest.fixture
def db():
    """A fresh, empty songs table."""
    library.init_songs_table()
    with library.get_db() as conn:
        conn.cursor().execute('DELETE FROM songs')
        conn.commit()
    yield library


def song_row(song='Careless Whisper', artist='George Michael', year=1985, **extra):
    row = {
        'song': song,
        'artist': artist,
        'year': year,
        'decade': library.decade_for(year),
    }
    row.update(extra)
    return row


def fetch(song, artist):
    with library.get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(library.sql(
            'SELECT year, genres, year_end_rank, preview_url, preview_source, '
            'playable, chart_peak FROM songs WHERE song = ? AND artist = ?'
        ), (song, artist))
        return cursor.fetchone()


def count():
    with library.get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM songs')
        return cursor.fetchone()[0]


# --- Writing -----------------------------------------------------------------

def test_insert_and_read_back(db):
    library.upsert_songs([song_row(year_end_rank=1, genres='pop')])

    year, genres, rank, _url, _src, _playable, _peak = fetch(
        'Careless Whisper', 'George Michael')
    assert (year, genres, rank) == (1985, 'pop', 1)


def test_reinserting_the_same_song_does_not_duplicate(db):
    library.upsert_songs([song_row(year_end_rank=1)])
    library.upsert_songs([song_row(year_end_rank=1)])

    assert count() == 1


def test_partial_update_keeps_the_other_columns(db):
    """An audio pass must not wipe chart data."""
    library.upsert_songs([song_row(year_end_rank=1, genres='pop')])

    library.upsert_songs([{
        'song': 'Careless Whisper',
        'artist': 'George Michael',
        'preview_url': 'https://example.invalid/a.mp3',
        'preview_source': 'deezer',
        'preview_checked_at': datetime.now(),
        'playable': True,
    }])

    year, genres, rank, url, source, playable, _peak = fetch(
        'Careless Whisper', 'George Michael')
    assert (year, genres, rank) == (1985, 'pop', 1)  # untouched
    assert url == 'https://example.invalid/a.mp3'
    assert source == 'deezer'
    assert playable


def test_partial_row_for_an_unknown_song_is_ignored(db):
    """Audio-only rows are updates; they must not create half-empty songs."""
    library.upsert_songs([{
        'song': 'Never Seen', 'artist': 'Nobody', 'preview_url': 'x', 'playable': True,
    }])

    assert count() == 0


def test_chart_data_does_not_clobber_the_year_end_rank(db):
    library.upsert_songs([song_row(year_end_rank=1)])
    library.upsert_songs([song_row(chart_peak=3, weeks_on_chart=20)])

    _year, _genres, rank, _url, _src, _playable, peak = fetch(
        'Careless Whisper', 'George Michael')
    assert rank == 1
    assert peak == 3


def test_empty_write_is_a_no_op(db):
    assert library.upsert_songs([]) == 0


def test_decade_for():
    assert library.decade_for(1985) == '1980s'
    assert library.decade_for(2020) == '2020s'
    assert library.decade_for(1960) == '1960s'


# --- Reading into the quiz ---------------------------------------------------

def test_unplayable_songs_are_never_loaded(db):
    library.upsert_songs([
        song_row('Playable', 'A', playable=True, preview_url='https://x/a.mp3'),
        song_row('No Audio', 'B', playable=False),
        song_row('Unchecked', 'C'),
    ])

    df = library._load_from_postgres()

    songs = set(df['Song'])
    assert 'Playable' in songs
    assert 'No Audio' not in songs
    assert 'Unchecked' in songs  # not yet checked, so still fair game


def test_loaded_columns_match_what_the_app_expects(db):
    library.upsert_songs([song_row(genres='pop', year_end_rank=1,
                                   preview_url='https://x/a.mp3')])

    df = library._load_from_postgres()

    for column in ('Song', 'Artist', 'Year', 'Decade', 'Genres', 'PreviewUrl'):
        assert column in df.columns


# --- The refresh job ---------------------------------------------------------

class FakeEntry:
    def __init__(self, title, artist, peak, weeks):
        self.title, self.artist = title, artist
        self.peakPos, self.weeks = peak, weeks


class FakeChart(list):
    date = '2026-08-08'


def fake_billboard(entries):
    chart = FakeChart(entries)
    module = type(sys)('billboard')
    module.ChartData = lambda name: chart
    return module


def test_current_chart_adds_songs(db, monkeypatch):
    monkeypatch.setitem(sys.modules, 'billboard', fake_billboard([
        FakeEntry('Golden', 'HUNTR/X', 1, 12),
        FakeEntry('Ordinary', 'Alex Warren', 2, 30),
    ]))

    refresh_library.add_current_chart()

    assert count() == 2
    _year, _g, _r, _u, _s, _p, peak = fetch('Golden', 'HUNTR/X')
    assert peak == 1


def test_running_the_chart_step_twice_does_not_duplicate(db, monkeypatch):
    monkeypatch.setitem(sys.modules, 'billboard', fake_billboard([
        FakeEntry('Golden', 'HUNTR/X', 1, 12),
    ]))

    refresh_library.add_current_chart()
    refresh_library.add_current_chart()

    assert count() == 1


def test_audio_step_marks_songs_with_no_preview(db, monkeypatch):
    library.upsert_songs([
        song_row('Has Audio', 'A'),
        song_row('No Audio', 'B'),
    ])
    monkeypatch.setattr(
        refresh_library, 'find_preview',
        lambda song, artist: (('https://x/a.mp3', 'deezer')
                              if song == 'Has Audio' else (None, None)))

    found = refresh_library.resolve_audio(limit=10)

    assert found == 1
    assert fetch('Has Audio', 'A')[5]      # playable
    assert not fetch('No Audio', 'B')[5]


def test_audio_step_prefers_unchecked_songs(db, monkeypatch):
    library.upsert_songs([song_row('Checked', 'A', preview_checked_at=datetime.now(),
                                   playable=True, preview_url='https://x/a.mp3')])
    library.upsert_songs([song_row('Unchecked', 'B')])

    asked = []
    monkeypatch.setattr(refresh_library, 'find_preview',
                        lambda song, artist: (asked.append(song),
                                              ('https://x/b.mp3', 'deezer'))[1])

    refresh_library.resolve_audio(limit=1)
    assert asked == ['Unchecked']


def test_a_failing_step_does_not_stop_the_others(db, monkeypatch, caplog):
    """A dead source must not take the rest of the job down."""
    library.upsert_songs([song_row('Needs Audio', 'A')])

    def explode(name):
        raise RuntimeError('billboard is down')

    module = type(sys)('billboard')
    module.ChartData = explode
    monkeypatch.setitem(sys.modules, 'billboard', module)
    monkeypatch.setattr(refresh_library, 'find_preview',
                        lambda song, artist: ('https://x/a.mp3', 'deezer'))
    monkeypatch.setattr(sys, 'argv', ['refresh_library', '--genre-batch', '0'])

    refresh_library.main()

    # The chart step failed, but the audio step still ran
    assert fetch('Needs Audio', 'A')[5]
    assert 'failed, continuing' in caplog.text


def test_summary_counts(db):
    library.upsert_songs([
        song_row('A', 'A', playable=True, genres='pop'),
        song_row('B', 'B', playable=False),
        song_row('C', 'C'),
    ])

    counts = refresh_library.library_summary()

    assert counts['total'] == 3
    assert counts['playable'] == 1
    assert counts['unplayable'] == 1
    assert counts['unchecked'] == 3
    assert counts['with_genres'] == 1
