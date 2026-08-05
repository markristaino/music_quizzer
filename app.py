from flask import Flask, render_template, request, jsonify, session
import pandas as pd
import deezer
import random
import re
import os
import html
import sys
import logging
import sqlite3
from contextlib import contextmanager
from functools import lru_cache

# Configure logging
logging.basicConfig(stream=sys.stdout, level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Gunicorn imports this module as "app"; running it directly means local dev.
RUNNING_LOCALLY = __name__ == '__main__'

secret_key = os.environ.get('SECRET_KEY')
if not secret_key:
    secret_key = os.urandom(32)
    logger.warning(
        "SECRET_KEY is not set - using a random key. Sessions will not survive a restart."
    )
app.secret_key = secret_key

app.config.update(
    SESSION_COOKIE_SECURE=os.environ.get(
        'SESSION_COOKIE_SECURE', '0' if RUNNING_LOCALLY else '1'
    ) != '0',
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    PERMANENT_SESSION_LIFETIME=1800  # 30 minutes
)

# Initialize Deezer client
client = deezer.Client()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(BASE_DIR, 'updated_spotify_data_new.csv')
FALLBACK_DATA_FILE = os.path.join(BASE_DIR, 'billboard_lyrics_1964-2015.csv')
DB_PATH = os.environ.get('SCORES_DB', os.path.join(BASE_DIR, 'scores.db'))

MAX_SONGS = 6              # Songs per game
MAX_RECENT_SONGS = 50      # Per-player replay memory
MAX_USERNAME_LENGTH = 32
LEADERBOARD_SIZE = 10
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


def clean_text(text):
    """Clean up text by removing special characters and normalizing spaces."""
    # Convert contractions to full words
    text = text.replace("don't", "dont")
    text = text.replace("couldn't", "couldnt")
    text = text.replace("won't", "wont")
    text = text.replace("can't", "cant")
    text = text.replace("ain't", "aint")
    text = text.replace("'bout", "bout")
    text = text.replace("'n'", "and")
    text = text.replace("'", "")  # Remove remaining apostrophes

    # Remove text in parentheses and brackets
    text = re.sub(r'\([^)]*\)', '', text)
    text = re.sub(r'\[[^\]]*\]', '', text)

    # Remove featuring, feat., ft., etc.
    text = re.sub(r'feat\.?|ft\.?|featuring', '', text, flags=re.IGNORECASE)

    # Remove special characters but preserve letters and numbers
    text = re.sub(r'[^\w\s]', ' ', text)

    # Normalize whitespace
    text = ' '.join(text.split())
    return text.strip()


def load_song_data():
    """Load the song dataset from disk once, at startup.

    Returns (dataframe, decades). Dataframe is None if nothing could be loaded.
    """
    df = None
    for path, encoding in ((DATA_FILE, 'utf-8'), (FALLBACK_DATA_FILE, 'latin1')):
        try:
            df = pd.read_csv(path, encoding=encoding)
            logger.info(f"Loaded {len(df)} songs from {os.path.basename(path)}")
            break
        except Exception as e:
            logger.error(f"Could not load {path}: {e}")

    if df is None:
        logger.error("No song data available")
        return None, []

    # Derive Decade from Year when the dataset does not carry it
    if 'Decade' not in df.columns and 'Year' in df.columns:
        year = pd.to_numeric(df['Year'], errors='coerce')
        df = df[year.notna()].copy()
        df['Decade'] = ((year[year.notna()] // 10) * 10).astype(int).astype(str) + 's'
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


@lru_cache(maxsize=4096)
def get_preview_url(song, artist):
    """Search Deezer for a song and return the preview URL (cached, including misses)."""
    try:
        clean_song = clean_text(song)
        clean_artist = clean_text(artist)

        search_strategies = [
            f'track:"{clean_song}" artist:"{clean_artist}"',   # exact match on both
            f'{clean_song} {clean_artist}',                    # simple combined search
            clean_song,                                        # title only
        ]

        song_words = set(clean_song.lower().split())
        artist_words = set(clean_artist.lower().split())

        for query in search_strategies:
            try:
                results = client.search(query)
            except Exception as e:
                logger.error(f"Deezer search failed for '{query}': {e}")
                continue

            if not results:
                continue

            for track in results:
                if not track.preview:
                    continue

                track_words = set(clean_text(track.title.lower()).split())
                track_artist_words = set(clean_text(track.artist.name.lower()).split())

                name_match = len(song_words & track_words) >= min(2, len(song_words))
                artist_match = bool(artist_words & track_artist_words)

                if name_match and artist_match:
                    return track.preview
    except Exception as e:
        logger.error(f"Error in get_preview_url: {e}")

    logger.info(f"No preview found for {artist} - {song}")
    return None


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
        preview_url = get_preview_url(song['Song'], song['Artist'])

        if preview_url:
            remember_song(song.name)
            # The answer stays server-side; the browser only gets audio.
            session['current_song'] = {
                'artist': str(song['Artist']),
                'song': str(song['Song']),
            }
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


# Database setup
def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute('''
        CREATE TABLE IF NOT EXISTS scores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            score INTEGER NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        ''')


@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    try:
        yield conn
    finally:
        conn.close()


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

    return render_template('index.html',
                           genres=[g.title() for g in GENRE_MAPPING],
                           decades=[f"{d}s" for d in all_decades],
                           max_songs=MAX_SONGS)


def record_score(username, final_score):
    """Save a finished game and report whether it reached the leaderboard."""
    with get_db() as db:
        cursor = db.execute(
            'SELECT score FROM scores ORDER BY score DESC LIMIT ?', (LEADERBOARD_SIZE,)
        )
        current_scores = [row[0] for row in cursor.fetchall()]
        made_leaderboard = (
            len(current_scores) < LEADERBOARD_SIZE or final_score > current_scores[-1]
        )

        db.execute('INSERT INTO scores (username, score) VALUES (?, ?)',
                   (username, final_score))
        db.commit()

    return made_leaderboard


@app.route('/check-answer', methods=['POST'])
def check_answer():
    """Check if the answer is correct against the song held in the session."""
    try:
        data = request.get_json(silent=True) or {}

        current_song = session.get('current_song')
        if not current_song:
            return jsonify({'error': 'No song in progress. Please load a new song.'}), 400

        user_answer = clean_text(str(data.get('answer', '')).lower())
        correct_artist = clean_text(current_song['artist'].lower())
        correct_song = clean_text(current_song['song'].lower())

        is_correct = bool(user_answer) and (
            correct_song in user_answer or correct_artist in user_answer
        )

        # Consume the song so the same round cannot be scored twice
        session.pop('current_song', None)

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
    try:
        with get_db() as conn:
            cursor = conn.execute('''
                SELECT username, score, timestamp
                FROM scores
                ORDER BY score DESC
                LIMIT ?
            ''', (LEADERBOARD_SIZE,))
            return jsonify([
                {'username': row[0], 'score': row[1], 'timestamp': row[2]}
                for row in cursor.fetchall()
            ])
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
