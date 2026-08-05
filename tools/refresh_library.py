"""Keep the song library current. Meant to run weekly on a scheduler.

    python -m tools.refresh_library

Three independent steps. Each one logs and moves on if it fails, so a dead
source can't take the others down. Nothing here ever deletes a song.

  1. Add this week's Billboard Hot 100 entries
  2. Resolve audio for songs that don't have a preview yet
  3. Fill in genres for artists we haven't looked up

Every January, re-run tools/build_library.py for the year just finished: the
year-end list is the authoritative ranking and supersedes the weekly entries.
"""
import argparse
import logging
import os
import sys
from datetime import date, datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import library  # noqa: E402
from previews import EXPIRING_SOURCES, LookupFailed, find_preview  # noqa: E402

logging.basicConfig(stream=sys.stdout, level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)

PREVIEW_BATCH = 500     # Songs to resolve audio for per run
GENRE_BATCH = 200       # Artists to look up per run
COMMIT_EVERY = 50       # Save partial progress this often


def add_current_chart():
    """Add this week's Hot 100. New songs arrive with real chart data."""
    import billboard

    chart = billboard.ChartData('hot-100')
    logger.info(f'Billboard Hot 100 for {chart.date}: {len(chart)} entries')

    rows = []
    for entry in chart:
        year = int(str(chart.date)[:4])
        rows.append({
            'song': entry.title,
            'artist': entry.artist,
            'year': year,
            'decade': library.decade_for(year),
            'chart_peak': entry.peakPos,
            'weeks_on_chart': entry.weeks,
            'last_charted': str(chart.date),
        })

    written = library.upsert_songs(rows)
    logger.info(f'  {written} songs added or refreshed from the current chart')
    return written


def _songs_needing_audio(limit):
    with library.get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(library.sql(
            'SELECT song, artist FROM songs WHERE preview_checked_at IS NULL LIMIT ?'
        ), (limit,))
        rows = cursor.fetchall()

        if len(rows) < limit:
            # Top the batch up with the least recently checked
            cursor.execute(library.sql(
                'SELECT song, artist FROM songs WHERE preview_checked_at IS NOT NULL '
                'ORDER BY preview_checked_at ASC LIMIT ?'
            ), (limit - len(rows),))
            rows += cursor.fetchall()

    return rows


def resolve_audio(limit=PREVIEW_BATCH):
    """Find and store a preview for songs that don't have one."""
    candidates = _songs_needing_audio(limit)
    if not candidates:
        logger.info('Every song already has a resolved preview')
        return 0

    logger.info(f'Resolving audio for {len(candidates)} songs')
    checked_at = datetime.now()
    pending, found, checked, unreachable = [], 0, 0, 0

    def flush():
        if pending:
            library.upsert_songs(pending)
            pending.clear()
            logger.info(f'  {checked}/{len(candidates)} checked, {found} playable')

    for song, artist in candidates:
        try:
            preview, source, track_id = find_preview(song, artist)
        except LookupFailed as e:
            # Leave it unchecked so a later run retries. Recording this as
            # "no preview" would blacklist the song over a network blip.
            unreachable += 1
            logger.warning(f'  skipped {artist} - {song}: {e}')
            continue

        if preview:
            found += 1
        checked += 1
        pending.append({
            'song': song,
            'artist': artist,
            # Deezer links expire within minutes, so only the id is worth
            # keeping - the app fetches a fresh link when the song comes up.
            'preview_url': None if source in EXPIRING_SOURCES else preview,
            'preview_source': source,
            'preview_id': track_id,
            'preview_checked_at': checked_at,
            'playable': bool(preview),
        })

        # Write as we go. A long run that only saved at the end would bank
        # nothing if it were interrupted, and the app couldn't use any of it
        # until the whole library was done.
        if len(pending) >= COMMIT_EVERY:
            flush()

    flush()
    logger.info(f'  {found} of {checked} checked are playable'
                + (f'; {unreachable} skipped as unreachable' if unreachable else ''))
    return found


def _artists_needing_genres(limit):
    with library.get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(library.sql(
            "SELECT DISTINCT artist FROM songs "
            "WHERE genres IS NULL OR genres = '' LIMIT ?"
        ), (limit,))
        return [row[0] for row in cursor.fetchall()]


def fill_genres(limit=GENRE_BATCH):
    """Look up genres for artists we don't have any for."""
    artists = _artists_needing_genres(limit)
    if not artists:
        logger.info('Every artist already has genres')
        return 0

    from genres import clean_artist_name, get_artist_genres_lastfm

    logger.info(f'Looking up genres for {len(artists)} artists')
    rows, found = [], 0

    for artist in artists:
        try:
            genres = get_artist_genres_lastfm(clean_artist_name(artist))
        except Exception as e:
            logger.warning(f'  {artist}: {e}')
            continue
        if not genres:
            continue
        found += 1
        with library.get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                library.sql('UPDATE songs SET genres = ? WHERE artist = ?'),
                (','.join(genres), artist),
            )
            conn.commit()

    logger.info(f'  resolved {found} of {len(artists)} artists')
    return found


def library_summary():
    counts = {}
    queries = {
        'total': 'SELECT COUNT(*) FROM songs',
        'playable': 'SELECT COUNT(*) FROM songs WHERE playable IS TRUE',
        'unplayable': 'SELECT COUNT(*) FROM songs WHERE playable IS FALSE',
        'unchecked': 'SELECT COUNT(*) FROM songs WHERE preview_checked_at IS NULL',
        'with_genres': "SELECT COUNT(*) FROM songs "
                       "WHERE genres IS NOT NULL AND genres <> ''",
    }
    with library.get_db() as conn:
        cursor = conn.cursor()
        for name, query in queries.items():
            cursor.execute(query)
            counts[name] = cursor.fetchone()[0]
    return counts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--preview-batch', type=int, default=PREVIEW_BATCH)
    parser.add_argument('--genre-batch', type=int, default=GENRE_BATCH)
    parser.add_argument('--skip-chart', action='store_true')
    args = parser.parse_args()

    logger.info(f'Refreshing the song library - {date.today()}')
    library.init_songs_table()

    steps = []
    if not args.skip_chart:
        steps.append(('current chart', lambda: add_current_chart()))
    steps.append(('audio', lambda: resolve_audio(args.preview_batch)))
    steps.append(('genres', lambda: fill_genres(args.genre_batch)))

    for name, step in steps:
        try:
            step()
        except Exception as e:
            # A dead source must not stop the other steps
            logger.warning(f'Step "{name}" failed, continuing: {e}')

    c = library_summary()
    logger.info(f"\nLibrary: {c['total']} songs | audio: {c['playable']} playable, "
                f"{c['unplayable']} with none, {c['unchecked']} not yet checked "
                f"| {c['with_genres']} with genres")


if __name__ == '__main__':
    main()
