"""Build the song library from Billboard Year-End Hot 100 charts.

Every song that lands here was a top-100 song of its year. Nothing enters any
other way.

    python -m tools.build_library                  # 1960 to last year, with genres
    python -m tools.build_library --no-genres      # skip the Last.fm pass
    python -m tools.build_library --years 2024 2025

Genres come from the old CSV where possible - it already covers most of these
artists - and from Last.fm only for the ones it doesn't.
"""
import argparse
import logging
import sys
import time
from datetime import datetime

sys.path.insert(0, __import__('os').path.dirname(
    __import__('os').path.dirname(__import__('os').path.abspath(__file__))))

import library  # noqa: E402
from tools.wikipedia_charts import fetch_year_end  # noqa: E402

logging.basicConfig(stream=sys.stdout, level=logging.INFO,
                    format='%(message)s')
logger = logging.getLogger(__name__)

FIRST_CHART_YEAR = 1960
REQUEST_PAUSE = 0.2  # Be polite to Wikipedia


def normalise(value):
    return ' '.join(str(value).lower().split())


def collect_entries(years):
    """Fetch each year, keeping the earliest appearance and best rank per song."""
    songs = {}
    failures = []

    for year in years:
        try:
            entries = fetch_year_end(year)
        except Exception as e:
            logger.warning(f'{year}: skipped - {e}')
            failures.append(year)
            continue

        for entry in entries:
            key = (normalise(entry['song']), normalise(entry['artist']))
            existing = songs.get(key)
            if existing is None or entry['rank'] < existing['rank']:
                # A hit can chart in two consecutive years. Credit it to the
                # year it placed highest, keeping year and rank consistent -
                # taking the best rank but the earliest year would file a 2022
                # number one under 2021.
                songs[key] = dict(entry)

        time.sleep(REQUEST_PAUSE)

    return songs, failures


def genre_map_from_csv():
    """Artist -> genres, taken from the old CSV so we don't re-query Last.fm."""
    try:
        import pandas as pd
        df = pd.read_csv(library.CSV_FILE)
    except Exception as e:
        logger.warning(f'No CSV genre data available: {e}')
        return {}

    mapping = {}
    for artist, genres in zip(df['Artist'], df['Genres']):
        if isinstance(genres, str) and genres.strip():
            mapping.setdefault(normalise(artist), genres.strip().lower())

    logger.info(f'Genre map from CSV covers {len(mapping)} artists')
    return mapping


def fill_missing_genres(songs, mapping):
    """Look up artists the CSV didn't cover, via Last.fm."""
    from genres import clean_artist_name, get_artist_genres_lastfm

    unknown = sorted({
        clean_artist_name(entry['artist'])
        for entry in songs.values()
        if normalise(entry['artist']) not in mapping
    })
    logger.info(f'Looking up {len(unknown)} artists on Last.fm')

    found = 0
    for name in unknown:
        try:
            genres = get_artist_genres_lastfm(name)
        except Exception as e:
            logger.warning(f'  {name}: {e}')
            continue
        if genres:
            mapping[normalise(name)] = ','.join(genres)
            found += 1

    logger.info(f'Last.fm resolved {found} of {len(unknown)} artists')
    return mapping


def genres_for(artist, mapping):
    from genres import clean_artist_name

    return (mapping.get(normalise(artist))
            or mapping.get(normalise(clean_artist_name(artist))))


def build(years, with_genres=True, dry_run=False, replace=False):
    songs, failures = collect_entries(years)
    logger.info(f'\n{len(songs)} unique songs from {len(years) - len(failures)} years')

    mapping = genre_map_from_csv()
    if with_genres:
        mapping = fill_missing_genres(songs, mapping)

    rows = []
    for entry in songs.values():
        rows.append({
            'song': entry['song'],
            'artist': entry['artist'],
            'year': entry['year'],
            'decade': library.decade_for(entry['year']),
            'genres': genres_for(entry['artist'], mapping),
            'year_end_rank': entry['rank'],
        })

    with_genre_count = sum(1 for r in rows if r['genres'])
    logger.info(f'{with_genre_count} of {len(rows)} songs have genres')

    by_decade = {}
    for row in rows:
        by_decade[row['decade']] = by_decade.get(row['decade'], 0) + 1
    logger.info('Songs per decade: '
                + ', '.join(f'{d}={by_decade[d]}' for d in sorted(by_decade)))

    if dry_run:
        logger.info('\nDry run - nothing written')
        return rows

    library.init_songs_table()

    if replace:
        # Songs are keyed on (song, artist), so a corrected artist inserts a new
        # row and orphans the old one. Clearing what this build owns - year-end
        # entries - is the only way to retire those. Weekly chart additions,
        # which have no year_end_rank, are left alone.
        with library.get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM songs WHERE year_end_rank IS NOT NULL')
            removed = cursor.rowcount
            conn.commit()
        logger.info(f'Replaced: cleared {removed} existing year-end songs')

    written = library.upsert_songs(rows)
    logger.info(f'\nWrote {written} songs to '
                f"{'Postgres' if library.USE_POSTGRES else library.SQLITE_PATH}")

    if failures:
        logger.warning(f'Years that failed and are missing: {failures}')

    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--years', nargs='+', type=int,
                        help='Specific years (default: 1960 to last year)')
    parser.add_argument('--no-genres', action='store_true',
                        help='Skip the Last.fm genre lookup')
    parser.add_argument('--dry-run', action='store_true',
                        help='Parse and report without writing')
    parser.add_argument('--replace', action='store_true',
                        help='Clear existing year-end songs first, so corrected '
                             'artists replace old rows instead of duplicating them')
    args = parser.parse_args()

    years = args.years or list(range(FIRST_CHART_YEAR, datetime.now().year))
    build(years, with_genres=not args.no_genres, dry_run=args.dry_run,
          replace=args.replace)


if __name__ == '__main__':
    main()
