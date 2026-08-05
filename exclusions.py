"""Artists held out of the quiz for being too recognisable.

Applied when the library is loaded, not when it's built, so rebuilding from the
charts doesn't quietly let them back in. Edit this list and restart.

Each entry is an artist name mapped to the year the exclusion starts, or None
to exclude everything they've done.
"""

EXCLUDED_ARTISTS = {
    'the beach boys': None,
    'the beatles': None,
    'the police': None,
    'pink floyd': 1973,   # from Dark Side of the Moon on
}


def normalise_artist(artist):
    return ' '.join(str(artist).lower().split())


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
