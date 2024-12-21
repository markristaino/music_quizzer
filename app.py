from flask import Flask, render_template, request, jsonify, session
import pandas as pd
import deezer
import random
import re
import os
import urllib.request
import tempfile
from datetime import datetime
import sys
import logging
import requests
import sqlite3
from contextlib import contextmanager

# Configure logging
logging.basicConfig(stream=sys.stdout, level=logging.DEBUG)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = 'your-fixed-secret-key-123'  # Change this to any fixed string

# Add session configuration
app.config.update(
    SESSION_COOKIE_SECURE=False,  # Set to True if using HTTPS
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    PERMANENT_SESSION_LIFETIME=1800  # 30 minutes
)

# Initialize Deezer client
client = deezer.Client()

# Global variables
song_data = None
recent_songs = set()  # Keep track of recently played songs
MAX_RECENT_SONGS = 100  # How many songs to remember
all_decades = []  # Store unique decades
MAX_SONGS = 6  # Maximum number of songs per game

# Genre mapping
GENRE_MAPPING = {
    'rock': ['rock', 'alternative rock', 'classic rock', 'hard rock', 'indie rock', 'progressive rock', 
             'psychedelic rock', 'art rock', 'garage rock', 'southern rock', 'rock-and-roll', 'rockabilly',
             'rock and roll', 'album rock', 'modern rock', 'soft rock', 'yacht rock', 'dance rock',
             'roots rock', 'post-grunge', 'modern hard rock', 'modern alternative rock', 'baroque pop',
             'glam rock', 'progressive metal', 'rock en espanol', 'latin rock', 'mexican classic rock',
             'piano rock', 'surf punk', 'indie surf', 'modern folk rock', 'modern power pop', 'new wave'],
             
    'pop': ['pop', 'pop rock', 'indie pop', 'synth-pop', 'dance pop', 'electropop', 'dream pop',
            'chamber pop', 'sophisti-pop', 'art pop', 'k-pop', 'j-pop', 'power pop', 'indie poptimism',
            'pop dance', 'pop folk', 'pop nacional', 'pop soul', 'pop emo', 'pop punk', 'pop r&b',
            'pop rap', 'canadian pop', 'uk pop', 'latin pop', 'adult standards', 'neo mellow',
            'contemporary vocal jazz', 'vocal jazz', 'show tunes', 'easy listening'],
            
    'electronic': ['electronic', 'electronica', 'edm', 'house', 'techno', 'trance', 'dubstep', 'ambient',
                  'drum and bass', 'electro', 'electronic trap', 'electro house', 'progressive house',
                  'deep house', 'tech house', 'tropical house', 'future bass', 'complextro', 'big room',
                  'brostep', 'filthstep', 'future garage', 'intelligent dance music', 'neo-synthpop',
                  'alternative dance', 'dance-punk', 'indietronica', 'canadian electronic', 'slap house',
                  'filter house', 'disco house', 'nu disco', 'compositional ambient', 'ambient pop'],
                  
    'hip hop': ['hip hop', 'rap', 'trap', 'gangster rap', 'underground hip hop', 'conscious hip hop',
                'alternative hip hop', 'east coast hip hop', 'west coast rap', 'southern hip hop',
                'atlanta hip hop', 'chicago rap', 'detroit hip hop', 'memphis rap', 'miami hip hop',
                'houston rap', 'jazz rap', 'political hip hop', 'emo rap', 'cloud rap', 'melodic rap',
                'rage rap', 'atl hip hop', 'atl trap', 'canadian hip hop', 'canadian trap',
                'country rap', 'dfw rap', 'latin hip hop', 'lgbtq+ hip hop', 'plugg', 'pluggnb'],
                
    'r&b': ['r&b', 'soul', 'funk', 'contemporary r&b', 'neo soul', 'motown', 'quiet storm',
            'new jack swing', 'gospel', 'southern soul', 'chicago soul', 'memphis soul', 'philly soul',
            'northern soul', 'soul blues', 'soul jazz', 'funk rock', 'funk metal', 'p funk',
            'synth funk', 'funk pop', 'jazz funk', 'alternative r&b', 'british soul', 'indie soul',
            'trap soul', 'urban contemporary'],
            
    'metal': ['metal', 'heavy metal', 'thrash metal', 'death metal', 'black metal', 'doom metal',
              'power metal', 'progressive metal', 'folk metal', 'gothic metal', 'industrial metal',
              'symphonic metal', 'alternative metal', 'nu metal', 'metalcore', 'melodic metalcore',
              'canadian metal', 'neo classical metal', 'old school thrash', 'prog metal',
              'uk metalcore'],
              
    'jazz': ['jazz', 'swing', 'bebop', 'big band', 'jazz fusion', 'cool jazz', 'hard bop',
             'contemporary jazz', 'smooth jazz', 'latin jazz', 'modal jazz', 'post-bop', 'free jazz',
             'jazz blues', 'jazz funk', 'jazz pop', 'jazz rap', 'jazz trio', 'jazz trumpet',
             'new orleans jazz', 'dixieland', 'smooth saxophone'],
             
    'folk': ['folk', 'folk rock', 'indie folk', 'contemporary folk', 'traditional folk',
             'american folk revival', 'folk-pop', 'boston folk', 'stomp and holler',
             'irish singer-songwriter', 'singer-songwriter', 'singer-songwriter pop'],
             
    'blues': ['blues', 'chicago blues', 'delta blues', 'electric blues', 'country blues',
              'contemporary blues', 'blues rock', 'modern blues', 'modern blues rock',
              'piano blues', 'punk blues', 'soul blues'],
              
    'classical': ['classical', 'orchestra', 'chamber music', 'symphony', 'opera', 'baroque',
                  'romantic', 'contemporary classical', 'minimalism', 'modern classical',
                  'orchestral', 'choral', 'classical performance', 'classical era',
                  'early romantic era', 'late romantic era', 'post-romantic era',
                  'british contemporary classical', 'polish classical', 'japanese classical',
                  'classical cello', 'classical tenor', 'early music', 'impressionism',
                  'neo-classical', 'orchestral performance', 'orchestral soundtrack'],
                  
    'world': ['world', 'latin', 'reggae', 'ska', 'afrobeat', 'brazilian', 'caribbean',
              'cumbia', 'salsa', 'samba', 'bossa nova', 'reggaeton', 'tropical',
              'urbano latino', 'reggaeton flow', 'reggaeton chileno', 'reggaeton colombiano',
              'roots reggae', 'reggae fusion', 'ska punk', 'ska mexicano'],
              
    'punk': ['punk', 'punk rock', 'pop punk', 'hardcore punk', 'post-punk', 'art punk',
             'skate punk', 'chicago punk', 'canadian punk', 'socal pop punk',
             'chicago hardcore', 'emo', 'screamo']
}

# Create reverse mapping for quick lookups
GENRE_REVERSE_MAPPING = {}
for parent, children in GENRE_MAPPING.items():
    for child in children:
        GENRE_REVERSE_MAPPING[child] = parent

def map_to_parent_genre(genre):
    """Map a subgenre to its parent genre."""
    genre = genre.lower().strip()
    for parent, subgenres in GENRE_MAPPING.items():
        if genre == parent or genre in subgenres:
            return parent
    return genre

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

def getRandomResponse(responses):
    return random.choice(responses)

def init_song_data():
    """Initialize song data from CSV, with error handling"""
    global song_data, all_decades
    try:
        # Try loading the updated Spotify data
        try:
            df = pd.read_csv('updated_spotify_data_new.csv', encoding='utf-8')
            logger.info("Loaded updated Spotify dataset")
            
            # Add Decade column if it doesn't exist
            if 'Decade' not in df.columns and 'Year' in df.columns:
                df['Decade'] = (df['Year'] // 10) * 10
                df['Decade'] = df['Decade'].astype(str) + 's'
                logger.info("Created Decade column from Year")
            
        except Exception as e:
            logger.error(f"Failed to load updated Spotify data: {str(e)}")
            # Fall back to original Billboard data if Spotify data not available
            df = pd.read_csv('billboard_lyrics_1964-2015.csv', encoding='latin1')
            logger.info("Loaded original Billboard dataset")
        
        song_data = df
        
        # Get unique decades without 's' suffix for the dropdown
        all_decades = sorted(list(set(int(d.replace('s', '')) for d in df['Decade'].astype(str).unique())))
        logger.info(f"Available decades in data: {all_decades}")
        
        logger.info(f"Loaded {len(song_data)} songs")
        logger.info(f"Found {len(GENRE_MAPPING)} parent genres and {len(all_decades)} decades")
        return True
    except Exception as e:
        logger.error(f"Error loading song data: {str(e)}")
        song_data = None
        return False

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

def get_preview_url(song, artist):
    """Search Deezer for a song and return the preview URL."""
    try:
        logger.info(f"Searching for preview URL - Song: {song}, Artist: {artist}")
        
        # Clean up song and artist names
        clean_song = clean_text(song)
        clean_artist = clean_text(artist)
        logger.info(f"Cleaned text - Song: {clean_song}, Artist: {clean_artist}")
        
        # Try different search strategies
        search_strategies = [
            # Strategy 1: Exact match with both song and artist
            lambda: f'track:"{clean_song}" artist:"{clean_artist}"',
            
            # Strategy 2: Simple combined search
            lambda: f'{clean_song} {clean_artist}',
            
            # Strategy 3: Just the song title
            lambda: clean_song
        ]
        
        for get_query in search_strategies:
            query = get_query()
            logger.info(f"Trying search query: {query}")
            try:
                results = client.search(query)
                logger.info(f"Found {len(results)} results for query: {query}")
                
                if not results:
                    continue
                    
                # Try to find the best match
                for track in results:
                    track_name = clean_text(track.title.lower())
                    track_artist = clean_text(track.artist.name.lower())
                    
                    logger.info(f"Comparing - Track: {track_name}, Artist: {track_artist}")
                    logger.info(f"Preview URL: {track.preview}")
                    
                    # Calculate similarity scores
                    name_match = False
                    artist_match = False
                    
                    # Check song name similarity
                    song_words = set(clean_song.lower().split())
                    track_words = set(track_name.split())
                    common_words = song_words & track_words
                    
                    if len(common_words) >= min(2, len(song_words)):
                        name_match = True
                    
                    # Check artist similarity
                    artist_words = set(clean_artist.lower().split())
                    track_artist_words = set(track_artist.split())
                    
                    if artist_words & track_artist_words:
                        artist_match = True
                    
                    logger.info(f"Match results - Name match: {name_match}, Artist match: {artist_match}")
                    
                    # Accept if both name and artist match reasonably well
                    if name_match and artist_match and track.preview:
                        logger.info(f"Found matching track with preview URL: {track.preview}")
                        return track.preview
            except Exception as e:
                logger.error(f"Error during search with query '{query}': {str(e)}")
                continue
                    
    except Exception as e:
        logger.error(f"Error in get_preview_url: {str(e)}")
    
    logger.warning("No preview URL found after trying all strategies")
    return None

def get_new_song(selected_genres=None, selected_decades=None, max_attempts=5):
    """Get a new song for the quiz."""
    global song_data, recent_songs
    
    try:
        logger.info(f"Selected genres: {selected_genres or 'all'}")
        logger.info(f"Selected decades: {selected_decades or 'all'}")
        
        # Filter songs based on selected genres and decades
        filtered_songs = song_data.copy()
        
        if selected_genres:
            # Handle multiple genres (match if any genre matches)
            genre_mask = filtered_songs['Genres'].fillna('').apply(
                lambda x: any(map_to_parent_genre(genre.strip()) in selected_genres 
                            for genre in str(x).lower().split(','))
            )
            filtered_songs = filtered_songs[genre_mask]
            logger.info(f"After genre filter: {len(filtered_songs)} songs")
        
        if selected_decades:
            # Add 's' suffix if not present
            decades = [f"{d}s" if not d.endswith('s') else d for d in selected_decades]
            filtered_songs = filtered_songs[filtered_songs['Decade'].isin(decades)]
            logger.info(f"After decade filter: {len(filtered_songs)} songs")
        
        if len(filtered_songs) == 0:
            selected_filters = []
            if selected_genres:
                selected_filters.append("genres: " + ", ".join(selected_genres))
            if selected_decades:
                selected_filters.append("decades: " + ", ".join(selected_decades))
            filter_text = " and ".join(selected_filters)
            
            logger.error(f"No songs match the filters: {filter_text}")
            return jsonify({
                'error': f'No songs found matching your selected {filter_text}. Try different filters!'
            })
        
        # Try to find a song with a preview URL
        for attempt in range(max_attempts):
            # Remove recently played songs
            available_songs = filtered_songs[~filtered_songs.index.isin(recent_songs)]
            
            if len(available_songs) == 0:
                # If no songs available with current filters, reset recent songs
                recent_songs.clear()
                available_songs = filtered_songs
                logger.info("Reset recent songs")
            
            # Select a random song
            song = available_songs.sample(n=1).iloc[0]
            logger.info(f"Attempt {attempt + 1}: Selected song: {song['Artist']} - {song['Song']}")
            
            # Try to get preview URL
            preview_url = get_preview_url(song['Song'], song['Artist'])
            if preview_url:
                # Add to recent songs
                recent_songs.add(song.name)
                if len(recent_songs) > MAX_RECENT_SONGS:
                    recent_songs.pop()
                
                return jsonify({
                    'preview_url': preview_url,
                    'artist': song['Artist'],
                    'song': song['Song']
                })
            else:
                logger.info(f"No preview URL found, trying another song...")
        
        # If we get here, we couldn't find a song with preview after max attempts
        logger.error("Could not find any songs with previews after multiple attempts")
        return jsonify({
            'error': 'Could not find a song with preview. Please try different filters.'
        })
        
    except Exception as e:
        logger.error(f"Error getting new song: {str(e)}")
        return jsonify({'error': str(e)})

@app.route('/update_filters', methods=['POST'])
def update_filters():
    """Update the genre and decade filters."""
    try:
        data = request.get_json()
        # Convert genre names to lowercase for consistent matching
        selected_genres = [g.lower() for g in data.get('genres', [])]
        selected_decades = data.get('decades', [])
        
        logger.info(f"Updating filters - Genres: {selected_genres}, Decades: {selected_decades}")
        
        # Apply filters and get a new song
        return get_new_song(selected_genres, selected_decades)
        
    except Exception as e:
        logger.error(f"Error updating filters: {str(e)}")
        return jsonify({'error': str(e)})

# Database setup
def init_db():
    with sqlite3.connect('scores.db') as conn:
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
    conn = sqlite3.connect('scores.db')
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
    if not init_song_data():
        return render_template('error.html', message="Failed to load song data")
    
    # Format genres and decades nicely for display
    formatted_genres = [g.title() for g in GENRE_MAPPING.keys()]  # Use parent genres from mapping
    formatted_decades = [f"{d}s" for d in all_decades]  # Add 's' to decades
    
    return render_template('index.html', 
                         genres=formatted_genres,
                         decades=formatted_decades)

@app.route('/new-song')
def new_song():
    """Get a new song."""
    return get_new_song()

@app.route('/check-answer', methods=['POST'])
def check_answer():
    """Check if the answer is correct."""
    try:
        data = request.get_json()
        user_answer = data.get('answer', '').lower().strip()
        correct_artist = data.get('artist', '').lower().strip()
        correct_song = data.get('song', '').lower().strip()
        
        logger.info(f"Checking answer: {user_answer}")
        logger.info(f"Correct answer: {correct_song} by {correct_artist}")
        
        # Check if either the song or artist name is in the answer
        is_correct = correct_song in user_answer or correct_artist in user_answer
        
        # Update session scores
        session['score'] = session.get('score', 0) + (1 if is_correct else 0)
        session['total'] = session.get('total', 0) + 1
        
        if is_correct:
            message = random.choice(CORRECT_RESPONSES)
        else:
            message = random.choice(INCORRECT_RESPONSES)
            # Format artist name in bold
            message += f" The correct answer was '{correct_song}' by <strong>{data.get('artist')}</strong>."
        
        # Check if game is over
        game_over = session.get('total', 0) >= MAX_SONGS
        if game_over:
            # Get final scores before clearing session
            final_score = session.get('score', 0)
            final_total = session.get('total', 0)
            
            # Save score to leaderboard if username exists
            username = session.get('username')
            made_leaderboard = False
            if username:
                # Check if score makes it to leaderboard (top 10)
                with get_db() as db:
                    current_scores = db.execute(
                        'SELECT score FROM scores ORDER BY score DESC LIMIT 10'
                    ).fetchall()
                    
                    # If less than 10 scores or score beats the lowest score
                    if len(current_scores) < 10 or (current_scores and final_score > current_scores[-1][0]):
                        made_leaderboard = True
                        message = "FUCK!!! NEW LEADERBOARD ENTRY!! " + message
                    
                    # Save the score
                    db.execute('INSERT INTO scores (username, score) VALUES (?, ?)',
                              (username, final_score))
                    db.commit()
            
            # Clear game state but keep username
            username = session.get('username')
            session.clear()
            session['username'] = username
            
            # Use final scores for response
            return jsonify({
                'correct': is_correct,
                'message': message,
                'score': final_score,
                'total': final_total,
                'game_over': game_over,
                'made_leaderboard': made_leaderboard
            })
        
        return jsonify({
            'correct': is_correct,
            'message': message,
            'score': session.get('score', 0),
            'total': session.get('total', 0),
            'game_over': game_over
        })
        
    except Exception as e:
        logger.error(f"Error checking answer: {str(e)}")
        return jsonify({
            'error': 'Error checking answer',
            'message': str(e)
        })

@app.route('/leaderboard')
def leaderboard():
    try:
        with get_db() as conn:
            cursor = conn.execute('''
                SELECT username, score, timestamp 
                FROM scores 
                ORDER BY score DESC 
                LIMIT 10
            ''')
            top_scores = cursor.fetchall()
            return jsonify([{
                'username': row[0],
                'score': row[1],
                'timestamp': row[2]
            } for row in top_scores])
    except Exception as e:
        logger.error(f"Error fetching leaderboard: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/set_username', methods=['POST'])
def set_username():
    """Set the username in the session."""
    try:
        data = request.get_json()
        username = data.get('username')
        if username:
            session.clear()  # Clear entire session
            session['username'] = username
            session['score'] = 0
            return jsonify({'status': 'success'})
        return jsonify({'error': 'No username provided'}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/check-session')
def check_session():
    """Check if there's an active session."""
    username = session.get('username')
    
    return jsonify({
        'has_session': bool(username),
        'username': username
    })

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=True)
else:
    # Configure Gunicorn logging
    gunicorn_logger = logging.getLogger('gunicorn.error')
    app.logger.handlers = gunicorn_logger.handlers
    app.logger.setLevel(gunicorn_logger.level)
