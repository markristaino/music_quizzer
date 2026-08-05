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


@pytest.fixture
def client(monkeypatch):
    """A test client with Deezer stubbed and a clean score table."""
    monkeypatch.setattr(quiz, 'get_preview_url', lambda song, artist: FAKE_PREVIEW)
    quiz.app.config['TESTING'] = True

    with quiz.get_db() as db:
        db.execute('DELETE FROM scores')
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
        result = client.post('/check-answer', json={'answer': 'wrong'}).get_json()
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
    assert board[0]['score'] == result['score']


def test_username_stays_after_game_over(client):
    start_game(client, 'persistent')

    for _ in range(quiz.MAX_SONGS):
        client.get('/new-song')
        client.post('/check-answer', json={'answer': 'wrong'})

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

    message = client.post('/check-answer', json={'answer': 'wrong'}).get_json()['message']

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


def test_parent_genre_mapping():
    assert quiz.map_to_parent_genre('Hard Rock') == 'rock'
    assert quiz.map_to_parent_genre('  TRAP ') == 'hip hop'
    assert quiz.map_to_parent_genre('rock') == 'rock'
    assert quiz.map_to_parent_genre('polka') == 'polka'  # unknown passes through


def test_clean_text():
    assert quiz.clean_text("Don't Stop (Remastered)") == 'Dont Stop'
    assert quiz.clean_text('Song feat. Someone') == 'Song Someone'
    assert quiz.clean_text('  multiple   spaces  ') == 'multiple spaces'
