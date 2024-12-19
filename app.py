from flask import Flask, render_template, request, jsonify, session
import pandas as pd
import deezer
import random
import re
import os
import urllib.request
import tempfile
from datetime import datetime

app = Flask(__name__)
app.secret_key = os.urandom(24)  # for session management

# Initialize Deezer client
client = deezer.Client()

# Load Billboard data
try:
    # Get the absolute path to the CSV file
    csv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'billboard_lyrics_1964-2015.csv')
    print(f"Attempting to load CSV file from: {csv_path}")
    df = pd.read_csv(csv_path, encoding='latin1')
    # Filter for top 50 songs
    df = df[df['Rank'] <= 50].copy()
    print(f"Successfully loaded CSV file with {len(df)} rows (filtered to top 50 songs)")
except Exception as e:
    print(f"Error loading CSV file: {str(e)}")
    raise

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
        print(f"Error searching for {song}: {str(e)}")
    
    return None

def get_new_song():
    """Get a random song with preview URL."""
    while True:
        song = df.sample(n=1).iloc[0]
        preview_url = get_preview_url(song['Song'], song['Artist'])
        if preview_url:
            return {
                'song': song['Song'],
                'artist': song['Artist'],
                'preview_url': preview_url
            }

@app.route('/')
def index():
    """Render the main page."""
    return render_template('index.html')

@app.route('/new-song')
def new_song():
    """Get a new song for the quiz."""
    song_data = get_new_song()
    session['current_artist'] = song_data['artist']
    session['current_song'] = song_data['song']
    return jsonify({
        'preview_url': song_data['preview_url']
    })

@app.route('/check-answer', methods=['POST'])
def check_answer():
    """Check if the guess is correct."""
    guess = request.json.get('guess', '').strip().lower()
    correct_artist = session.get('current_artist', '').lower()
    
    # Reject empty guesses
    if not guess:
        return jsonify({
            'correct': False,
            'artist': session['current_artist'],
            'song': session['current_song']
        })
    
    # Clean both guess and correct answer
    guess = clean_text(guess)
    correct_artist = clean_text(correct_artist)
    
    is_correct = (guess == correct_artist or 
                 (len(guess) > 3 and (guess in correct_artist or correct_artist in guess)))
    
    return jsonify({
        'correct': is_correct,
        'artist': session['current_artist'],
        'song': session['current_song']
    })

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=True)
