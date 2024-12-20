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

def get_track_year(sp, track_id):
    """Get the release year for a track from Spotify"""
    try:
        track_info = sp.track(track_id)
        album_id = track_info['album']['id']
        album_info = sp.album(album_id)
        release_date = album_info.get('release_date', '')
        precision = album_info.get('release_date_precision', '')
        if precision == 'day' or precision == 'month':
            return release_date[:4]
        elif precision == 'year':
            return release_date
        else:
            return None
    except Exception as e:
        print(f"Error getting track year: {str(e)}")
        return None

def get_artist_top_tracks(sp, artist_id):
    """Get top tracks from an artist"""
    try:
        results = sp.artist_top_tracks(artist_id)
        artist_info = sp.artist(artist_id)
        artist_genres = artist_info['genres']
        tracks = []
        for track in results['tracks']:
            popularity = track['popularity']
            if popularity >= 90:
                popularity_category = "Very High"
            elif popularity >= 70:
                popularity_category = "High"
            elif popularity >= 50:
                popularity_category = "Medium"
            elif popularity >= 30:
                popularity_category = "Low"
            else:
                popularity_category = "Very Low"
            
            year = track['album']['release_date'][:4] if track['album']['release_date'] else None
            if not year or not year.isdigit() or int(year) < 1900:
                year = get_track_year(sp, track['id'])
            if not year or not year.isdigit() or int(year) < 1900:
                year = 'Unknown'
                decade = 'Unknown'
            else:
                decade = f"{year[:3]}0s"
            
            tracks.append({
                'Song': track['name'],
                'Artist': track['artists'][0]['name'],
                'Year': year,
                'Decade': decade,
                'Genres': ', '.join(artist_genres) if artist_genres else 'Unknown',
                'Popularity': popularity,
                'Popularity_Category': popularity_category,
                'Source': 'Artist Top Tracks'
            })
        return tracks
    except Exception as e:
        print(f"Error getting top tracks for artist {artist_id}: {str(e)}")
        return []

def get_related_artists_tracks(sp, artist_id, max_related=3):
    """Get top tracks from related artists"""
    tracks = []
    try:
        related = sp.artist_related_artists(artist_id)
        for artist in related['artists'][:max_related]:
            artist_tracks = get_artist_top_tracks(sp, artist['id'])
            tracks.extend(artist_tracks)
    except Exception as e:
        print(f"Error getting related artists for {artist_id}: {str(e)}")
    return tracks

def get_top_artists(sp, genres=None):
    """Get top artists by genre"""
    if genres is None:
        genres = [
            'pop', 'rock', 'hip hop', 'rap', 'r&b', 'country', 'electronic',
            'metal', 'jazz', 'blues', 'folk', 'indie', 'soul', 'punk',
            'classical', 'reggae', 'disco', 'funk', 'alternative'
        ]
    
    artists = []
    for genre in genres:
        results = sp.search(q=f'genre:"{genre}"', type='artist', limit=50)
        artists.extend(results['artists']['items'])
    
    unique_artists = {artist['id']: artist for artist in artists}.values()
    return sorted(unique_artists, key=lambda x: x['popularity'], reverse=True)

def clean_text(text):
    """Clean text by removing special characters and converting to lowercase"""
    return ''.join(e for e in text if e.isalnum() or e.isspace()).lower()

def are_similar_strings(str1, str2, threshold=0.85):
    """Check if two strings are similar using character-level comparison"""
    str1 = clean_text(str1.lower())
    str2 = clean_text(str2.lower())
    
    if not str1 or not str2:
        return False
    
    s1 = set(str1.split())
    s2 = set(str2.split())
    
    intersection = len(s1 & s2)
    union = len(s1 | s2)
    return intersection / union >= threshold if union > 0 else False

def deduplicate_songs(df):
    """Remove duplicate songs based on similar names and artists"""
    print("\nDeduplicating songs...")
    rows_to_keep = []
    seen_songs = set()
    duplicates = []
    
    for idx, row in tqdm(df.iterrows(), total=len(df)):
        song = row['Song']
        artist = row['Artist']
        key = f"{song}|{artist}"
        
        is_duplicate = False
        for seen_key in seen_songs:
            seen_song, seen_artist = seen_key.split('|')
            if are_similar_strings(song, seen_song) and are_similar_strings(artist, seen_artist):
                is_duplicate = True
                duplicates.append({
                    'Original': f"{seen_song} by {seen_artist}",
                    'Duplicate': f"{song} by {artist}"
                })
                break
        
        if not is_duplicate:
            seen_songs.add(key)
            rows_to_keep.append(idx)
    
    deduped_df = df.loc[rows_to_keep].copy()
    print(f"\nRemoved {len(df) - len(deduped_df)} duplicate songs")
    
    if duplicates:
        print("\nExample duplicates removed:")
        for i, dup in enumerate(duplicates[:5], 1):
            print(f"{i}. {dup['Duplicate']} (duplicate of {dup['Original']})")
        if len(duplicates) > 5:
            print(f"... and {len(duplicates) - 5} more")
    
    return deduped_df

def get_spotify_track_info(sp, song, artist):
    """Get both genre and popularity information in a single lookup"""
    try:
        query = f"track:{song} artist:{artist}"
        results = sp.search(q=query, type='track', limit=5)
        
        if not results['tracks']['items']:
            return {
                'genres': 'Unknown',
                'popularity': 50,
                'popularity_category': 'Medium'
            }
        
        best_match = None
        highest_similarity = -1
        
        for track in results['tracks']['items']:
            track_name = track['name']
            track_artist = track['artists'][0]['name']
            
            name_similarity = are_similar_strings(song, track_name)
            artist_similarity = are_similar_strings(artist, track_artist)
            
            if name_similarity and artist_similarity:
                combined_similarity = (name_similarity + artist_similarity) / 2
                if combined_similarity > highest_similarity:
                    highest_similarity = combined_similarity
                    best_match = track
        
        if not best_match:
            return {
                'genres': 'Unknown',
                'popularity': 50,
                'popularity_category': 'Medium'
            }
        
        artist_id = best_match['artists'][0]['id']
        artist_info = sp.artist(artist_id)
        genres = artist_info['genres']
        popularity = best_match['popularity']
        
        if popularity >= 90:
            popularity_category = "Very High"
        elif popularity >= 70:
            popularity_category = "High"
        elif popularity >= 50:
            popularity_category = "Medium"
        elif popularity >= 30:
            popularity_category = "Low"
        else:
            popularity_category = "Very Low"
        
        return {
            'genres': ', '.join(genres) if genres else 'Unknown',
            'popularity': popularity,
            'popularity_category': popularity_category
        }
    
    except Exception as e:
        print(f"Error getting track info for {song} by {artist}: {str(e)}")
        return {
            'genres': 'Unknown',
            'popularity': 50,
            'popularity_category': 'Medium'
        }

def update_song_database():
    """Update the song database with Spotify data"""
    try:
        print("Loading existing Billboard data...")
        existing_df = pd.read_csv('billboard_lyrics_1964-2015.csv', encoding='latin1')
        existing_df['Year'] = existing_df['Year'].astype(str)
        
        print("Initializing Spotify client...")
        sp = init_spotify()
        
        print("Getting top artists...")
        top_artists = get_top_artists(sp)
        
        all_tracks = []
        print("\nGetting tracks from top artists...")
        for artist in tqdm(top_artists[:50]):
            tracks = get_artist_top_tracks(sp, artist['id'])
            all_tracks.extend(tracks)
            
            related_tracks = get_related_artists_tracks(sp, artist['id'])
            all_tracks.extend(related_tracks)
        
        if all_tracks:
            new_df = pd.DataFrame(all_tracks)
            new_df = new_df.drop_duplicates(subset=['Song', 'Artist'])
            
            if not existing_df.empty:
                print("\nUpdating existing songs with Spotify data...")
                for idx, row in tqdm(existing_df.iterrows(), total=len(existing_df)):
                    song = row['Song']
                    artist = row['Artist']
                    
                    spotify_info = get_spotify_track_info(sp, song, artist)
                    
                    existing_df.at[idx, 'Genres'] = spotify_info['genres']
                    existing_df.at[idx, 'Popularity'] = spotify_info['popularity']
                    existing_df.at[idx, 'Popularity_Category'] = spotify_info['popularity_category']
                
                print("\nCombining existing and new data...")
                combined_df = pd.concat([existing_df, new_df], ignore_index=True)
            else:
                combined_df = new_df
            
            deduped_df = deduplicate_songs(combined_df)
            
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            output_file = f'updated_spotify_data_{timestamp}.csv'
            deduped_df.to_csv(output_file, index=False)
            print(f"\nSaved updated dataset to {output_file}")
            
            print("\nDataset statistics:")
            print(f"Total songs: {len(deduped_df)}")
            print("\nSongs by decade:")
            decade_counts = deduped_df['Decade'].value_counts()
            for decade, count in decade_counts.items():
                print(f"{decade}: {count}")
            
            print("\nSongs by popularity category:")
            popularity_counts = deduped_df['Popularity_Category'].value_counts()
            for category, count in popularity_counts.items():
                print(f"{category}: {count}")
            
            return deduped_df
        else:
            print("No new tracks found")
            return existing_df
    
    except Exception as e:
        print(f"Error updating database: {str(e)}")
        return None

if __name__ == '__main__':
    update_song_database()
