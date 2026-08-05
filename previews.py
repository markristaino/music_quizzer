"""Finding a playable 30-second preview for a song.

Two providers, tried in order. Neither has any say in what's in the library -
they only answer "can this song be played". Deezer is primary because the app
has always used it; iTunes is the fallback so one provider going down doesn't
take the game with it. Both are unauthenticated.
"""
import json
import logging
import re
import urllib.parse
import urllib.request
from functools import lru_cache

import deezer

logger = logging.getLogger(__name__)

client = deezer.Client()

ITUNES_SEARCH = 'https://itunes.apple.com/search'
USER_AGENT = 'music-quizzer/1.0 (https://github.com/markristaino/music_quizzer)'
REQUEST_TIMEOUT = 15


def clean_text(text):
    """Clean up text by removing special characters and normalizing spaces."""
    # Convert contractions to full words
    text = text.replace("don't", "dont")
    text = text.replace("couldn't", "couldnt")
    text = text.replace("won't", "wont")
    text = text.replace("can't", "cant")
    text = text.replace("ain't", "aint")
    text = text.replace("'bout", "bout")
    text = text.replace("'n'", "and")
    text = text.replace("'", "")  # Remove remaining apostrophes

    # Remove text in parentheses and brackets
    text = re.sub(r'\([^)]*\)', '', text)
    text = re.sub(r'\[[^\]]*\]', '', text)

    # Remove featuring, feat., ft., etc.
    text = re.sub(r'feat\.?|ft\.?|featuring', '', text, flags=re.IGNORECASE)

    # Remove special characters but preserve letters and numbers
    text = re.sub(r'[^\w\s]', ' ', text)

    # Normalize whitespace
    text = ' '.join(text.split())
    return text.strip()


def is_match(song_words, artist_words, candidate_song, candidate_artist):
    """Does a search result plausibly refer to the song we asked for?"""
    track_words = set(clean_text(candidate_song.lower()).split())
    track_artist_words = set(clean_text(candidate_artist.lower()).split())

    title_matches = len(song_words & track_words) >= min(2, len(song_words))
    artist_matches = bool(artist_words & track_artist_words)
    return title_matches and artist_matches


def _deezer_preview(clean_song, clean_artist, song_words, artist_words):
    queries = [
        f'track:"{clean_song}" artist:"{clean_artist}"',  # exact match on both
        f'{clean_song} {clean_artist}',                   # simple combined search
        clean_song,                                       # title only
    ]

    for query in queries:
        try:
            results = client.search(query)
        except Exception as e:
            logger.debug(f"Deezer search failed for '{query}': {e}")
            continue

        for track in results:
            if not track.preview:
                continue
            if is_match(song_words, artist_words, track.title, track.artist.name):
                return track.preview

    return None


def _itunes_preview(clean_song, clean_artist, song_words, artist_words):
    query = urllib.parse.urlencode({
        'term': f'{clean_song} {clean_artist}',
        'media': 'music',
        'entity': 'song',
        'limit': 10,
    })
    request = urllib.request.Request(f'{ITUNES_SEARCH}?{query}',
                                     headers={'User-Agent': USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
            results = json.load(response).get('results', [])
    except Exception as e:
        logger.debug(f'iTunes search failed for {clean_song}: {e}')
        return None

    for item in results:
        preview = item.get('previewUrl')
        if not preview:
            continue
        if is_match(song_words, artist_words,
                    item.get('trackName', ''), item.get('artistName', '')):
            return preview

    return None


def find_preview(song, artist):
    """Return (preview_url, source), or (None, None) if neither provider has one."""
    clean_song = clean_text(song)
    clean_artist = clean_text(artist)
    song_words = set(clean_song.lower().split())
    artist_words = set(clean_artist.lower().split())

    if not song_words:
        return None, None

    for source, lookup in (('deezer', _deezer_preview), ('itunes', _itunes_preview)):
        try:
            preview = lookup(clean_song, clean_artist, song_words, artist_words)
        except Exception as e:
            logger.warning(f'{source} lookup failed for {artist} - {song}: {e}')
            continue
        if preview:
            return preview, source

    return None, None


@lru_cache(maxsize=4096)
def get_preview_url(song, artist):
    """Cached preview lookup for request-time use, misses included."""
    preview, _source = find_preview(song, artist)
    if not preview:
        logger.info(f'No preview found for {artist} - {song}')
    return preview
