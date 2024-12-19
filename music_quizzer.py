import pandas as pd
import random
import re
from pygame import mixer
import time
import deezer
import urllib.request
import os
import tempfile

# Initialize Deezer client
client = deezer.Client()

# Load Billboard data
df = pd.read_csv('billboard_lyrics_1964-2015.csv', encoding='latin1')

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
    
    print(f"Could not find a preview for {song} by {artist}. Skipping...")
    return None

def play_clip(url):
    """Play a song preview clip from the given URL."""
    if not url:
        return
        
    try:
        # Create a temporary file
        temp_dir = tempfile.gettempdir()
        temp_file = os.path.join(temp_dir, 'preview.mp3')
        
        # Download the preview
        urllib.request.urlretrieve(url, temp_file)
        
        # Play the preview
        mixer.init()
        mixer.music.load(temp_file)
        mixer.music.play()
        time.sleep(20)  # Play for 20 seconds
        mixer.music.stop()
        mixer.quit()
        
        # Clean up
        try:
            os.remove(temp_file)
        except:
            pass
            
    except Exception as e:
        print(f"Error playing clip: {str(e)}")

def quiz():
    """Run the music quiz game."""
    print("\nWelcome to the Music Quiz!")
    print("I'll play a clip of a song, and you try to guess the artist.")
    print("Type your answer and press Enter. Press Ctrl+C to quit.\n")
    
    # Get 10 random songs from the dataset
    songs = df.sample(n=10)[['Song', 'Artist']].values
    score = 0
    
    try:
        for song, artist in songs:
            url = get_preview_url(song, artist)
            
            if not url:
                continue
            
            print("\nGuess the artist for this song:")
            play_clip(url)
            
            try:
                guess = input("Your guess: ").strip().lower()
                correct = clean_text(artist).lower()
                
                if guess in correct or correct in guess:
                    print("Correct! ")
                    score += 1
                else:
                    print(f"Sorry, it was {artist}")
                
                time.sleep(1)
            except EOFError:
                print("\nQuiz ended.")
                break
                
    except KeyboardInterrupt:
        print("\nQuiz ended.")
    finally:
        print(f"\nFinal score: {score}/{len(songs)}")

def analyze_dataset():
    """Analyze the dataset and Deezer preview availability."""
    print("\nAnalyzing dataset and Deezer availability...")
    
    # Sample songs from different decades
    decades = df.groupby(df['Year'] // 10 * 10)
    
    results = []
    for decade, group in decades:
        sample = group.sample(min(5, len(group)))
        for _, row in sample.iterrows():
            song, artist = row['Song'], row['Artist']
            url = get_preview_url(song, artist)
            results.append({
                'decade': decade,
                'song': song,
                'artist': artist,
                'has_preview': bool(url)
            })
    
    # Print results
    print("\nResults by decade:")
    for decade in sorted(set(r['decade'] for r in results)):
        decade_results = [r for r in results if r['decade'] == decade]
        success_rate = sum(1 for r in decade_results if r['has_preview']) / len(decade_results)
        print(f"\n{decade}s:")
        print(f"Success rate: {success_rate * 100:.1f}%")
        for r in decade_results:
            status = "" if r['has_preview'] else ""
            print(f"{status} {r['song']} by {r['artist']}")

if __name__ == "__main__":
    quiz()
    analyze_dataset()
