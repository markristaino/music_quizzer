# Music Quiz Web App

A web-based music quiz that plays song previews and challenges you to name the artist.

## Features

- Every song in the library was a Billboard year-end top-100 hit for its year
- Filter by genre and decade; six songs per game, with a top-10 leaderboard
- Answers are checked on the server, so they never reach the browser
- The library refreshes itself weekly from the current chart

## The song library

Songs come from the Billboard Year-End Hot 100, 1960 to last year — about 6,300
after removing hits that charted in two consecutive years. Billboard's own
year-end pages return 403, so the lists are read from Wikipedia, which mirrors
them.

Nothing enters the library any other way. That is the whole relevance rule: if a
song wasn't a top-100 song of its year, it isn't in the quiz.

Each song also carries its year-end rank, so tightening the quiz to, say, the top
40 of each year is a filter change rather than a rebuild.

### Building it

Needs `DATABASE_URL` pointing at Postgres. Run once:

```bash
python -m tools.build_library
```

Add `--no-genres` to skip the Last.fm pass (much faster), `--dry-run` to parse
and report without writing, or `--years 2024 2025` for specific years.

### Keeping it current

```bash
python -m tools.refresh_library
```

Three independent steps — a failure in one is logged and the others still run,
and nothing is ever deleted:

1. Adds this week's Billboard Hot 100 entries, with their peak position
2. Resolves audio for songs that don't have a preview yet (500 per run)
3. Fills in genres for artists not yet looked up (200 per run)

Each January, re-run `tools.build_library` for the year just finished — the
year-end list is the authoritative ranking and supersedes the weekly entries.

### Where audio comes from

Deezer first, then Apple's iTunes Search API. Both are unauthenticated. Neither
has any say in what's in the library; they only answer whether a song can be
played. A song neither can serve is flagged and never picked, so a round can't
fail mid-game.

## Local Development

```bash
pip install -r requirements.txt
python app.py
```

Then open http://localhost:8080.

Without `DATABASE_URL` the app reads `updated_spotify_data_new.csv` instead, so
it runs with no database. The CSV is the old library — kept as a fallback and as
a genre lookup for the build script.

## Tests

```bash
pip install -r requirements-tools.txt
python -m pytest tests/
```

No network: chart pages, previews and Last.fm are all stubbed.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `SECRET_KEY` | random per boot | Signs session cookies. **Set this in production** — without it, every restart logs everyone out. |
| `DATABASE_URL` | unset | Postgres, holding both the song library and the leaderboard. Unset falls back to the CSV and local SQLite. |
| `PORT` | `8080` | Port to bind |
| `SCORES_DB` | `scores.db` next to `app.py` | SQLite path (ignored when `DATABASE_URL` is set) |
| `SESSION_COOKIE_SECURE` | on, except when running `app.py` directly | Require HTTPS for session cookies |
| `LASTFM_API_KEY` / `LASTFM_API_SECRET` | built-in | Genre lookups |
| `FLASK_DEBUG` | off | Flask debug mode (local only) |

## Deployment

Deployed to Heroku from the `main` branch (`Procfile` runs gunicorn).

Postgres is required — Heroku wipes the dyno's disk on every restart, so both the
leaderboard and the self-updating library need somewhere real to live.

```bash
heroku addons:create heroku-postgresql:essential-0
heroku config:set SECRET_KEY="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
heroku run python -m tools.build_library          # one time, ~10 minutes
```

Then add the weekly refresh:

```bash
heroku addons:create scheduler:standard
heroku addons:open scheduler   # add: python -m tools.refresh_library, weekly
```

## Technologies Used

- Flask (Python web framework)
- Postgres (song library and leaderboard)
- Billboard year-end charts via Wikipedia (what's in the library)
- Deezer and iTunes Search (audio previews)
- Last.fm (genres)
- Bootstrap, HTML5 Audio API, Pandas
