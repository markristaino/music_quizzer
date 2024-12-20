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
app.secret_key = os.urandom(24)  # for session management

# Initialize Deezer client
client = deezer.Client()

# Global dataframe to store song data
song_data = None

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
        
        # Take a random sample of songs
        df = df.sample(n=min(1000, len(df)))
        
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
    """Get a random song with preview URL."""
    if song_data is None:
        print("Error: Song database not initialized")
        return None
        
    # Simple random selection
    song = song_data.sample(n=1).iloc[0]
    
    preview_url = get_preview_url(song['Song'], song['Artist'])
    if preview_url:
        return {
            'preview_url': preview_url,
            'song': song['Song'],
            'artist': song['Artist']
        }
    return None

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

@app.route('/')
def index():
    """Render the main page."""
    if not init_song_data():
        return render_template('error.html', error_message="Could not load song database"), 500
    return render_template('index.html')

@app.route('/new-song')
def new_song():
    """Get a new song for the quiz."""
    if not init_song_data():
        return jsonify({"error": "Song database not available"}), 500
        
    song_data = get_new_song()
    if not song_data:
        return jsonify({"error": "Could not get new song"}), 500
        
    session['current_artist'] = song_data['artist']
    session['current_song'] = song_data['song']
    return jsonify({
        'preview_url': song_data['preview_url']
    })

@app.route('/check-answer', methods=['POST'])
def check_answer():
    try:
        if not init_song_data():
            return jsonify({"error": "Song database not available"}), 500

        guess = request.json.get('guess', '').strip()
        current_artist = session.get('current_artist', '')
        current_song = session.get('current_song', '')
        
        # Treat empty guesses as incorrect answers
        if not guess:
            # Still increment questions_answered for blank responses
            session['questions_answered'] = session.get('questions_answered', 0) + 1
            
            # If game is over (after 6 questions), save score
            if session.get('questions_answered', 0) >= 6:
                username = session.get('username', 'Anonymous')
                with get_db() as conn:
                    conn.execute('INSERT INTO scores (username, score) VALUES (?, ?)',
                               (username, session.get('score', 0)))
                    conn.commit()
            
            return jsonify({
                'correct': False,
                'answer': f"**{current_artist}** - {current_song}",
                'score': session.get('score', 0),
                'questions_answered': session.get('questions_answered', 0)
            })
        
        # Clean both guess and correct answer
        guess = clean_text(guess)
        correct_artist = clean_text(current_artist)
        
        # Check if the guess matches or is a substring (if longer than 3 chars)
        is_correct = (guess.lower() == correct_artist.lower() or 
                     (len(guess) > 3 and (guess.lower() in correct_artist.lower() or 
                                        correct_artist.lower() in guess.lower())))
        
        # Update score in session
        session['score'] = session.get('score', 0) + (1 if is_correct else 0)
        session['questions_answered'] = session.get('questions_answered', 0) + 1
        
        # If game is over (after 6 questions), save score
        if session.get('questions_answered', 0) >= 6:
            username = session.get('username', 'Anonymous')
            with get_db() as conn:
                conn.execute('INSERT INTO scores (username, score) VALUES (?, ?)',
                           (username, session.get('score', 0)))
                conn.commit()
        
        return jsonify({
            'correct': is_correct,
            'answer': f"**{current_artist}** - {current_song}",
            'score': session.get('score', 0),
            'questions_answered': session.get('questions_answered', 0)
        })
    except Exception as e:
        logger.error(f"Error in check_answer: {str(e)}")
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

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=True)
else:
    # Configure Gunicorn logging
    gunicorn_logger = logging.getLogger('gunicorn.error')
    app.logger.handlers = gunicorn_logger.handlers
    app.logger.setLevel(gunicorn_logger.level)
