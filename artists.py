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
    'prince and the new power generation': 'Prince',
    'prince & the new power generation': 'Prince',
}


# Ways a credit names guests after the lead. Deliberately no " & ", " and " or
# " x " - those join real acts (Hall & Oates, Lil Nas X, Tony Orlando and Dawn).
FEATURED_SEPARATORS = (
    ' featuring ', ' feat. ', ' feat ', ' ft. ', ' ft ', ' f/ ',
    ' duet with ', ' with ', ' vs. ', ' vs ', ' presents ', ' pres. ',
)


def primary_artist(artist):
    """The billed lead, without any guests.

    "Chris Brown featuring Usher and Rick Ross" -> "Chris Brown"
    """
    name = ' '.join(str(artist).split())
    padded = ' ' + name.lower() + ' '

    cut = len(name)
    for separator in FEATURED_SEPARATORS:
        found = padded.find(separator)
        if found != -1:
            cut = min(cut, found)

    return name[:cut].strip() or name


# Artists we know are female-fronted. Last.fm's tags are crowd-sourced and
# uneven - most Taylor Swift rows carry only "pop" - so naming them here is the
# only reliable way. Matched on the lead, so "X featuring her" doesn't count.
FEMALE_VOCAL_ARTISTS = {
    'taylor swift',
    'ariana grande',
    'olivia rodrigo',
    'ella langley',
    'alyssa grace',
    'lady gaga',
    'gigi perez',
    'ravyn lenae',
    'sza',
    'gracie abrams',
    'chappell roan',
    'billie eilish',
    'aretha franklin',
    'olivia newton-john',
    'brenda lee',
    'connie francis',
    'natalie cole',
    'gladys knight & the pips',
    'the shirelles',
    "the go-go's",
    'expose',
    'exposé',
    'miami sound machine',
    'paramore',
    'adele',
    'doja cat',
    'dua lipa',
    'cardi b',
    'mary j. blige',
    'lizzo',
    'megan thee stallion',
    'camila cabello',
    'halsey',
    'tate mcrae',
    'doechii',
    'lainey wilson',
    'karol g',
}

# Tags that mark a female vocal. Matched whole, never as substrings - "female"
# contains "male", and that way round the test would invert.
FEMALE_VOCAL_TAGS = {
    'female vocalists', 'female vocalist', 'female', 'female rap',
    'female fronted', 'girl group', 'girl groups', 'classic girl group',
    'country women', 'women in rock',
}


def is_female_vocal(artist, genres=None):
    """Is this song female-fronted?

    The named list wins; tags are the fallback. Judged on the billed lead, so
    "Tim McGraw featuring Taylor Swift" is not counted.
    """
    # Prefix match on the whole credit, so joint billings count when she is
    # named first ("Ella Langley & Morgan Wallen") but not when she is a guest.
    credit = normalise_artist(artist)
    lead = normalise_artist(primary_artist(artist))
    for known in FEMALE_VOCAL_ARTISTS:
        if credit == known or credit.startswith(known + ' ') or lead == known:
            return True

    if not isinstance(genres, str):
        return False
    return any(tag.strip().lower() in FEMALE_VOCAL_TAGS for tag in genres.split(','))


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
