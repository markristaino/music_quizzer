import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
import pandas as pd
from datetime import datetime
import os
from tqdm import tqdm

def init_spotify():
    """Initialize Spotify client"""
    client_id = os.environ.get('SPOTIFY_CLIENT_ID')
    client_secret = os.environ.get('SPOTIFY_CLIENT_SECRET')
    
    if not client_id or not client_secret:
        raise ValueError("Spotify credentials not found in environment variables")
    
    return spotipy.Spotify(auth_manager=SpotifyClientCredentials(
        client_id=client_id,
        client_secret=client_secret
    ))

def get_artist_top_tracks(sp, artist_id):
    """Get top tracks from an artist"""
    try:
        results = sp.artist_top_tracks(artist_id)
        return [{
            'Song': track['name'],
            'Artist': track['artists'][0]['name'],
            'Year': track['album']['release_date'][:4],
            'Popularity': track['popularity'],
            'Source': 'Artist Top Tracks'
        } for track in results['tracks']]
    except Exception as e:
        print(f"Error getting top tracks for artist {artist_id}: {str(e)}")
        return []

def get_related_artists_tracks(sp, artist_id, max_related=3):
    """Get top tracks from related artists"""
    tracks = []
    try:
        related = sp.artist_related_artists(artist_id)
        for artist in related['artists'][:max_related]:
            tracks.extend(get_artist_top_tracks(sp, artist['id']))
    except Exception as e:
        print(f"Error getting related artists for {artist_id}: {str(e)}")
    return tracks

def get_top_artists(sp, genres=None):
    """Get top artists by genre"""
    if genres is None:
        genres = ['pop', 'rock', 'hip hop', 'rap', 'r&b', 'country', 'electronic']
    
    artists = []
    for genre in genres:
        try:
            results = sp.search(q=f'genre:"{genre}"', type='artist', limit=20)
            artists.extend(results['artists']['items'])
        except Exception as e:
            print(f"Error searching genre {genre}: {str(e)}")
            continue
    
    # Remove duplicates and sort by popularity
    unique_artists = {artist['id']: artist for artist in artists}.values()
    return sorted(unique_artists, key=lambda x: x['popularity'], reverse=True)

def update_song_database():
    """Update the song database with Spotify data"""
    try:
        print("Loading existing Billboard data...")
        existing_df = pd.read_csv('billboard_lyrics_1964-2015.csv', encoding='latin1')
        print(f"Loaded {len(existing_df)} existing songs")
    except Exception as e:
        print(f"Error loading existing data: {str(e)}")
        existing_df = pd.DataFrame()
    
    sp = init_spotify()
    all_tracks = []
    
    # Get top artists across different genres
    print("Finding top artists across genres...")
    top_artists = get_top_artists(sp)
    print(f"Found {len(top_artists)} top artists")
    
    # Get tracks from top artists and their related artists
    print("\nFetching tracks from top artists and their related artists...")
    for artist in tqdm(top_artists):
        try:
            # Get artist's top tracks
            tracks = get_artist_top_tracks(sp, artist['id'])
            all_tracks.extend(tracks)
            
            # Get related artists' tracks
            related_tracks = get_related_artists_tracks(sp, artist['id'])
            all_tracks.extend(related_tracks)
            
            print(f"Added {len(tracks)} tracks from {artist['name']} and {len(related_tracks)} from related artists")
        except Exception as e:
            print(f"Error processing artist {artist['name']}: {str(e)}")
            continue
    
    # Convert to DataFrame and remove duplicates
    if all_tracks:
        spotify_df = pd.DataFrame(all_tracks)
        spotify_df.drop_duplicates(subset=['Song', 'Artist'], keep='first', inplace=True)
        
        # Sort by popularity and keep top songs
        spotify_df = spotify_df.sort_values('Popularity', ascending=False)
        spotify_df = spotify_df.head(1000)  # Keep top 1000 songs
        
        print(f"\nCollected {len(spotify_df)} unique songs from Spotify")
        
        # Combine with existing data
        if not existing_df.empty:
            # Add popularity column to existing data if it doesn't exist
            if 'Popularity' not in existing_df.columns:
                existing_df['Popularity'] = 70  # Default popularity for old songs
            if 'Source' not in existing_df.columns:
                existing_df['Source'] = 'Billboard Historical'
                
            combined_df = pd.concat([existing_df, spotify_df], ignore_index=True)
            combined_df.drop_duplicates(subset=['Song', 'Artist'], keep='first', inplace=True)
            print(f"Final dataset contains {len(combined_df)} unique songs")
        else:
            combined_df = spotify_df
        
        return combined_df
    else:
        print("No tracks collected from Spotify")
        return existing_df

if __name__ == '__main__':
    print("Starting Spotify data update...")
    updated_df = update_song_database()
    if len(updated_df) > 0:
        updated_df.to_csv('updated_spotify_data.csv', index=False)
        print("Update complete! New data saved to updated_spotify_data.csv")
    else:
        print("Error: No data collected")
