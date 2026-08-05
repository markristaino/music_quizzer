"""Artist rules: who is held out of the quiz, and how names are tidied.

Both are applied when the library is loaded, not when it's built, so rebuilding
from the charts can't quietly undo them. Edit and restart.
"""

# Artist -> which of their songs to leave out:
#   None            everything they did
#   (from, until)   a year range, `from` inclusive and `until` exclusive;
#                   either end may be None for open-ended
EXCLUDED_ARTISTS = {
    'the beach boys': None,
    'the beatles': None,
    'the police': None,
    'elvis presley': None,
    'simon & garfunkel': None,
    'the doors': None,
    'michael jackson': None,
    'u2': None,
    'pink floyd': (1973, None),   # from Dark Side of the Moon on
    'bob dylan': (None, 1969),    # everything before 1969
}


# Credits the charts use that we'd rather show differently. Matched on the
# whole credit, so joint billings like "Paul McCartney and Stevie Wonder" are
# left alone.
ARTIST_ALIASES = {
    'little stevie wonder': 'Stevie Wonder',
    'daryl hall & john oates': 'Hall & Oates',
    'daryl hall and john oates': 'Hall & Oates',
    'hall and oates': 'Hall & Oates',
    'prince and the revolution': 'Prince',
    'prince & the revolution': 'Prince',
}


def normalise_artist(artist):
    return ' '.join(str(artist).lower().split())


def canonical_artist(artist):
    """The name the quiz should use for this credit."""
    return ARTIST_ALIASES.get(normalise_artist(artist), artist)


def is_excluded(artist, year=None):
    """Should this song be kept out of the quiz?"""
    name = normalise_artist(artist)

    for excluded, span in EXCLUDED_ARTISTS.items():
        # Prefix match so joint credits go too ("The Beatles with Billy Preston")
        if name != excluded and not name.startswith(excluded + ' '):
            continue

        if span is None:
            return True

        try:
            released = int(year)
        except (TypeError, ValueError):
            # No usable year on a ranged rule - leave it out rather than risk
            # serving the thing we were asked to remove
            return True

        start, until = span
        return ((start is None or released >= start)
                and (until is None or released < until))

    return False
