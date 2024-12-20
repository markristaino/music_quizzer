import billboard
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
import pandas as pd
from datetime import datetime
import os
from tqdm import tqdm

def get_yearend_billboard_hits(start_year=2016):
    """Get Billboard Year-End Hot 100 hits from 2016 onwards"""
    songs = []
    current_year = datetime.now().year
    
    print(f"Fetching Billboard Year-End Hot 100 from {start_year} to {current_year}...")
    for year in tqdm(range(start_year, current_year + 1)):
        try:
            # Year-end charts use the format 'hot-100-songs-YYYY'
            chart = billboard.ChartData(f'hot-100-songs-{year}')
            for entry in chart:
                songs.append({
                    'Song': entry.title,
                    'Artist': entry.artist,
                    'Year': year,
                    'Rank': entry.rank
                })
            print(f"Added {len(chart)} songs from {year}")
        except Exception as e:
            print(f"Error fetching year {year}: {str(e)}")
            continue
    
    return pd.DataFrame(songs)

def enrich_with_spotify(df, client_id, client_secret):
    """Add Spotify play counts and additional songs from artists"""
    if not client_id or not client_secret:
        print("Spotify credentials not found. Skipping Spotify enrichment.")
        return df
        
    sp = spotipy.Spotify(auth_manager=SpotifyClientCredentials(
        client_id=client_id,
        client_secret=client_secret
    ))
    
    enriched_songs = []
    print("Enriching songs with Spotify data...")
    for idx, row in tqdm(df.iterrows(), total=len(df)):
        try:
            # Search for the original song
            results = sp.search(q=f"track:{row['Song']} artist:{row['Artist']}", type='track', limit=1)
            if results['tracks']['items']:
                track = results['tracks']['items'][0]
                enriched_songs.append({
                    'Song': row['Song'],
                    'Artist': row['Artist'],
                    'Year': row['Year'],
                    'Rank': row['Rank'],
                    'Popularity': track['popularity']
                })
                
                # Get one additional popular song from the same artist
                artist_id = track['artists'][0]['id']
                top_tracks = sp.artist_top_tracks(artist_id)
                if top_tracks['tracks']:
                    top_track = next((t for t in top_tracks['tracks'] if t['name'] != row['Song']), None)
                    if top_track:
                        enriched_songs.append({
                            'Song': top_track['name'],
                            'Artist': row['Artist'],
                            'Year': datetime.now().year,
                            'Rank': None,
                            'Popularity': top_track['popularity']
                        })
        except Exception as e:
            print(f"Error processing {row['Song']} by {row['Artist']}: {str(e)}")
            continue
    
    return pd.DataFrame(enriched_songs)

def update_song_database():
    """Update the song database with recent hits and Spotify data"""
    # Load existing data
    try:
        print("Loading existing Billboard data...")
        existing_df = pd.read_csv('billboard_lyrics_1964-2015.csv', encoding='latin1')
        print(f"Loaded {len(existing_df)} existing songs")
    except Exception as e:
        print(f"Error loading existing data: {str(e)}")
        existing_df = pd.DataFrame()
    
    # Get Billboard year-end hits from 2016 onwards
    recent_df = get_yearend_billboard_hits()
    print(f"Found {len(recent_df)} new songs from Billboard Year-End charts")
    
    # Enrich with Spotify data
    if os.environ.get('SPOTIFY_CLIENT_ID') and os.environ.get('SPOTIFY_CLIENT_SECRET'):
        recent_df = enrich_with_spotify(
            recent_df,
            os.environ['SPOTIFY_CLIENT_ID'],
            os.environ['SPOTIFY_CLIENT_SECRET']
        )
        print(f"Enriched data now contains {len(recent_df)} songs")
    
    # Combine datasets
    if not existing_df.empty:
        combined_df = pd.concat([existing_df, recent_df], ignore_index=True)
        combined_df.drop_duplicates(subset=['Song', 'Artist'], keep='first', inplace=True)
        print(f"Final dataset contains {len(combined_df)} unique songs")
    else:
        combined_df = recent_df
    
    return combined_df

if __name__ == '__main__':
    print("Starting Billboard data update...")
    updated_df = update_song_database()
    updated_df.to_csv('updated_billboard_data.csv', index=False)
    print("Update complete! New data saved to updated_billboard_data.csv")
