"""Tests for the quiz app.

Deezer lookups are stubbed out, so these run without network access.
"""
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Point the score database somewhere disposable before importing the app
os.environ['SCORES_DB'] = os.path.join(tempfile.mkdtemp(), 'test_scores.db')

import app as quiz  # noqa: E402

FAKE_PREVIEW = 'https://example.invalid/preview.mp3'

# A guess that cannot fuzzy-match any real artist or title. Plain words like
# "wrong" occasionally match a song called Wrong, which made tests flaky.
NO_MATCH = 'zzzzzzzzzz qqqqqqqqqq'


@pytest.fixture
def client(monkeypatch):
    """A test client with Deezer stubbed and a clean score table."""
    monkeypatch.setattr(quiz, 'get_preview_url', lambda song, artist: FAKE_PREVIEW)
    quiz.app.config['TESTING'] = True

    with quiz.get_db() as db:
        db.cursor().execute('DELETE FROM scores')
        db.commit()

    with quiz.app.test_client() as client:
        yield client


def start_game(client, username='player'):
    return client.post('/set_username', json={'username': username})


def current_answer(client):
    """Read the song the server is holding for this session."""
    with client.session_transaction() as session:
        return session['current_song']


# --- The answer must never reach the browser ---------------------------------

def test_new_song_does_not_leak_the_answer(client):
    start_game(client)
    payload = client.get('/new-song').get_json()

    assert payload['preview_url'] == FAKE_PREVIEW
    assert 'artist' not in payload
    assert 'song' not in payload


def test_client_supplied_answer_is_ignored(client):
    """Posting your own artist/song used to score a guaranteed point."""
    start_game(client)
    client.get('/new-song')

    result = client.post('/check-answer', json={
        'answer': 'totally made up',
        'artist': 'totally made up',
        'song': 'totally made up',
    }).get_json()

    assert result['correct'] is False
    assert result['score'] == 0


def test_answer_is_checked_against_the_session_song(client):
    start_game(client)
    client.get('/new-song')
    answer = current_answer(client)

    result = client.post('/check-answer', json={'answer': answer['artist']}).get_json()

    assert result['correct'] is True
    assert result['score'] == 1


def test_song_title_also_counts_as_correct(client):
    start_game(client)
    client.get('/new-song')
    answer = current_answer(client)

    result = client.post('/check-answer', json={'answer': answer['song']}).get_json()

    assert result['correct'] is True


def test_round_cannot_be_scored_twice(client):
    start_game(client)
    client.get('/new-song')
    answer = current_answer(client)

    client.post('/check-answer', json={'answer': answer['artist']})
    replay = client.post('/check-answer', json={'answer': answer['artist']})

    assert replay.status_code == 400
    assert 'error' in replay.get_json()


def test_check_answer_without_a_song_is_rejected(client):
    start_game(client)
    response = client.post('/check-answer', json={'answer': 'anything'})

    assert response.status_code == 400


def test_lost_session_is_flagged_so_the_browser_can_recover(client):
    """A signed-out session must not strand the player on a dead error."""
    start_game(client)
    payload = client.post('/check-answer', json={'answer': 'anything'}).get_json()

    assert payload['reason'] == 'no_song'
    assert 'error' in payload


def test_client_errors_are_logged(client, caplog):
    start_game(client)
    client.get('/new-song')

    response = client.post('/log-error', json={
        'context': 'audio-load', 'detail': 'code=4 host=example.invalid'})

    assert response.status_code == 204
    assert 'client error [audio-load]' in caplog.text
    assert 'code=4' in caplog.text


def test_client_error_fields_are_truncated(client, caplog):
    client.post('/log-error', json={'context': 'x' * 200, 'detail': 'y' * 5000})

    logged = caplog.text
    assert 'x' * (quiz.CLIENT_ERROR_CONTEXT_LENGTH + 1) not in logged
    assert 'y' * (quiz.CLIENT_ERROR_DETAIL_LENGTH + 1) not in logged


def test_empty_answer_is_not_correct(client):
    start_game(client)
    client.get('/new-song')

    result = client.post('/check-answer', json={'answer': ''}).get_json()

    assert result['correct'] is False


# --- Game flow ---------------------------------------------------------------

def test_game_ends_after_max_songs(client):
    start_game(client)

    for round_number in range(1, quiz.MAX_SONGS + 1):
        client.get('/new-song')
        result = client.post('/check-answer', json={'answer': NO_MATCH}).get_json()
        assert result['total'] == round_number
        assert result['game_over'] is (round_number == quiz.MAX_SONGS)


def test_finished_game_reaches_the_leaderboard(client):
    start_game(client, 'winner')

    for _ in range(quiz.MAX_SONGS):
        client.get('/new-song')
        answer = current_answer(client)
        result = client.post('/check-answer', json={'answer': answer['artist']}).get_json()

    assert result['game_over'] is True
    assert result['made_leaderboard'] is True

    board = client.get('/leaderboard').get_json()
    assert board[0]['username'] == 'winner'
    assert board[0]['total'] == result['score']
    assert board[0]['games'] == 1


def test_a_score_of_zero_is_not_recorded(client):
    start_game(client, 'blanked')

    for _ in range(quiz.MAX_SONGS):
        client.get('/new-song')
        result = client.post('/check-answer', json={'answer': NO_MATCH}).get_json()

    assert result['score'] == 0
    assert result['made_leaderboard'] is False
    assert client.get('/leaderboard').get_json() == []


def test_one_right_still_counts(client):
    start_game(client, 'scraped-by')

    for round_number in range(quiz.MAX_SONGS):
        client.get('/new-song')
        answer = current_answer(client)
        guess = answer['artist'] if round_number == 0 else NO_MATCH
        result = client.post('/check-answer', json={'answer': guess}).get_json()

    assert result['score'] == 1
    board = client.get('/leaderboard').get_json()
    assert [entry['username'] for entry in board] == ['scraped-by']
    assert board[0]['total'] == 1


def play_game(client, username, correct_rounds):
    """Play a full game, getting `correct_rounds` of them right."""
    start_game(client, username)
    for index in range(quiz.MAX_SONGS):
        client.get('/new-song')
        answer = current_answer(client)
        guess = answer['artist'] if index < correct_rounds else NO_MATCH
        client.post('/check-answer', json={'answer': guess})


# --- All-time standings ------------------------------------------------------

def test_totals_accumulate_across_games(client):
    play_game(client, 'repeat', 2)
    play_game(client, 'repeat', 3)

    board = client.get('/leaderboard').get_json()

    assert len(board) == 1
    assert board[0] == {'username': 'repeat', 'total': 5, 'games': 2, 'best': 3}


def test_names_are_grouped_regardless_of_case(client):
    play_game(client, 'Mark', 2)
    play_game(client, 'mark', 1)

    board = client.get('/leaderboard').get_json()

    assert len(board) == 1
    assert board[0]['total'] == 3
    assert board[0]['games'] == 2


def test_standings_rank_by_total(client):
    play_game(client, 'steady', 2)
    play_game(client, 'steady', 2)   # 4 across two games
    play_game(client, 'oneshot', 3)  # 3 in one

    board = client.get('/leaderboard').get_json()

    assert [entry['username'] for entry in board] == ['steady', 'oneshot']
    assert board[0]['total'] == 4


def test_fewer_games_breaks_a_tie(client):
    play_game(client, 'efficient', 3)
    play_game(client, 'grinder', 2)
    play_game(client, 'grinder', 1)

    board = client.get('/leaderboard').get_json()

    assert [entry['username'] for entry in board] == ['efficient', 'grinder']


def test_blank_games_do_not_add_a_player(client):
    play_game(client, 'shutout', 0)

    assert client.get('/leaderboard').get_json() == []


def test_username_stays_after_game_over(client):
    start_game(client, 'persistent')

    for _ in range(quiz.MAX_SONGS):
        client.get('/new-song')
        client.post('/check-answer', json={'answer': NO_MATCH})

    assert client.get('/check-session').get_json() == {
        'has_session': True, 'username': 'persistent'
    }


# --- Input handling ----------------------------------------------------------

def test_username_is_length_limited(client):
    start_game(client, 'x' * 200)

    username = client.get('/check-session').get_json()['username']
    assert len(username) == quiz.MAX_USERNAME_LENGTH


def test_blank_username_is_rejected(client):
    assert client.post('/set_username', json={'username': '   '}).status_code == 400
    assert client.post('/set_username', json={}).status_code == 400


def test_wrong_answer_message_escapes_song_data(client, monkeypatch):
    start_game(client)
    client.get('/new-song')

    with client.session_transaction() as session:
        session['current_song'] = {'artist': '<script>x</script>', 'song': 'Test'}

    message = client.post('/check-answer', json={'answer': NO_MATCH}).get_json()['message']

    assert '<script>' not in message
    assert '&lt;script&gt;' in message


# --- Filtering ---------------------------------------------------------------

def test_filters_are_applied(client):
    start_game(client)
    client.post('/update_filters', json={'genres': ['rock'], 'decades': ['1980s']})

    client.get('/new-song')
    answer = current_answer(client)

    row = quiz.song_data[
        (quiz.song_data['Song'] == answer['song'])
        & (quiz.song_data['Artist'] == answer['artist'])
    ].iloc[0]

    assert row['Decade'] == '1980s'
    assert 'rock' in row['ParentGenres']


def test_impossible_filter_returns_a_message(client):
    start_game(client)
    client.post('/update_filters', json={'genres': ['classical'], 'decades': ['1930s']})

    payload = client.get('/new-song').get_json()

    assert 'error' in payload
    assert 'No songs found' in payload['error']


def test_recent_songs_are_tracked_per_session(client):
    """One player's history must not affect another's."""
    start_game(client)
    client.get('/new-song')

    with client.session_transaction() as session:
        assert len(session['recent_songs']) == 1

    other = quiz.app.test_client()
    start_game(other)
    other.get('/new-song')

    with other.session_transaction() as session:
        assert len(session['recent_songs']) == 1


def test_recent_songs_list_is_capped(client):
    start_game(client)
    with client.session_transaction() as session:
        session['recent_songs'] = list(range(quiz.MAX_RECENT_SONGS + 20))

    client.get('/new-song')

    with client.session_transaction() as session:
        assert len(session['recent_songs']) == quiz.MAX_RECENT_SONGS


# --- Data + genre mapping ----------------------------------------------------

def test_song_data_loaded():
    assert quiz.song_data is not None
    assert len(quiz.song_data) > 0
    assert quiz.all_decades == sorted(quiz.all_decades)


def test_songs_before_min_year_are_excluded():
    import pandas as pd

    years = pd.to_numeric(quiz.song_data['Year'], errors='coerce')
    assert years.min() >= quiz.MIN_YEAR
    assert years.notna().all()


def test_decade_options_start_at_min_year():
    assert min(quiz.all_decades) >= quiz.MIN_YEAR - (quiz.MIN_YEAR % 10)
    assert 1930 not in quiz.all_decades
    assert 1950 not in quiz.all_decades


def test_parent_genre_mapping():
    assert quiz.map_to_parent_genre('Hard Rock') == 'rock'
    assert quiz.map_to_parent_genre('  TRAP ') == 'hip hop'
    assert quiz.map_to_parent_genre('rock') == 'rock'
    assert quiz.map_to_parent_genre('polka') == 'polka'  # unknown passes through


@pytest.mark.parametrize('credit, lead', [
    ('Chris Brown featuring Usher and Rick Ross', 'Chris Brown'),
    ('Usher featuring Lil Jon and Ludacris', 'Usher'),
    ('Mark Ronson featuring Bruno Mars', 'Mark Ronson'),
    ('Gotye feat. Kimbra', 'Gotye'),
    ('Flo Rida ft. T-Pain', 'Flo Rida'),
    ('Santana with Rob Thomas', 'Santana'),
    # Joint acts are not guest credits and must survive intact
    ('Simon & Garfunkel', 'Simon & Garfunkel'),
    ('Hall & Oates', 'Hall & Oates'),
    ('Tony Orlando and Dawn', 'Tony Orlando and Dawn'),
    ('Lil Nas X', 'Lil Nas X'),
    ('Lady Gaga and Bruno Mars', 'Lady Gaga and Bruno Mars'),
    ('Captain & Tennille', 'Captain & Tennille'),
])
def test_primary_artist(credit, lead):
    assert quiz.primary_artist(credit) == lead


def test_naming_the_lead_is_enough(client):
    start_game(client)
    client.get('/new-song')

    with client.session_transaction() as session:
        session['current_song'] = {
            'artist': 'Chris Brown featuring Usher and Rick Ross',
            'song': 'Deuces',
        }

    result = client.post('/check-answer', json={'answer': 'chris brown'}).get_json()
    assert result['correct'] is True


def test_naming_only_a_guest_is_not_enough(client):
    start_game(client)
    client.get('/new-song')

    with client.session_transaction() as session:
        session['current_song'] = {
            'artist': 'Chris Brown featuring Usher and Rick Ross',
            'song': 'Deuces',
        }

    result = client.post('/check-answer', json={'answer': 'rick ross'}).get_json()
    assert result['correct'] is False


def test_the_full_credit_still_counts(client):
    start_game(client)
    client.get('/new-song')

    with client.session_transaction() as session:
        session['current_song'] = {
            'artist': 'Mark Ronson featuring Bruno Mars',
            'song': 'Uptown Funk',
        }

    result = client.post('/check-answer',
                         json={'answer': 'mark ronson featuring bruno mars'}).get_json()
    assert result['correct'] is True


def matches(guess, correct):
    return quiz.answer_matches(quiz.clean_text(guess.lower()),
                               quiz.clean_text(correct.lower()))


@pytest.mark.parametrize('guess, correct', [
    ('Alanis Morissette', 'Alanis Morissette'),   # exact
    ('alanis morisett', 'Alanis Morissette'),     # a letter short
    ('whitney huston', 'Whitney Houston'),        # misspelled
    ('the beetles', 'The Beatles'),               # misspelled
    ('morissette', 'Alanis Morissette'),          # surname only
    ('alanis', 'Alanis Morissette'),              # first name only
    ('beatles', 'The Beatles'),                   # without the article
    ('simon and garfunkle', 'Simon & Garfunkel'), # ampersand plus a typo
    ('i think its fleetwood mac', 'Fleetwood Mac'),  # buried in a sentence
])
def test_forgiving_answers_are_accepted(guess, correct):
    assert matches(guess, correct)


@pytest.mark.parametrize('guess, correct', [
    ('', 'Alanis Morissette'),
    ('madonna', 'Alanis Morissette'),
    ('the police', 'The Beatles'),
    ('john lennon', 'Elton John'),        # short shared word isn't enough
    ('no idea', 'Fleetwood Mac'),
])
def test_wrong_answers_are_still_wrong(guess, correct):
    assert not matches(guess, correct)


def test_a_shared_surname_is_accepted(monkeypatch):
    """Known cost of accepting surnames alone - loosening further would
    catch phonetic guesses but let more of these through."""
    assert matches('wilson phillips', 'Jackie Wilson')


def test_answer_can_be_the_song_title(client):
    start_game(client)
    client.get('/new-song')
    answer = current_answer(client)

    result = client.post('/check-answer', json={'answer': answer['song']}).get_json()
    assert result['correct'] is True


def test_clean_text():
    assert quiz.clean_text("Don't Stop (Remastered)") == 'Dont Stop'
    assert quiz.clean_text('Song feat. Someone') == 'Song Someone'
    assert quiz.clean_text('  multiple   spaces  ') == 'multiple spaces'
