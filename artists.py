"""Artist rules: who is held out of the quiz, and how names are tidied.

Both are applied when the library is loaded, not when it's built, so rebuilding
from the charts can't quietly undo them. Edit and restart.
"""

# Artist -> the year the exclusion starts, or None for everything they did.
EXCLUDED_ARTISTS = {
    'elvis presley': None,
    'the beach boys': None,
    'the beatles': None,
    'the police': None,
    'pink floyd': 1973,   # from Dark Side of the Moon on
}


# Credits the charts use that we'd rather show differently. Matched on the
# whole credit, so joint billings like "Paul McCartney and Stevie Wonder" are
# left alone.
ARTIST_ALIASES = {
    'little stevie wonder': 'Stevie Wonder',
}


def normalise_artist(artist):
    return ' '.join(str(artist).lower().split())


def canonical_artist(artist):
    """The name the quiz should use for this credit."""
    return ARTIST_ALIASES.get(normalise_artist(artist), artist)


def is_excluded(artist, year=None):
    """Should this song be kept out of the quiz?"""
    name = normalise_artist(artist)

    for excluded, from_year in EXCLUDED_ARTISTS.items():
        # Prefix match so joint credits go too ("The Beatles with Billy Preston")
        if name != excluded and not name.startswith(excluded + ' '):
            continue

        if from_year is None:
            return True

        try:
            return int(year) >= from_year
        except (TypeError, ValueError):
            # No usable year on a year-gated rule - leave it out rather than
            # risk serving the thing we were asked to remove
            return True

    return False
