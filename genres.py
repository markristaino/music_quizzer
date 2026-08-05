"""Genre lookups, via Last.fm's top tags for an artist.

This was spotify_songs.py, which was a misleading name - there is no Spotify
here, and its credentials stopped working. Last.fm's tags are what the quiz's
genre filter has actually been built from.
"""
import logging
import os
import time
from threading import Lock

import pylast

logger = logging.getLogger(__name__)

API_KEY = os.environ.get('LASTFM_API_KEY', '0243f85294f0317b7bf2dcce8ff639e1')
API_SECRET = os.environ.get('LASTFM_API_SECRET', 'f40c2aeec15941f9c7fd18ae1b7254a1')

network = pylast.LastFMNetwork(api_key=API_KEY, api_secret=API_SECRET)

MIN_REQUEST_INTERVAL = 0.2  # 5 requests per second
MIN_TAG_WEIGHT = 25         # Tags below this are noise

# Tags people apply that aren't genres
NOT_GENRES = {
    'seen live', 'favourite', 'favorite', 'spotify', 'under 2000 listeners',
    'albums i own', 'my music', 'awesome', 'love', 'best',
}

_rate_limit_lock = Lock()
_last_request_time = 0.0


def _rate_limited(func, *args, **kwargs):
    """Space out calls so we stay inside Last.fm's rate limit."""
    global _last_request_time

    with _rate_limit_lock:
        elapsed = time.time() - _last_request_time
        if elapsed < MIN_REQUEST_INTERVAL:
            time.sleep(MIN_REQUEST_INTERVAL - elapsed)
        _last_request_time = time.time()

    return func(*args, **kwargs)


def clean_artist_name(artist):
    """Reduce a credit to the primary artist.

    "Ciara featuring Missy Elliott" -> "ciara"
    """
    featured_indicators = [
        'featuring', 'feat.', 'feat', 'ft.', 'ft', 'with',
        ' & ', ' x ', ' vs. ', ' vs ', ' presents ', ' pres. ',
    ]

    artist = str(artist).lower().strip()
    for separator in featured_indicators:
        if separator in artist:
            artist = artist.split(separator)[0]
            break  # Stop at the first match to avoid over-splitting

    return artist.strip()


def get_artist_genres_lastfm(artist_name):
    """Return an artist's genres, strongest tags first. Empty list if unknown."""
    try:
        artist = _rate_limited(network.get_artist, artist_name)
        tags = _rate_limited(artist.get_top_tags, limit=10)
    except pylast.WSError as e:
        if 'could not be found' not in str(e):
            logger.warning(f'Last.fm error for {artist_name}: {e}')
        return []
    except Exception as e:
        logger.warning(f'Last.fm lookup failed for {artist_name}: {e}')
        return []

    genres = []
    for tag in tags:
        try:
            if int(tag.weight) < MIN_TAG_WEIGHT:
                continue
        except (ValueError, TypeError):
            continue

        genre = tag.item.get_name().lower().strip()
        if genre and genre not in NOT_GENRES:
            genres.append(genre)

    return genres
