"""The song library.

Lives in Postgres when DATABASE_URL is set, so a scheduled job has somewhere to
write - Heroku wipes the dyno disk on restart. Falls back to the CSV for local
runs and tests.

`load_songs()` returns the DataFrame shape app.py already expects: Song, Artist,
Year, Decade, Genres, plus PreviewUrl when the library has one stored.
"""
import logging
import os
import sqlite3
from contextlib import contextmanager

import pandas as pd

from exclusions import is_excluded

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CSV_FILE = os.path.join(BASE_DIR, 'updated_spotify_data_new.csv')
FALLBACK_CSV_FILE = os.path.join(BASE_DIR, 'billboard_lyrics_1964-2015.csv')
SQLITE_PATH = os.environ.get('SCORES_DB', os.path.join(BASE_DIR, 'scores.db'))

DATABASE_URL = os.environ.get('DATABASE_URL', '')
if DATABASE_URL.startswith('postgres://'):
    # Heroku still hands out the legacy scheme; psycopg2 wants the modern one
    DATABASE_URL = 'postgresql://' + DATABASE_URL[len('postgres://'):]
USE_POSTGRES = DATABASE_URL.startswith('postgresql://')

if USE_POSTGRES:
    import psycopg2


def sql(query):
    """Queries are written with SQLite '?' placeholders; Postgres wants '%s'."""
    return query.replace('?', '%s') if USE_POSTGRES else query


@contextmanager
def get_db():
    conn = psycopg2.connect(DATABASE_URL) if USE_POSTGRES else sqlite3.connect(SQLITE_PATH)
    try:
        yield conn
    finally:
        conn.close()


SONGS_SCHEMA = '''
CREATE TABLE IF NOT EXISTS songs (
    {id_column},
    song TEXT NOT NULL,
    artist TEXT NOT NULL,
    year INTEGER NOT NULL,
    decade TEXT NOT NULL,
    genres TEXT,
    year_end_rank INTEGER,
    chart_peak INTEGER,
    weeks_on_chart INTEGER,
    last_charted DATE,
    preview_url TEXT,
    preview_source TEXT,
    preview_id TEXT,
    preview_checked_at TIMESTAMP,
    playable BOOLEAN,
    UNIQUE (song, artist)
)
'''


# Columns added after the table first shipped, so existing databases get them
LATER_COLUMNS = {'preview_id': 'TEXT'}


def _existing_columns(cursor):
    if USE_POSTGRES:
        cursor.execute("SELECT column_name FROM information_schema.columns "
                       "WHERE table_name = 'songs'")
        return {row[0] for row in cursor.fetchall()}
    cursor.execute('PRAGMA table_info(songs)')
    return {row[1] for row in cursor.fetchall()}


def init_songs_table():
    id_column = ('id SERIAL PRIMARY KEY' if USE_POSTGRES
                 else 'id INTEGER PRIMARY KEY AUTOINCREMENT')
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(SONGS_SCHEMA.format(id_column=id_column))

        present = _existing_columns(cursor)
        for column, column_type in LATER_COLUMNS.items():
            if column not in present:
                cursor.execute(f'ALTER TABLE songs ADD COLUMN {column} {column_type}')
                logger.info(f'Added missing column songs.{column}')

        conn.commit()


def songs_table_exists():
    """True when the library table is present and has rows."""
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT COUNT(*) FROM songs')
            return cursor.fetchone()[0] > 0
    except Exception:
        return False


def decade_for(year):
    return f'{(int(year) // 10) * 10}s'


COLUMNS = ['song', 'artist', 'year', 'decade', 'genres', 'year_end_rank',
           'chart_peak', 'weeks_on_chart', 'last_charted', 'preview_url',
           'preview_source', 'preview_id', 'preview_checked_at', 'playable']

# A row can only be inserted if it carries everything the schema requires
REQUIRED = ('song', 'artist', 'year', 'decade')


def upsert_songs(rows):
    """Insert or update songs, keyed on (song, artist). Never deletes.

    `rows` is a list of dicts. Only the keys present are written, so an audio
    pass doesn't wipe chart data and vice versa.

    Rows carrying the required columns are inserted or merged. Partial rows -
    an audio or genre pass, say - are updates only: Postgres checks NOT NULL
    before ON CONFLICT can resolve, so they can't go through an insert.
    """
    if not rows:
        return 0

    written = 0
    with get_db() as conn:
        cursor = conn.cursor()
        for row in rows:
            present = [c for c in COLUMNS if c in row]
            updatable = [c for c in present if c not in ('song', 'artist')]

            if all(c in row for c in REQUIRED):
                placeholders = ', '.join('?' for _ in present)
                updates = ', '.join(f'{c} = excluded.{c}' for c in updatable)
                statement = (
                    f"INSERT INTO songs ({', '.join(present)}) "
                    f"VALUES ({placeholders}) ON CONFLICT (song, artist) "
                    + (f"DO UPDATE SET {updates}" if updates else "DO NOTHING")
                )
                cursor.execute(sql(statement), [row[c] for c in present])
            elif updatable:
                assignments = ', '.join(f'{c} = ?' for c in updatable)
                cursor.execute(
                    sql(f'UPDATE songs SET {assignments} '
                        f'WHERE song = ? AND artist = ?'),
                    [row[c] for c in updatable] + [row['song'], row['artist']],
                )
            else:
                continue

            written += 1
        conn.commit()

    return written


def _load_from_csv():
    for path, encoding in ((CSV_FILE, 'utf-8'), (FALLBACK_CSV_FILE, 'latin1')):
        try:
            df = pd.read_csv(path, encoding=encoding)
            logger.info(f'Loaded {len(df)} songs from {os.path.basename(path)}')
            return df
        except Exception as e:
            logger.error(f'Could not load {path}: {e}')
    return None


def _load_from_postgres():
    columns = ['song', 'artist', 'year', 'decade', 'genres', 'year_end_rank',
               'preview_url', 'preview_source', 'preview_id', 'playable']
    # A plain cursor rather than pandas.read_sql_query, which only officially
    # supports SQLAlchemy connectables and warns about a raw DBAPI connection
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(f"SELECT {', '.join(columns)} FROM songs")
        df = pd.DataFrame(cursor.fetchall(), columns=columns)

    # A song with no preview can never be a round, so keep it out of play.
    # Not yet checked (NULL) still counts as fair game.
    playable = df['playable'].apply(lambda v: True if pd.isna(v) else bool(v))
    excluded = int((~playable).sum())
    if excluded:
        logger.info(f'Excluded {excluded} songs with no preview')
    df = df[playable]

    return df.rename(columns={
        'song': 'Song',
        'artist': 'Artist',
        'year': 'Year',
        'decade': 'Decade',
        'genres': 'Genres',
        'year_end_rank': 'Rank',
        'preview_url': 'PreviewUrl',
        'preview_source': 'PreviewSource',
        'preview_id': 'PreviewId',
    })


def _drop_excluded_artists(df):
    """Remove artists held out of the quiz. See exclusions.py."""
    if df is None or df.empty or 'Artist' not in df.columns:
        return df

    years = pd.to_numeric(df.get('Year'), errors='coerce')
    excluded = [
        is_excluded(artist, None if pd.isna(year) else year)
        for artist, year in zip(df['Artist'], years)
    ]

    dropped = sum(excluded)
    if dropped:
        logger.info(f'Excluded {dropped} songs by held-out artists')

    return df[[not flag for flag in excluded]]


def load_songs():
    """Load the library from whichever backend is configured."""
    if USE_POSTGRES and songs_table_exists():
        logger.info('Loading song library from Postgres')
        return _drop_excluded_artists(_load_from_postgres())

    if USE_POSTGRES:
        logger.warning('Postgres has no song library yet - falling back to the CSV. '
                       'Run tools/build_library.py to populate it.')

    return _drop_excluded_artists(_load_from_csv())
