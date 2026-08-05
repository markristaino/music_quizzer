# Music Quiz Web App

A web-based music quiz that plays song previews and challenges you to name the artist.

## Features

- Song previews filtered by genre and decade
- Six songs per game, with a top-10 leaderboard
- Answers are checked on the server, so they never reach the browser
- Uses the Deezer API for previews

## Local Development

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Run the app:
```bash
python app.py
```

3. Visit `http://localhost:8080` in your browser

Set `FLASK_DEBUG=1` for the reloader and debugger. Running `app.py` directly sends
session cookies over plain HTTP; deployments get secure cookies by default.

## Tests

```bash
pip install -r requirements-tools.txt
python -m pytest tests/
```

Deezer lookups are stubbed, so the tests run without network access.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `SECRET_KEY` | random per boot | Signs session cookies. **Set this in production** — without it, every restart logs everyone out. |
| `PORT` | `8080` | Port to bind |
| `SCORES_DB` | `scores.db` next to `app.py` | SQLite leaderboard path |
| `SESSION_COOKIE_SECURE` | on, except when running `app.py` directly | Require HTTPS for session cookies |
| `FLASK_DEBUG` | off | Flask debug mode (local only) |

## Deployment

Deployed to Heroku from the `main` branch (`Procfile` runs gunicorn).

Note: the leaderboard is SQLite on the dyno's local disk, which Heroku wipes on every
restart. Scores do not survive a redeploy.

## Data

`updated_spotify_data_new.csv` is the dataset the app reads at startup.
`billboard_lyrics_1964-2015.csv` is the fallback and the input for the offline scripts
(`billboard_updater.py`, `spotify_songs.py`, `analyze_songs.py`, `filter_obscure_songs.py`),
which need `requirements-tools.txt`.

## Technologies Used

- Flask (Python web framework)
- Deezer API (music previews)
- Bootstrap (UI framework)
- HTML5 Audio API
- Pandas (data handling)
