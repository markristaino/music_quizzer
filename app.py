from flask import Flask, render_template, request, jsonify, session
import pandas as pd
import random
import os
import html
import sys
import logging
import secrets
from difflib import SequenceMatcher

import library
from library import USE_POSTGRES, get_db, sql
from previews import (EXPIRING_SOURCES, clean_text, get_preview_url,
                      refresh_preview)

# Configure logging
logging.basicConfig(stream=sys.stdout, level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Gunicorn imports this module as "app"; running it directly means local dev.
RUNNING_LOCALLY = __name__ == '__main__'

def load_secret_key():
    """The key that signs session cookies.

    A fresh key on every boot signs everyone out, losing the song they were on
    mid-game. Production sets SECRET_KEY. Locally we keep one on disk so
    restarting the app doesn't interrupt whoever is playing.
    """
    key = os.environ.get('SECRET_KEY')
    if key:
        return key

    if RUNNING_LOCALLY:
        path = os.path.join(library.BASE_DIR, '.secret_key')
        try:
            if os.path.exists(path):
                stored = open(path).read().strip()
                if stored:
                    return stored
            generated = secrets.token_hex(32)
            with open(path, 'w') as handle:
                handle.write(generated)
            logger.info(f'Generated a local session key at {path}')
            return generated
        except OSError as e:
            logger.warning(f'Could not persist a local session key: {e}')

    logger.warning(
        'SECRET_KEY is not set - using a random key. Restarting will sign '
        'everyone out mid-game. Set it in production.'
    )
    return os.urandom(32)


app.secret_key = load_secret_key()

app.config.update(
    SESSION_COOKIE_SECURE=os.environ.get(
        'SESSION_COOKIE_SECURE', '0' if RUNNING_LOCALLY else '1'
    ) != '0',
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    PERMANENT_SESSION_LIFETIME=1800  # 30 minutes
)

# Where the library and the leaderboard live is decided in library.py, which
# picks Postgres when DATABASE_URL is set and SQLite otherwise.
DB_PATH = library.SQLITE_PATH

MAX_SONGS = 6              # Songs per game
MAX_GUESSES = 2            # Tries per song; the second one comes with a hint
MIN_YEAR = 1960            # Songs released before this are left out of the quiz
MAX_RECENT_SONGS = 50      # Per-player replay memory
MAX_USERNAME_LENGTH = 32
LEADERBOARD_SIZE = 10
MIN_RECORDED_SCORE = 1     # A game with nothing right doesn't go on the board
PREVIEW_SEARCH_ATTEMPTS = 5

# Genre mapping
GENRE_MAPPING = {
    'rock': ['rock', 'alternative rock', 'classic rock', 'hard rock', 'indie rock', 'progressive rock',
             'psychedelic rock', 'art rock', 'garage rock', 'southern rock', 'rock-and-roll', 'rockabilly',
             'rock and roll', 'album rock', 'modern rock', 'soft rock', 'yacht rock', 'dance rock',
             'roots rock', 'post-grunge', 'modern hard rock', 'modern alternative rock', 'baroque pop',
             'glam rock', 'progressive metal', 'rock en espanol', 'latin rock', 'mexican classic rock',
             'piano rock', 'surf punk', 'indie surf', 'modern folk rock', 'modern power pop', 'new wave',
             'electronic rock', 'country rock', 'grunge', 'hair metal', 'blues-rock', 'rock ballads',
             'rock n roll', 'acoustic rock'],

    'pop': ['pop', 'pop rock', 'indie pop', 'synth-pop', 'dance pop', 'electropop', 'dream pop',
            'chamber pop', 'sophisti-pop', 'art pop', 'k-pop', 'j-pop', 'power pop', 'indie poptimism',
            'pop dance', 'pop folk', 'pop nacional', 'pop soul', 'pop emo', 'pop punk', 'pop r&b',
            'pop rap', 'canadian pop', 'uk pop', 'latin pop', 'adult standards', 'neo mellow',
            'contemporary vocal jazz', 'vocal jazz', 'show tunes', 'easy listening', 'bedroom pop',
            'bubblegum', 'adult contemporary', 'puerto rican pop', 'colombian pop', 'pop-soul',
            'bubblegum pop', 'candy pop', 'dark pop'],

    'electronic': ['electronic', 'electronica', 'edm', 'house', 'techno', 'trance', 'dubstep', 'ambient',
                  'drum and bass', 'electro', 'electronic trap', 'electro house', 'progressive house',
                  'deep house', 'tech house', 'tropical house', 'future bass', 'complextro', 'big room',
                  'brostep', 'filthstep', 'future garage', 'intelligent dance music', 'neo-synthpop',
                  'alternative dance', 'dance-punk', 'indietronica', 'canadian electronic', 'slap house',
                  'filter house', 'disco house', 'nu disco', 'compositional ambient', 'ambient pop',
                  'synthwave', 'retrowave', 'acid house', 'drumstep', 'hard trance', 'uk dance',
                  'uk funky', 'cyberpunk'],

    'hip hop': ['hip hop', 'rap', 'trap', 'gangster rap', 'underground hip hop', 'conscious hip hop',
                'alternative hip hop', 'east coast hip hop', 'west coast rap', 'southern hip hop',
                'atlanta hip hop', 'chicago rap', 'detroit hip hop', 'memphis rap', 'miami hip hop',
                'houston rap', 'jazz rap', 'political hip hop', 'emo rap', 'cloud rap', 'melodic rap',
                'rage rap', 'atl hip hop', 'atl trap', 'canadian hip hop', 'canadian trap',
                'country rap', 'dfw rap', 'latin hip hop', 'lgbtq+ hip hop', 'plugg', 'pluggnb',
                'dirty south', 'southern rap', 'g funk', 'east coast rap', 'crunk', 'trap latino',
                'queens hip hop', 'underground hip-hop', 'golden age hip hop'],

    'r&b': ['r&b', 'soul', 'funk', 'contemporary r&b', 'neo soul', 'motown', 'quiet storm',
            'new jack swing', 'gospel', 'southern soul', 'chicago soul', 'memphis soul', 'philly soul',
            'northern soul', 'soul blues', 'soul jazz', 'funk rock', 'funk metal', 'p funk',
            'synth funk', 'funk pop', 'jazz funk', 'alternative r&b', 'british soul', 'indie soul',
            'trap soul', 'urban contemporary', 'classic soul', 'neo-soul', 'latin soul', 'rhythm and blues',
            'slow jams', 'funk paulista', 'funk rj', 'funk carioca', 'latin alternative',
            'tropical alternativo'],

    'metal': ['metal', 'heavy metal', 'thrash metal', 'death metal', 'black metal', 'doom metal',
              'power metal', 'progressive metal', 'folk metal', 'gothic metal', 'industrial metal',
              'symphonic metal', 'alternative metal', 'nu metal', 'metalcore', 'melodic metalcore',
              'canadian metal', 'neo classical metal', 'old school thrash', 'prog metal',
              'uk metalcore', 'rap metal', 'melodic black metal', 'traditional doom metal',
              'glam metal', 'progressive metalcore'],

    'jazz': ['jazz', 'swing', 'bebop', 'big band', 'jazz fusion', 'cool jazz', 'hard bop',
             'contemporary jazz', 'smooth jazz', 'latin jazz', 'modal jazz', 'post-bop', 'free jazz',
             'jazz blues', 'jazz funk', 'jazz pop', 'jazz rap', 'jazz trio', 'jazz trumpet',
             'new orleans jazz', 'dixieland', 'smooth saxophone', 'jazz-funk', 'soul jazz'],

    'folk': ['folk', 'folk rock', 'indie folk', 'contemporary folk',
             'traditional folk',
             'american folk revival', 'folk-pop', 'boston folk', 'stomp and holler',
             'irish singer-songwriter', 'singer-songwriter', 'singer-songwriter pop',
             'folk-country', 'irish folk'],

    'blues': ['blues', 'chicago blues', 'delta blues', 'electric blues', 'country blues',
              'contemporary blues', 'blues rock', 'modern blues', 'modern blues rock',
              'piano blues', 'punk blues', 'soul blues', 'swamp blues', 'classic blues',
              'harmonica blues'],

    'classical': ['classical', 'orchestra', 'chamber music', 'symphony', 'opera', 'baroque',
                  'romantic', 'contemporary classical', 'minimalism', 'modern classical',
                  'orchestral', 'choral', 'classical performance', 'classical era',
                  'early romantic era', 'late romantic era', 'post-romantic era',
                  'british contemporary classical', 'polish classical', 'japanese classical',
                  'classical cello', 'classical tenor', 'early music', 'impressionism',
                  'neo-classical', 'orchestral performance', 'orchestral soundtrack',
                  'german baroque', 'italian baroque', 'german romanticism'],

    'world': ['world', 'latin', 'reggae', 'ska', 'afrobeat', 'brazilian', 'caribbean',
              'cumbia', 'salsa', 'samba', 'bossa nova', 'reggaeton', 'tropical',
              'urbano latino', 'reggaeton flow', 'reggaeton chileno', 'reggaeton colombiano',
              'roots reggae', 'reggae fusion', 'ska punk', 'ska mexicano', 'dancehall',
              'funk paulista', 'funk rj', 'funk carioca', 'latin alternative',
              'tropical alternativo'],

    'punk': ['punk', 'punk rock', 'pop punk', 'hardcore punk', 'post-punk', 'art punk',
             'skatepunk', 'melodic punk', 'melodic punk rock', 'canadian pop punk']
}

# Reverse mapping for O(1) subgenre -> parent lookups
GENRE_REVERSE_MAPPING = {}
for parent, children in GENRE_MAPPING.items():
    GENRE_REVERSE_MAPPING[parent] = parent
    for child in children:
        GENRE_REVERSE_MAPPING[child] = parent


def map_to_parent_genre(genre):
    """Map a subgenre to its parent genre."""
    genre = genre.lower().strip()
    return GENRE_REVERSE_MAPPING.get(genre, genre)

CORRECT_RESPONSES = [
    "Correct! That was pure metal—like your amp cranked all the way to eleven! ",
    "Fuck yeah! You’ve got the rhythm of a double-kick drum solo! ",
    "You nailed it! That answer’s sharper than a spiked leather jacket! ",
    "Right answer! You’re shredding harder than a guitarist at a headbanger’s ball! ",
    "Bravo! That was so metal, it melted the stage! ",
    "Nice job! That answer was heavier than a doom metal riff! ",
    "You got it! You’re the lead singer in the symphony of correct answers! ",
    "Correct! You hit that note perfectly, like a power ballad’s soaring chorus! ",
    "Well done! That answer’s more solid than a wall of Marshall stacks! ",
    "Spot on! You’ve got the precision of a perfectly tuned guitar string! "
]

RETRY_RESPONSES = [
    "Not even close. One more shot. ",
    "Nope. You get one more swing at it. ",
    "Wrong, but the encore's not over. One more. ",
    "Miss. Take another run at it. ",
    "That's a no. Last chance on this one. ",
    "Swing and a miss. One more. ",
]

INCORRECT_RESPONSES = [
    "Wrong! That answer was flatter than a deflated stage prop. ",
    "Oops! That guess missed the mark like a bad guitar solo at an encore. ",
    "Not quite! That was about as metal as a plastic tambourine. ",
    "Incorrect! That guess went off the rails like a runaway tour bus! ",
    "Nope! That was heavier than metal—but not in a good way. ",
    "Oops! That answer fell harder than a bass drop in a mosh pit. ",
    "Wrong answer! That guess was more offbeat than a drummer without a metronome. ",
    "Close, but that answer was more squeak than screeching guitar. ",
    "Not quite! That was softer than a metal ballad at an acoustic set. ",
    "Incorrect! That guess was about as tough as a broken guitar string. "
]


def load_song_data():
    """Load the song library once, at startup.

    Returns (dataframe, decades). Dataframe is None if nothing could be loaded.
    """
    try:
        df = library.load_songs()
    except Exception as e:
        logger.error(f"Could not load the song library: {e}")
        df = None

    if df is None or df.empty:
        logger.error("No song data available")
        return None, []

    # The quiz only covers MIN_YEAR onward. This also drops rows with an
    # unreadable Year, which could not be placed in a decade anyway.
    if 'Year' in df.columns:
        year = pd.to_numeric(df['Year'], errors='coerce')
        dropped = int((~(year >= MIN_YEAR)).sum())
        df = df[year >= MIN_YEAR].copy()
        if dropped:
            logger.info(f"Dropped {dropped} songs released before {MIN_YEAR}")

    # Derive Decade from Year when the dataset does not carry it
    if 'Decade' not in df.columns and 'Year' in df.columns:
        year = pd.to_numeric(df['Year'], errors='coerce')
        df['Decade'] = ((year // 10) * 10).astype(int).astype(str) + 's'
        logger.info("Created Decade column from Year")

    df = df[df['Decade'].notna()].copy()

    # Precompute parent genres per row so filtering does not re-parse on every request
    if 'Genres' in df.columns:
        df['ParentGenres'] = df['Genres'].fillna('').apply(
            lambda value: {
                map_to_parent_genre(genre)
                for genre in str(value).split(',')
                if genre.strip()
            }
        )
    else:
        df['ParentGenres'] = [set() for _ in range(len(df))]

    decades = sorted({
        int(str(d).replace('s', ''))
        for d in df['Decade'].unique()
        if str(d).replace('s', '').isdigit()
    })
    logger.info(f"Available decades: {decades}")
    return df, decades


song_data, all_decades = load_song_data()


# Answer matching. Requiring the exact name as a substring meant one wrong
# letter failed the round, so guesses are matched three ways, loosest last.
WHOLE_MATCH_RATIO = 0.8    # "alanis morisett" vs "alanis morissette"
TOKEN_MATCH_RATIO = 0.85   # a single misspelled word
MIN_TOKEN_LENGTH = 5       # short words like "john" are too common to accept alone
MIN_SKELETON_LENGTH = 3    # below this, consonants alone collide too easily

VOWELS = set('aeiouy')

ANSWER_STOPWORDS = {'the', 'and', 'featuring', 'with', 'their', 'band'}


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


def hint_for(current_song):
    """The nudge that comes with the second guess: an initial and a year."""
    lead = primary_artist(current_song.get('artist', ''))
    initial = lead[:1].upper()
    year = str(current_song.get('year', '')).strip()

    parts = []
    if initial:
        parts.append(f'starts with <strong>{html.escape(initial)}</strong>')
    if year and year.lower() not in ('none', 'nan'):
        parts.append(f'charted in <strong>{html.escape(year)}</strong>')

    if not parts:
        return ''
    return 'The artist ' + ' and '.join(parts) + '.'


def consonant_skeleton(value):
    """The consonants of a name, which survive most phonetic misspellings.

    "tpayne" and "tpain" both reduce to "tpn". Character-similarity scores them
    at 0.67 and reject them; people type artist names by ear all the time.
    """
    return ''.join(c for c in value if c.isalnum() and c not in VOWELS)


def _similar(a, b, threshold):
    return SequenceMatcher(None, a, b).ratio() >= threshold


def answer_matches(guess, correct):
    """Is `guess` close enough to `correct` to count? Both come in cleaned."""
    if not guess or not correct:
        return False

    # The full name somewhere in the answer
    if correct in guess:
        return True

    # The whole answer, allowing for typos
    if _similar(guess, correct, WHOLE_MATCH_RATIO):
        return True

    # Names vary in how they're spaced and hyphenated - T-Pain, T Pain, tpain -
    # and cleaning turns punctuation into spaces. Comparing without any spacing
    # judges the letters rather than the styling.
    tight_guess = guess.replace(' ', '')
    tight_correct = correct.replace(' ', '')
    if len(tight_correct) >= 4 and tight_correct in tight_guess:
        return True
    if _similar(tight_guess, tight_correct, WHOLE_MATCH_RATIO):
        return True

    # Spelled by ear: same consonants, different vowels
    skeleton = consonant_skeleton(tight_correct)
    if (len(skeleton) >= MIN_SKELETON_LENGTH
            and skeleton == consonant_skeleton(tight_guess)):
        return True

    # A distinctive word on its own - surname only, or one word misspelled
    guess_words = guess.split()
    for word in correct.split():
        if len(word) < MIN_TOKEN_LENGTH or word in ANSWER_STOPWORDS:
            continue
        if any(_similar(word, other, TOKEN_MATCH_RATIO) for other in guess_words):
            return True

    return False


def playable_url(song):
    """A URL that will still work when the player presses play.

    Deezer signs its preview links with a short expiry, so a stored one is
    usually dead. For those we keep the track id and fetch a fresh link - one
    call. Apple's links don't expire, so a stored one is used as-is. Failing
    both, fall back to a full search.
    """
    source = song.get('PreviewSource')
    track_id = song.get('PreviewId')

    if isinstance(source, str) and isinstance(track_id, str) and track_id:
        fresh = refresh_preview(source, track_id)
        if fresh:
            return fresh

    stored = song.get('PreviewUrl')
    if source not in EXPIRING_SOURCES and isinstance(stored, str) and stored:
        return stored

    return get_preview_url(song['Song'], song['Artist'])


def remember_song(index):
    """Record a song as recently played for this player only."""
    recent = session.get('recent_songs', [])
    recent.append(int(index))
    session['recent_songs'] = recent[-MAX_RECENT_SONGS:]


def pick_song(selected_genres=None, selected_decades=None):
    """Pick a playable song for the quiz. Returns (payload, status_code)."""
    if song_data is None:
        return {'error': 'Song data is unavailable. Please try again later.'}, 503

    filtered_songs = song_data

    if selected_genres:
        wanted = set(selected_genres)
        filtered_songs = filtered_songs[
            filtered_songs['ParentGenres'].apply(lambda genres: bool(genres & wanted))
        ]

    if selected_decades:
        decades = [d if str(d).endswith('s') else f"{d}s" for d in selected_decades]
        filtered_songs = filtered_songs[filtered_songs['Decade'].isin(decades)]

    if len(filtered_songs) == 0:
        described = []
        if selected_genres:
            described.append("genres: " + ", ".join(selected_genres))
        if selected_decades:
            described.append("decades: " + ", ".join(selected_decades))
        return {
            'error': f'No songs found matching your selected {" and ".join(described)}. '
                     'Try different filters!'
        }, 200

    recent = set(session.get('recent_songs', []))

    for attempt in range(PREVIEW_SEARCH_ATTEMPTS):
        available_songs = filtered_songs[~filtered_songs.index.isin(recent)]

        if len(available_songs) == 0:
            session['recent_songs'] = []
            recent = set()
            available_songs = filtered_songs

        song = available_songs.sample(n=1).iloc[0]

        preview_url = playable_url(song)

        if preview_url:
            remember_song(song.name)
            # The answer stays server-side; the browser only gets audio.
            session['current_song'] = {
                'artist': str(song['Artist']),
                'song': str(song['Song']),
                'year': str(song['Year']),
            }
            session['attempts'] = 0
            return {'preview_url': preview_url}, 200

        recent.add(song.name)
        logger.info(f"Attempt {attempt + 1}: no preview, trying another song")

    return {'error': 'Could not find a song with preview. Please try different filters.'}, 200


@app.route('/update_filters', methods=['POST'])
def update_filters():
    """Update the genre and decade filters."""
    try:
        data = request.get_json(silent=True) or {}
        session['selected_genres'] = [str(g).lower() for g in data.get('genres', [])]
        session['selected_decades'] = [str(d) for d in data.get('decades', [])]
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"Error updating filters: {e}")
        return jsonify({'error': 'Could not update filters'}), 500


@app.route('/new-song')
def new_song():
    """Get a new song."""
    try:
        payload, status = pick_song(
            session.get('selected_genres', []),
            session.get('selected_decades', []),
        )
        return jsonify(payload), status
    except Exception as e:
        logger.error(f"Error getting new song: {e}")
        return jsonify({'error': 'Could not load a song. Please try again.'}), 500


# Leaderboard storage. `get_db` and `sql` come from library.py so both tables
# share one connection story.
def init_db():
    id_column = ('id SERIAL PRIMARY KEY' if USE_POSTGRES
                 else 'id INTEGER PRIMARY KEY AUTOINCREMENT')
    with get_db() as conn:
        conn.cursor().execute(f'''
        CREATE TABLE IF NOT EXISTS scores (
            {id_column},
            username TEXT NOT NULL,
            score INTEGER NOT NULL,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        ''')
        conn.commit()
    logger.info(f"Leaderboard storage: {'Postgres' if USE_POSTGRES else DB_PATH}")


# Initialize database
init_db()


@app.after_request
def add_header(response):
    """Add headers to prevent caching."""
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, post-check=0, pre-check=0, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '-1'
    return response


@app.route('/')
def index():
    """Render the main page."""
    if song_data is None:
        return render_template('error.html', message="Failed to load song data")

    return render_template('index.html', max_songs=MAX_SONGS)


# Career totals, grouped case-insensitively so "Mark" and "mark" are one player.
# Every finished game is already a row, so the history needs no extra table.
STANDINGS_QUERY = '''
    SELECT MIN(username), SUM(score), COUNT(*), MAX(score)
    FROM scores
    GROUP BY LOWER(username)
    ORDER BY SUM(score) DESC, COUNT(*) ASC
'''


def standings(limit=LEADERBOARD_SIZE):
    """All-time totals per player, best first."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(sql(STANDINGS_QUERY + ' LIMIT ?'), (limit,))
        return [
            {'username': name, 'total': int(total), 'games': int(games),
             'best': int(best)}
            for name, total, games, best in cursor.fetchall()
        ]


def record_score(username, final_score):
    """Save a finished game and report whether the player is now in the top ten.

    A game where nothing was guessed right isn't a score worth keeping, so it
    never reaches the board.
    """
    if final_score < MIN_RECORDED_SCORE:
        logger.info(f'Not recording a score of {final_score} for {username}')
        return False

    with get_db() as db:
        cursor = db.cursor()
        cursor.execute(sql('INSERT INTO scores (username, score) VALUES (?, ?)'),
                       (username, final_score))
        db.commit()

    # Judge against the board people actually see: all-time totals
    return any(row['username'].lower() == username.lower()
               for row in standings(LEADERBOARD_SIZE))


@app.route('/check-answer', methods=['POST'])
def check_answer():
    """Check if the answer is correct against the song held in the session."""
    try:
        data = request.get_json(silent=True) or {}

        current_song = session.get('current_song')
        if not current_song:
            # Usually a session that expired or was signed by an older key.
            # `reason` lets the browser recover instead of dead-ending.
            return jsonify({
                'error': 'Lost track of that clip. Here comes a fresh one.',
                'reason': 'no_song',
            }), 400

        user_answer = clean_text(str(data.get('answer', '')).lower())
        # Only the lead has to be named - guests don't count either way.
        # Must run before clean_text, which strips the word "featuring" itself.
        correct_artist = clean_text(primary_artist(current_song['artist']).lower())
        correct_song = clean_text(current_song['song'].lower())

        is_correct = (answer_matches(user_answer, correct_artist)
                      or answer_matches(user_answer, correct_song))

        attempts = session.get('attempts', 0) + 1
        session['attempts'] = attempts

        # A first wrong guess buys another try, with a nudge. The round stays
        # open: nothing is scored and the song isn't consumed yet.
        if not is_correct and attempts < MAX_GUESSES:
            return jsonify({
                'correct': False,
                'retry': True,
                'guesses_left': MAX_GUESSES - attempts,
                'message': random.choice(RETRY_RESPONSES) + hint_for(current_song),
                'score': session.get('score', 0),
                'total': session.get('total', 0),
                'game_over': False,
            })

        # Consume the song so the same round cannot be scored twice
        session.pop('current_song', None)
        session.pop('attempts', None)

        session['score'] = session.get('score', 0) + (1 if is_correct else 0)
        session['total'] = session.get('total', 0) + 1

        if is_correct:
            message = random.choice(CORRECT_RESPONSES)
        else:
            message = random.choice(INCORRECT_RESPONSES)
            message += (
                f" The correct answer was '{html.escape(current_song['song'])}' "
                f"by <strong>{html.escape(current_song['artist'])}</strong>."
            )

        game_over = session.get('total', 0) >= MAX_SONGS
        if not game_over:
            return jsonify({
                'correct': is_correct,
                'message': message,
                'score': session.get('score', 0),
                'total': session.get('total', 0),
                'game_over': False
            })

        final_score = session.get('score', 0)
        final_total = session.get('total', 0)
        username = session.get('username')

        made_leaderboard = False
        if username:
            made_leaderboard = record_score(username, final_score)
            if made_leaderboard:
                message = "FUCK!!! NEW LEADERBOARD ENTRY!! " + message

        # Clear game state but keep the player signed in
        session.clear()
        session['username'] = username

        return jsonify({
            'correct': is_correct,
            'message': message,
            'score': final_score,
            'total': final_total,
            'game_over': True,
            'made_leaderboard': made_leaderboard
        })

    except Exception as e:
        logger.error(f"Error checking answer: {e}")
        return jsonify({'error': 'Could not check that answer.'}), 500


@app.route('/leaderboard')
def leaderboard():
    """All-time standings by player."""
    try:
        return jsonify(standings())
    except Exception as e:
        logger.error(f"Error fetching leaderboard: {e}")
        return jsonify({'error': 'Could not load the leaderboard.'}), 500


@app.route('/set_username', methods=['POST'])
def set_username():
    """Set the username in the session."""
    try:
        data = request.get_json(silent=True) or {}
        username = str(data.get('username', '')).strip()[:MAX_USERNAME_LENGTH]
        if not username:
            return jsonify({'error': 'No username provided'}), 400

        session.clear()  # Start a fresh game
        session['username'] = username
        session['score'] = 0
        return jsonify({'status': 'success'})
    except Exception as e:
        logger.error(f"Error setting username: {e}")
        return jsonify({'error': 'Could not set username'}), 500


CLIENT_ERROR_CONTEXT_LENGTH = 60
CLIENT_ERROR_DETAIL_LENGTH = 300


@app.route('/log-error', methods=['POST'])
def log_error():
    """Record a browser-side failure in the server log.

    Without this, anything that breaks in someone's browser - a clip that won't
    play, a request that fails - is only ever seen by that player. Fields are
    truncated because this endpoint is open to anyone.
    """
    data = request.get_json(silent=True) or {}
    context = str(data.get('context', 'unknown'))[:CLIENT_ERROR_CONTEXT_LENGTH]
    detail = str(data.get('detail', ''))[:CLIENT_ERROR_DETAIL_LENGTH]

    current = session.get('current_song') or {}
    logger.warning(
        'client error [%s] %s | song=%s - %s | player=%s | ua=%s',
        context, detail,
        current.get('artist', '-'), current.get('song', '-'),
        session.get('username', '-'),
        request.headers.get('User-Agent', '-')[:120],
    )
    return '', 204


@app.route('/check-session')
def check_session():
    """Check if there's an active session."""
    username = session.get('username')
    return jsonify({'has_session': bool(username), 'username': username})


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    debug = os.environ.get('FLASK_DEBUG', '0') != '0'
    app.run(host='0.0.0.0', port=port, debug=debug)
else:
    # Configure Gunicorn logging
    gunicorn_logger = logging.getLogger('gunicorn.error')
    app.logger.handlers = gunicorn_logger.handlers
    app.logger.setLevel(gunicorn_logger.level)
