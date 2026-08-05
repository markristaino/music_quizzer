"""Parser tests for the Wikipedia year-end charts.

Every sample here is real wikitext taken from the pages we parse. No network.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools import wikipedia_charts as charts  # noqa: E402

HEADER = '''{| class="wikitable sortable" style="text-align: center"
|-
! scope="col" | No.
! scope="col" | Title
! scope="col" | Artist(s)
'''

# The layout used by most years
OLD_FORMAT = HEADER + '''|-
|1 || "[[Careless Whisper]]" || [[George Michael]]
|-
|2 || "[[Like a Virgin (song)|Like a Virgin]]" || [[Madonna]]
|-
|3 || "[[Out of Touch (song)|Out of Touch]]" || [[Hall & Oates|Daryl Hall & John Oates]]
|}
'''

# The layout used by recent years
NEW_FORMAT = HEADER + '''|-
| scope="row" | 1
| "[[Die with a Smile]]" || [[Lady Gaga]] and [[Bruno Mars]]
|-
| scope="row" | 2
| "[[Luther (song)|Luther]]" || [[Kendrick Lamar]] and [[SZA]]
|}
'''

# An artist with consecutive entries spans one cell over several rows (1964)
ROWSPAN_FORMAT = HEADER + '''|-
|1 || "[[I Want to Hold Your Hand]]" || rowspan="2"| [[The Beatles]]
|-
|2 || "[[She Loves You]]"
|-
|3 || "[[Hello, Dolly! (song)|Hello, Dolly!]]" || [[Louis Armstrong]]
|}
'''

# A stray trailing pipe on the separator line (1989)
STRAY_PIPE_FORMAT = HEADER + '''|-
|25 || "[[Like a Prayer (song)|Like a Prayer]]" || [[Madonna]]
|- |
|26 || "[[I'll Be Loving You (Forever)]]" || [[New Kids on the Block]]
|}
'''


def parsed(wikitext, year=1985):
    return charts.parse_year_end(wikitext, year)


# --- Table formats -----------------------------------------------------------

def test_old_inline_format():
    entries = parsed(OLD_FORMAT)

    assert len(entries) == 3
    assert entries[0] == {'rank': 1, 'song': 'Careless Whisper',
                          'artist': 'George Michael', 'year': 1985}


def test_new_scope_row_format():
    entries = parsed(NEW_FORMAT, 2025)

    assert len(entries) == 2
    assert entries[0]['song'] == 'Die with a Smile'
    assert entries[0]['artist'] == 'Lady Gaga and Bruno Mars'
    assert entries[1]['song'] == 'Luther'


def test_rowspan_carries_the_artist_down():
    """The row under a spanning cell has no artist of its own."""
    entries = parsed(ROWSPAN_FORMAT, 1964)

    assert [e['rank'] for e in entries] == [1, 2, 3]
    assert entries[1]['song'] == 'She Loves You'
    assert entries[1]['artist'] == 'The Beatles'
    # The span must not leak past the rows it covers
    assert entries[2]['artist'] == 'Louis Armstrong'


def test_stray_pipe_on_separator_line():
    entries = parsed(STRAY_PIPE_FORMAT, 1989)

    assert [e['rank'] for e in entries] == [25, 26]
    assert entries[1]['song'] == "I'll Be Loving You (Forever)"
    assert entries[1]['artist'] == 'New Kids on the Block'


# --- Wikitext cleaning -------------------------------------------------------

@pytest.mark.parametrize('raw, expected', [
    ('[[Madonna]]', 'Madonna'),
    ('[[Like a Virgin (song)|Like a Virgin]]', 'Like a Virgin'),
    ("[[Hall & Oates|Daryl Hall & John Oates]]", 'Daryl Hall & John Oates'),
    ("''[[Theme from A Summer Place]]''", 'Theme from A Summer Place'),
    ('[[Ciara]] featuring [[Missy Elliott]]', 'Ciara featuring Missy Elliott'),
    ('[[Prince (musician)|Prince]]<ref name="x">note</ref>', 'Prince'),
    ('[[Elton John]]{{efn|with someone}}', 'Elton John'),
    ('The&nbsp;Beatles', 'The Beatles'),
    ('  spaced   out  ', 'spaced out'),
])
def test_clean_wikitext(raw, expected):
    assert charts.clean_wikitext(raw) == expected


# --- Whole-page behaviour ----------------------------------------------------

def test_rows_are_ordered_by_rank():
    scrambled = HEADER + '''|-
|3 || "[[Third]]" || [[C]]
|-
|1 || "[[First]]" || [[A]]
|-
|2 || "[[Second]]" || [[B]]
|}
'''
    assert [e['rank'] for e in parsed(scrambled)] == [1, 2, 3]


def test_repeated_rank_keeps_the_first():
    duplicated = HEADER + '''|-
|1 || "[[Real Entry]]" || [[A]]
|-
|1 || "[[Sidebar Entry]]" || [[B]]
|}
'''
    entries = parsed(duplicated)
    assert len(entries) == 1
    assert entries[0]['song'] == 'Real Entry'


def test_non_row_content_is_ignored():
    noisy = '''[[File:Beatles.jpg|thumb|The Beatles had "[[She Loves You]]" that year.]]
''' + OLD_FORMAT + '''
==References==
{{reflist}}
'''
    assert len(parsed(noisy)) == 3


def test_ranks_outside_the_chart_are_dropped():
    out_of_range = HEADER + '''|-
|1 || "[[Valid]]" || [[A]]
|-
|101 || "[[Too Far]]" || [[B]]
|}
'''
    assert [e['rank'] for e in parsed(out_of_range)] == [1]


# --- The short-parse guard ---------------------------------------------------

def test_short_page_raises(monkeypatch):
    """A layout change must fail loudly, not yield a thin library."""
    monkeypatch.setattr(charts, 'fetch_wikitext', lambda title, timeout=30: OLD_FORMAT)

    with pytest.raises(ValueError, match='parsed only 3'):
        charts.fetch_year_end(1985)


def test_full_page_passes_the_guard(monkeypatch):
    rows = '\n'.join(f'|-\n|{i} || "[[Song {i}]]" || [[Artist {i}]]'
                     for i in range(1, 101))
    monkeypatch.setattr(charts, 'fetch_wikitext',
                        lambda title, timeout=30: HEADER + rows + '\n|}')

    entries = charts.fetch_year_end(1985)
    assert len(entries) == 100
    assert entries[0]['year'] == 1985
