"""Read Billboard Year-End Hot 100 charts from Wikipedia.

Billboard's own year-end pages return 403, but Wikipedia mirrors the lists for
every year from 1960 on. Each page holds one table of 100 songs in one of two
wikitext layouts:

    older      |1 || "[[Careless Whisper]]" || [[George Michael]]

    newer      | scope="row" | 1
               | "[[Die with a Smile]]" || [[Lady Gaga]] and [[Bruno Mars]]

Fetching and parsing are kept apart so the parser can be tested without network.
"""
import json
import logging
import re
import urllib.parse
import urllib.request

logger = logging.getLogger(__name__)

WIKIPEDIA_API = 'https://en.wikipedia.org/w/api.php'
USER_AGENT = 'music-quizzer/1.0 (https://github.com/markristaino/music_quizzer)'
PAGE_TITLE = 'Billboard_Year-End_Hot_100_singles_of_{year}'

EXPECTED_ENTRIES = 100
MIN_ACCEPTABLE_ENTRIES = 90  # Some years legitimately list a few fewer

# Consume the whole separator line - some rows carry a stray trailing pipe
_ROW_SEPARATOR = re.compile(r'^\|-.*$', re.MULTILINE)
_RANK = re.compile(r'^\|\s*(?:scope="row"\s*\|\s*)?(\d{1,3})\b')
_TITLE = re.compile(r'"\s*(.+?)\s*"', re.DOTALL)
_REF = re.compile(r'<ref[^>]*?/>|<ref.*?</ref>', re.DOTALL | re.IGNORECASE)
_COMMENT = re.compile(r'<!--.*?-->', re.DOTALL)
_TEMPLATE = re.compile(r'\{\{[^{}]*\}\}')
_WIKILINK = re.compile(r'\[\[(?:[^\[\]|]*\|)?([^\[\]|]*)\]\]')
_HTML_TAG = re.compile(r'<[^>]+>')
# An artist with consecutive entries gets one cell spanning several rows, which
# leaves the rows underneath with no artist of their own.
_ROWSPAN = re.compile(r'rowspan\s*=\s*"?(\d+)"?\s*\|')
# Cell attributes (rowspan="2", scope="row", style="...") hold quoted values
_CELL_ATTR = re.compile(r'\b[a-z-]+\s*=\s*"[^"]*"\s*\|?')


def clean_wikitext(value):
    """Reduce a wikitext fragment to the plain text a reader would see."""
    value = _REF.sub('', value)
    value = _COMMENT.sub('', value)

    # Templates can nest; peel one layer at a time
    for _ in range(3):
        new_value = _TEMPLATE.sub('', value)
        if new_value == value:
            break
        value = new_value

    value = _WIKILINK.sub(r'\1', value)
    value = value.replace("'''", '').replace("''", '')
    value = _HTML_TAG.sub('', value)
    value = value.replace('&nbsp;', ' ').replace('&amp;', '&')
    value = value.replace('&quot;', '"').replace('&ndash;', '-')
    return ' '.join(value.split()).strip()


def _parse_row(chunk):
    """Parse one table row into (rank, song, artist, rowspan).

    Returns None if the chunk isn't a chart row. `artist` is None when the row
    has no artist cell, which means it sits under a spanning cell above it.
    """
    text = ' '.join(line.strip() for line in chunk.strip().splitlines() if line.strip())
    if not text.startswith('|'):
        return None

    # The last row runs into the table terminator
    table_end = text.find('|}')
    if table_end != -1:
        text = text[:table_end]

    rank_match = _RANK.match(text)
    if not rank_match:
        return None
    rank = int(rank_match.group(1))

    remainder = text[rank_match.end():]

    # Read the rowspan, then strip all cell attributes. They contain quoted
    # values (rowspan="2") that would otherwise look like song titles below.
    rowspan = 1
    span_match = _ROWSPAN.search(remainder)
    if span_match:
        rowspan = int(span_match.group(1))
    remainder = _CELL_ATTR.sub(' | ', remainder)

    # Work in table cells rather than by quote position. Titles can be doubled
    # up ("You Learn" / "You Oughta Know") and artists can carry quoted
    # nicknames (Clarence "Frogman" Henry), so quotes alone don't delimit them.
    cells = remainder.split('||')

    title_cell = next(
        (i for i, cell in enumerate(cells) if _TITLE.search(cell)), None)
    if title_cell is None:
        return None

    song = clean_wikitext(_TITLE.search(cells[title_cell]).group(1))
    if not song:
        return None

    # The artist is the final cell - unless the row ends at the title, which
    # means a spanning cell above supplies the artist.
    artist = None
    if len(cells) - 1 > title_cell:
        artist = clean_wikitext(cells[-1].lstrip('| ')) or None

    return rank, song, artist, rowspan


def parse_year_end(wikitext, year):
    """Parse a year-end chart page into a list of entries, ordered by rank."""
    entries = {}
    spanning_artist, rows_remaining = None, 0

    for chunk in _ROW_SEPARATOR.split(wikitext):
        row = _parse_row(chunk)
        if row is None:
            continue
        rank, song, artist, rowspan = row

        if artist:
            # A spanning cell covers this row plus the ones underneath it
            spanning_artist, rows_remaining = artist, rowspan - 1
        elif rows_remaining > 0:
            artist, rows_remaining = spanning_artist, rows_remaining - 1
        else:
            continue

        if not 1 <= rank <= EXPECTED_ENTRIES:
            continue
        # A page occasionally repeats a rank across tables; first one wins
        entries.setdefault(rank, {
            'rank': rank,
            'song': song,
            'artist': artist,
            'year': year,
        })

    return [entries[rank] for rank in sorted(entries)]


def fetch_wikitext(title, timeout=30):
    """Fetch raw wikitext for a page. Raises if the page is missing."""
    query = urllib.parse.urlencode({
        'action': 'parse',
        'page': title,
        'prop': 'wikitext',
        'format': 'json',
        'formatversion': '2',
    })
    request = urllib.request.Request(f'{WIKIPEDIA_API}?{query}',
                                     headers={'User-Agent': USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.load(response)

    if 'error' in payload:
        raise LookupError(f"{title}: {payload['error'].get('info', 'unknown error')}")
    return payload['parse']['wikitext']


def fetch_year_end(year):
    """Fetch and parse one year's chart.

    Raises ValueError when a year parses short, so a layout change surfaces
    instead of quietly producing a thin library.
    """
    entries = parse_year_end(fetch_wikitext(PAGE_TITLE.format(year=year)), year)

    if len(entries) < MIN_ACCEPTABLE_ENTRIES:
        raise ValueError(
            f'{year}: parsed only {len(entries)} entries, expected about '
            f'{EXPECTED_ENTRIES}. The page layout has probably changed.'
        )

    logger.info(f'{year}: {len(entries)} songs')
    return entries
