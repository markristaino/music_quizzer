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
import deezer

logger = logging.getLogger(__name__)


class LookupFailed(Exception):
    """No provider could be reached, so we learned nothing.

    Distinct from "searched and found nothing": a network blip must never be
    recorded as a permanent verdict that a song has no preview.
    """

client = deezer.Client()

# Deezer signs its preview URLs with a ~15 minute expiry, so a stored URL is
# dead almost immediately. For these we keep the track id and fetch a fresh URL
# at play time. Apple's URLs carry no signature and can be stored as-is.
EXPIRING_SOURCES = {'deezer'}

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
    """Returns (preview_url, track_id)."""
    queries = [
        f'track:"{clean_song}" artist:"{clean_artist}"',  # exact match on both
        f'{clean_song} {clean_artist}',                   # simple combined search
        clean_song,                                       # title only
    ]

    reached = False
    for query in queries:
        try:
            results = client.search(query)
            reached = True
        except Exception as e:
            logger.debug(f"Deezer search failed for '{query}': {e}")
            continue

        for track in results:
            if not track.preview:
                continue
            if is_match(song_words, artist_words, track.title, track.artist.name):
                return track.preview, str(track.id)

    if not reached:
        raise LookupFailed('deezer unreachable')
    return None, None


def _itunes_preview(clean_song, clean_artist, song_words, artist_words):
    """Returns (preview_url, track_id)."""
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
        raise LookupFailed(f'itunes unreachable: {e}')

    for item in results:
        preview = item.get('previewUrl')
        if not preview:
            continue
        if is_match(song_words, artist_words,
                    item.get('trackName', ''), item.get('artistName', '')):
            return preview, str(item.get('trackId', ''))

    return None, None


def find_preview(song, artist):
    """Search both providers for a playable preview.

    Returns (preview_url, source, track_id) - all None if neither has one. The
    track id matters more than the URL: see EXPIRING_SOURCES below.
    """
    clean_song = clean_text(song)
    clean_artist = clean_text(artist)
    song_words = set(clean_song.lower().split())
    artist_words = set(clean_artist.lower().split())

    if not song_words:
        return None, None, None

    reached = False
    for source, lookup in (('deezer', _deezer_preview), ('itunes', _itunes_preview)):
        try:
            preview, track_id = lookup(clean_song, clean_artist,
                                       song_words, artist_words)
            reached = True
        except Exception as e:
            logger.warning(f'{source} lookup failed for {artist} - {song}: {e}')
            continue
        if preview:
            return preview, source, track_id

    if not reached:
        raise LookupFailed(f'no provider reachable for {artist} - {song}')
    return None, None, None


def get_preview_url(song, artist):
    """Search for a playable preview URL. Not cached - see EXPIRING_SOURCES."""
    try:
        preview, _source, _track_id = find_preview(song, artist)
    except LookupFailed as e:
        logger.warning(f'Preview lookup unavailable: {e}')
        return None
    if not preview:
        logger.info(f'No preview found for {artist} - {song}')
    return preview


def refresh_preview(source, track_id):
    """A fresh URL for a preview we already identified, by track id.

    One cheap call instead of re-running the whole search.
    """
    if source != 'deezer' or not track_id:
        return None
    try:
        return client.get_track(int(track_id)).preview or None
    except Exception as e:
        logger.info(f'Could not refresh deezer track {track_id}: {e}')
        return None
