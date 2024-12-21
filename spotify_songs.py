import os
import time
import json
import sys
import pandas as pd
from tqdm import tqdm
import pylast
from concurrent.futures import ThreadPoolExecutor
from queue import Queue
from threading import Lock

# Last.fm API setup
API_KEY = "0243f85294f0317b7bf2dcce8ff639e1"
API_SECRET = "f40c2aeec15941f9c7fd18ae1b7254a1"

network = pylast.LastFMNetwork(
    api_key=API_KEY,
    api_secret=API_SECRET,
)

# Rate limiting setup
request_queue = Queue()
rate_limit_lock = Lock()
last_request_time = 0
MIN_REQUEST_INTERVAL = 0.2  # 200ms between requests (5 requests per second)

def rate_limited_request(func, *args, **kwargs):
    """Execute a function with rate limiting"""
    global last_request_time
    
    with rate_limit_lock:
        current_time = time.time()
        time_since_last = current_time - last_request_time
        if time_since_last < MIN_REQUEST_INTERVAL:
            time.sleep(MIN_REQUEST_INTERVAL - time_since_last)
        last_request_time = time.time()
        
    return func(*args, **kwargs)

def get_artist_genres_lastfm(artist_name):
    """Get artist genres from Last.fm using top tags"""
    try:
        # Search for the artist
        artist = rate_limited_request(network.get_artist, artist_name)
        
        # Get top tags (these are effectively genres)
        tags = rate_limited_request(artist.get_top_tags, limit=10)
        
        # Filter tags by weight (popularity) and convert to genres
        genres = []
        for tag in tags:
            try:
                # Convert weight to int and compare
                if int(tag.weight) >= 25:
                    # Clean up the tag name
                    genre = tag.item.get_name().lower().strip()
                    # Skip non-genre tags like "seen live", "favourite", etc
                    if genre not in {'seen live', 'favourite', 'favorite', 'spotify', 'under 2000 listeners'}:
                        genres.append(genre)
            except (ValueError, TypeError):
                # Skip tags with invalid weights
                continue
        
        print(f"Found genres for {artist_name}: {genres}", flush=True)
        return genres
        
    except pylast.WSError as e:
        if "The artist you supplied could not be found" in str(e):
            print(f"Artist not found: {artist_name}", flush=True)
        else:
            print(f"Last.fm API error for {artist_name}: {e}", flush=True)
        return []
    except Exception as e:
        print(f"Error getting genres for {artist_name}: {e}", flush=True)
        return []

def process_artist_batch(artists, artist_to_indices, input_df):
    """Process a batch of artists in parallel"""
    results = {}
    with ThreadPoolExecutor(max_workers=5) as executor:  # 5 parallel requests
        future_to_artist = {
            executor.submit(get_artist_genres_lastfm, artist): artist 
            for artist in artists
        }
        for future in tqdm(future_to_artist, desc="Processing batch", leave=False):
            artist = future_to_artist[future]
            try:
                genres = future.result()
                if genres:
                    results[artist] = genres
            except Exception as e:
                print(f"Error processing {artist}: {e}", flush=True)
    
    # Update dataframe with results
    for artist, genres in results.items():
        if genres:
            genres_str = ','.join(genres)
            for idx in artist_to_indices[artist]:
                input_df.at[idx, 'Genres'] = genres_str
    
    return len(results)

def update_songs(input_df, output_file):
    """Main function to update song database"""
    print("Starting update process...", flush=True)
    
    # First identify unique artists that need processing
    missing_genres = input_df['Genres'].isna()
    unique_artists = input_df.loc[missing_genres, 'Artist'].unique()
    
    print("\nSample of original artist names:", flush=True)
    print(unique_artists[:10], flush=True)
    
    # Clean artist names and remove duplicates
    cleaned_artists = {clean_artist_name(artist) for artist in unique_artists}
    cleaned_artists = sorted(list(cleaned_artists))  # Convert to sorted list
    
    print("\nSample of cleaned artist names:", flush=True)
    print(cleaned_artists[:10], flush=True)
    
    total_artists = len(cleaned_artists)
    print(f"\nFound {total_artists} unique primary artists needing genre data", flush=True)
    
    # Create a lookup for all songs by these artists
    artist_to_indices = {}
    for idx, row in input_df.iterrows():
        if pd.isna(row['Genres']):
            artist = clean_artist_name(row['Artist'])
            if artist in cleaned_artists:
                if artist not in artist_to_indices:
                    artist_to_indices[artist] = []
                artist_to_indices[artist].append(idx)
    
    # Process artists in batches
    batch_size = 50  # Larger batches since Last.fm is faster
    processed_count = 0
    start_time = time.time()
    
    try:
        with tqdm(total=total_artists, desc="Overall progress") as pbar:
            for i in range(0, total_artists, batch_size):
                batch = cleaned_artists[i:i + batch_size]
                
                # Process batch
                batch_processed = process_artist_batch(batch, artist_to_indices, input_df)
                processed_count += batch_processed
                
                # Calculate progress stats
                elapsed = time.time() - start_time
                rate = processed_count / elapsed if elapsed > 0 else 0
                eta = (total_artists - processed_count) / rate if rate > 0 else 0
                
                print(f"\rProcessed {processed_count}/{total_artists} artists "
                      f"({processed_count/total_artists*100:.1f}%) "
                      f"| Rate: {rate:.1f} artists/sec "
                      f"| ETA: {eta/60:.1f} minutes", flush=True)
                
                # Save progress after each batch
                input_df.to_csv(output_file, index=False)
                
                pbar.update(len(batch))
                
    except Exception as e:
        print(f"\nFatal error in update_songs: {e}", flush=True)
        raise
    
    finally:
        # Save final progress
        input_df.to_csv(output_file, index=False)
        print(f"\n\nCompleted processing {processed_count} artists", flush=True)
        
    return input_df

def clean_artist_name(artist):
    """Clean artist name by removing featured artists and common separators"""
    # List of words that indicate featured artists
    featured_indicators = [
        'featuring', 'feat.', 'feat', 'ft.', 'ft', 'with',
        ' & ', ' x ', ' vs. ', ' vs ', ' presents ', ' pres. '  # Added spaces around indicators
    ]
    
    # Convert to lowercase for comparison
    artist = artist.lower().strip()
    
    # Split on common separators - only when they're surrounded by spaces
    for separator in featured_indicators:
        if separator in artist:
            # Take only the first part (primary artist)
            artist = artist.split(separator)[0]
            break  # Stop after first match to avoid over-splitting
    
    # Remove any trailing/leading whitespace
    return artist.strip()

def compile_existing_genres(df):
    """Compile all known genres for artists from existing data"""
    # Create a mask for valid genre entries
    valid_genres = (df['Genres'].notna()) & (df['Genres'] != '') & (df['Genres'] != 'Unknown')
    
    # Group by artist and get their genres
    artist_genres = (df[valid_genres]
                    .groupby('Artist', as_index=False)
                    .agg({'Genres': 'first'})  # Take first valid genre for each artist
                    .set_index('Artist')['Genres']
                    .str.lower()  # Normalize to lowercase
                    .to_dict())
    
    return artist_genres

def update_song_database(input_file='spotify_songs.csv', 
                        output_file='updated_spotify_data_new.csv'):
    """Main function to update song database"""
    print(f"Loading Spotify database: {input_file}", flush=True)
    sys.stdout.flush()
    df = pd.read_csv(input_file)
    
    # Convert year to string if it exists
    if 'Year' in df.columns:
        df['Year'] = df['Year'].astype(str)
    
    # Initialize columns if they don't exist
    if 'Genres' not in df.columns:
        df['Genres'] = None
    if 'Popularity' not in df.columns:
        df['Popularity'] = None
    
    # First compile all known genres
    artist_genres = compile_existing_genres(df)
    print(f"Found {len(artist_genres)} artists with known genres", flush=True)
    sys.stdout.flush()
    
    # Apply known genres to any missing entries
    missing_genres = df['Genres'].isna()
    genres_applied = 0
    for idx, row in df[missing_genres].iterrows():
        artist = row['Artist'].lower()
        if artist in artist_genres:
            df.at[idx, 'Genres'] = artist_genres[artist]
            genres_applied += 1
    
    print(f"Applied existing genres to {df['Genres'].notna().sum()} songs", flush=True)
    sys.stdout.flush()
    print(f"Still missing genres for {df['Genres'].isna().sum()} songs", flush=True)
    sys.stdout.flush()
    
    # Always proceed to update_songs to get new genres from Last.fm
    updated_df = update_songs(df, output_file)
    print(f"\nUpdate complete! Results saved to {output_file}", flush=True)
    sys.stdout.flush()
    return updated_df

def test_lastfm_connection():
    """Test the Last.fm connection with timing information"""
    print("Starting Last.fm connection test...", flush=True)
    sys.stdout.flush()
    
    try:
        print("Initializing Last.fm client...", flush=True)
        sys.stdout.flush()
        
        # Test a simple search
        print("\nTesting search API...", flush=True)
        sys.stdout.flush()
        
        print("Making search request...", flush=True)
        sys.stdout.flush()
        
        start_time = time.time()
        artist = network.get_artist("Radiohead")
        tags = artist.get_top_tags(limit=5)
        end_time = time.time()
        
        print(f"Search API call took {(end_time - start_time):.2f} seconds", flush=True)
        print(f"Found artist: {artist.name}", flush=True)
        print("Top tags:", [tag.item.get_name() for tag in tags[:5]], flush=True)
        sys.stdout.flush()
        
        return True
            
    except Exception as e:
        print(f"\nError in test_lastfm_connection:", flush=True)
        print(f"Error type: {type(e)}", flush=True)
        print(f"Error message: {str(e)}", flush=True)
        print(f"Error args: {e.args}", flush=True)
        sys.stdout.flush()
        return False

if __name__ == "__main__":
    # Test Last.fm connection
    print("Testing Last.fm connection...", flush=True)
    sys.stdout.flush()
    test_lastfm_connection()
    
    # Update song database
    update_song_database(input_file='updated_spotify_data.csv', 
                        output_file='updated_spotify_data_new.csv')
