"""Tests for the artist rules: exclusions and name tidying."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from artists import canonical_artist, is_excluded  # noqa: E402


@pytest.mark.parametrize('artist, year', [
    ('The Beatles', 1964),
    ('the beatles', 1970),
    ('The Beach Boys', 1966),
    ('The Police', 1983),
    ('Elvis Presley', 1957),
    ('Elvis Presley', 1970),
    ('Simon & Garfunkel', 1970),
    ('The Doors', 1967),
    ('Michael Jackson', 1983),
    ('Michael Jackson featuring Siedah Garrett', 1987),
    ('U2', 1987),
])
def test_fully_excluded_artists(artist, year):
    assert is_excluded(artist, year)


def test_joint_credits_go_too():
    """1969's Get Back is credited to The Beatles with Billy Preston."""
    assert is_excluded('The Beatles with Billy Preston', 1969)


@pytest.mark.parametrize('year, excluded', [
    (1967, False),   # See Emily Play, before Dark Side
    (1972, False),
    (1973, True),    # Dark Side of the Moon
    (1980, True),    # Another Brick in the Wall
])
def test_pink_floyd_is_gated_by_year(year, excluded):
    assert is_excluded('Pink Floyd', year) is excluded


def test_year_gated_artist_with_no_year_is_held_out():
    """Better to drop it than risk serving what we were asked to remove."""
    assert is_excluded('Pink Floyd', None)
    assert is_excluded('Pink Floyd', 'unknown')


@pytest.mark.parametrize('year, excluded', [
    (1965, True),    # Like a Rolling Stone
    (1966, True),    # Rainy Day Women
    (1968, True),
    (1969, False),   # Lay Lady Lay
    (1975, False),
])
def test_bob_dylan_is_gated_to_before_1969(year, excluded):
    assert is_excluded('Bob Dylan', year) is excluded


@pytest.mark.parametrize('artist', [
    'The Rolling Stones',
    '3 Doors Down',          # not a prefix match on "the doors"
    'Paul Simon',            # solo work is fair game
    'Art Garfunkel',
    'The Jackson 5',         # only Michael solo was asked for
    'Janet Jackson',
    'Beach House',
    'Police Academy Band',   # not a prefix match on "the police"
    'Sting',
    'Paul McCartney',        # solo work is fair game
    'John Lennon',
])
def test_everyone_else_is_kept(artist):
    assert not is_excluded(artist, 1975)


def test_library_load_drops_them():
    import pandas as pd
    import library

    df = pd.DataFrame([
        {'Song': 'Hey Jude', 'Artist': 'The Beatles', 'Year': 1968},
        {'Song': 'Money', 'Artist': 'Pink Floyd', 'Year': 1973},
        {'Song': 'See Emily Play', 'Artist': 'Pink Floyd', 'Year': 1967},
        {'Song': 'Imagine', 'Artist': 'John Lennon', 'Year': 1971},
    ])

    kept = set(library._apply_artist_rules(df)['Song'])

    assert kept == {'See Emily Play', 'Imagine'}


# --- Name tidying ------------------------------------------------------------

def test_little_stevie_wonder_is_renamed():
    assert canonical_artist('Little Stevie Wonder') == 'Stevie Wonder'
    assert canonical_artist('little stevie wonder') == 'Stevie Wonder'


@pytest.mark.parametrize('credit, expected', [
    ('Daryl Hall & John Oates', 'Hall & Oates'),
    ('Daryl Hall and John Oates', 'Hall & Oates'),
    ('Hall & Oates', 'Hall & Oates'),
    ('Prince and The Revolution', 'Prince'),
    ('Prince & the Revolution', 'Prince'),
    ('Prince and The New Power Generation', 'Prince'),
    ('Prince', 'Prince'),
])
def test_backing_bands_fold_into_the_lead(credit, expected):
    assert canonical_artist(credit) == expected


@pytest.mark.parametrize('credit', [
    'DJ Jazzy Jeff & The Fresh Prince',
    'Baby Boy da Prince',
    'Paul Anka & Odia Coates',
])
def test_similar_names_are_not_folded(credit):
    assert canonical_artist(credit) == credit


def test_joint_credits_are_left_alone():
    for credit in ('Stevie Wonder',
                   'Paul McCartney and Stevie Wonder',
                   'Dionne and Friends (Dionne Warwick, Gladys Knight, '
                   'Elton John and Stevie Wonder)'):
        assert canonical_artist(credit) == credit


def test_unknown_artists_pass_through():
    assert canonical_artist('Fleetwood Mac') == 'Fleetwood Mac'


def test_library_load_renames_artists():
    import pandas as pd
    import library

    df = pd.DataFrame([
        {'Song': 'Fingertips - Part 2', 'Artist': 'Little Stevie Wonder', 'Year': 1963},
        {'Song': 'Superstition', 'Artist': 'Stevie Wonder', 'Year': 1973},
    ])

    assert set(library._apply_artist_rules(df)['Artist']) == {'Stevie Wonder'}
