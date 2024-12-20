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

def init_song_data():
    """Initialize song data from CSV, with error handling"""
    global song_data
    try:
        # Try loading the updated Spotify data first
        try:
            df = pd.read_csv('updated_spotify_data.csv', encoding='utf-8')
            logger.info("Loaded updated Spotify dataset")
        except:
            # Fall back to original Billboard data if Spotify data not available
            df = pd.read_csv('billboard_lyrics_1964-2015.csv', encoding='latin1')
            logger.info("Loaded original Billboard dataset")
        
        song_data = df
        logger.info(f"Loaded {len(song_data)} songs")
        return True
    except Exception as e:
        logger.error(f"Error loading song data: {str(e)}")
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
        # Clean up song and artist names
        clean_song = clean_text(song)
        clean_artist = clean_text(artist)
        
        # Try different search strategies
        search_strategies = [
            # Strategy 1: Exact match with both song and artist
            lambda: f'track:"{clean_song}" artist:"{clean_artist}"',
            
            # Strategy 2: Simple combined search
            lambda: f'{clean_song} {clean_artist}',
            
            # Strategy 3: Just the song title
            lambda: clean_song,
            
            # Strategy 4: Search by artist and first few words of song
            lambda: f'{" ".join(clean_song.split()[:3])} {clean_artist}',
            
            # Strategy 5: Search by artist's first name/word and song
            lambda: f'{clean_song} {clean_artist.split()[0]}',
            
            # Strategy 6: Search by just the artist
            lambda: clean_artist
        ]
        
        for get_query in search_strategies:
            query = get_query()
            results = client.search(query)
            
            if not results:
                continue
                
            # Try to find the best match
            for track in results:
                track_name = clean_text(track.title.lower())
                track_artist = clean_text(track.artist.name.lower())
                
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
                
                # Accept if both name and artist match reasonably well
                if name_match and artist_match and track.preview:
                    return track.preview
                        
    except Exception as e:
        logger.error(f"Error searching for {song}: {str(e)}", exc_info=True)
    
    return None

def get_new_song():
    """Get a new song for the quiz."""
    try:
        logger.info(f"Session before new song: {dict(session)}")
        
        if song_data is None:
            init_song_data()
        
        # Simple random selection
        song = song_data.sample(n=1).iloc[0]
        preview_url = get_preview_url(song['Song'], song['Artist'])
        
        if preview_url:
            # Store current song info in session
            session['current_song'] = song['Song']
            session['current_artist'] = song['Artist']
            
            logger.info(f"Session after new song: {dict(session)}")
            
            return jsonify({
                'preview_url': preview_url
            })
        return jsonify({'error': 'No preview available'}), 404
        
    except Exception as e:
        logger.error(f"Error getting new song: {str(e)}")
        return jsonify({'error': str(e)}), 500

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
        return render_template('error.html', error_message="Could not load song database"), 500
    return render_template('index.html')

@app.route('/new-song')
def new_song():
    """Get a new song for the quiz."""
    try:
        logger.info(f"Session before new song: {dict(session)}")
        
        if song_data is None:
            init_song_data()
        
        # Simple random selection
        song = song_data.sample(n=1).iloc[0]
        preview_url = get_preview_url(song['Song'], song['Artist'])
        
        if preview_url:
            # Store current song info in session
            session['current_song'] = song['Song']
            session['current_artist'] = song['Artist']
            
            logger.info(f"Session after new song: {dict(session)}")
            
            return jsonify({
                'preview_url': preview_url
            })
        return jsonify({'error': 'No preview available'}), 404
        
    except Exception as e:
        logger.error(f"Error getting new song: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/check-answer', methods=['POST'])
def check_answer():
    """Check if the answer is correct."""
    try:
        guess = request.json.get('guess', '').strip()
        current_song = session.get('current_song')
        current_artist = session.get('current_artist')
        
        if not current_song or not current_artist:
            return jsonify({'error': 'No song in play'}), 400
        
        # Initialize response
        response = {
            'correct': False,
            'message': '',
            'correct_answer': {
                'song': current_song,
                'artist': current_artist
            }
        }
        
        # Check if answer is correct (case insensitive)
        if guess.lower() == current_artist.lower():
            response['correct'] = True
            response['message'] = "Correct!"
            session['score'] = session.get('score', 0) + 1
        else:
            response['message'] = "Incorrect."
        
        # Increment questions answered
        session['questions_answered'] = session.get('questions_answered', 0) + 1
        
        # Add score to response
        response['score'] = session.get('score', 0)
        response['total'] = session.get('questions_answered', 0)
        
        # Check if game is over
        if session.get('questions_answered', 0) >= 6:
            response['game_over'] = True
            
            # Save score to leaderboard
            username = session.get('username', 'Anonymous')
            with get_db() as db:
                db.execute('INSERT INTO scores (username, score) VALUES (?, ?)',
                          (username, session.get('score', 0)))
                db.commit()
            
            # Clear game state but keep username
            username = session.get('username')
            session.clear()
            session['username'] = username
        
        return jsonify(response)
        
    except Exception as e:
        logger.error(f"Error checking answer: {str(e)}")
        return jsonify({'error': str(e)}), 500

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
    username = request.json.get('username', 'Anonymous')
    session['username'] = username
    return jsonify({'success': True})

@app.route('/check-session')
def check_session():
    """Check if user has an active session."""
    return jsonify({
        'username': session.get('username', None)
    })

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=True)
else:
    # Configure Gunicorn logging
    gunicorn_logger = logging.getLogger('gunicorn.error')
    app.logger.handlers = gunicorn_logger.handlers
    app.logger.setLevel(gunicorn_logger.level)
