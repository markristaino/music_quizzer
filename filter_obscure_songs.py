import pandas as pd
import os
from datetime import datetime

def filter_spotify_data(input_file, output_file, min_popularity=50):
    """
    Filter out obscure songs from Spotify data based on popularity score.
    
    Args:
        input_file: Path to the input CSV file
        output_file: Path to save the filtered CSV file
        min_popularity: Minimum popularity score to keep (0-100)
    """
    print(f"Loading Spotify data from {input_file}...")
    df = pd.read_csv(input_file)
    
    # Print original stats
    total_songs = len(df)
    print(f"Original dataset: {total_songs} songs")
    
    # Convert popularity to numeric if it's not already
    df['Popularity'] = pd.to_numeric(df['Popularity'], errors='coerce')
    
    # Count songs with missing popularity
    missing_popularity = df['Popularity'].isna().sum()
    print(f"Songs with missing popularity: {missing_popularity} ({missing_popularity/total_songs*100:.1f}%)")
    
    # Filter by popularity
    popular_df = df[df['Popularity'] >= min_popularity]
    
    # Print stats
    kept_songs = len(popular_df)
    removed_songs = total_songs - kept_songs
    print(f"Keeping {kept_songs} songs ({kept_songs/total_songs*100:.1f}%)")
    print(f"Removing {removed_songs} songs ({removed_songs/total_songs*100:.1f}%)")
    
    # Save filtered data
    popular_df.to_csv(output_file, index=False)
    print(f"Filtered data saved to {output_file}")
    
    return popular_df

def filter_billboard_data(input_file, output_file, max_rank=None, reference_artists=None):
    """
    Filter out obscure songs from Billboard data.
    
    Args:
        input_file: Path to the input CSV file
        output_file: Path to save the filtered CSV file
        max_rank: Maximum rank to keep (lower rank = more popular)
        reference_artists: Set of artist names to keep (from Spotify data)
    """
    print(f"\nLoading Billboard data from {input_file}...")
    df = pd.read_csv(input_file, encoding='latin1')
    
    # Print original stats
    total_songs = len(df)
    print(f"Original dataset: {total_songs} songs")
    
    # Create a copy for filtering
    filtered_df = df.copy()
    
    # Filter by rank if specified
    if max_rank is not None:
        filtered_df = filtered_df[filtered_df['Rank'] <= max_rank]
        print(f"After rank filter: {len(filtered_df)} songs")
    
    # Filter by reference artists if provided
    if reference_artists is not None:
        # Normalize artist names to lowercase for comparison
        filtered_df['Artist_Lower'] = filtered_df['Artist'].str.lower()
        reference_artists_lower = {artist.lower() for artist in reference_artists}
        
        # Keep songs by artists in the reference set
        artist_mask = filtered_df['Artist_Lower'].isin(reference_artists_lower)
        filtered_df = filtered_df[artist_mask]
        filtered_df = filtered_df.drop(columns=['Artist_Lower'])  # Remove temporary column
        
        print(f"After artist filter: {len(filtered_df)} songs")
    
    # Print stats
    kept_songs = len(filtered_df)
    removed_songs = total_songs - kept_songs
    print(f"Keeping {kept_songs} songs ({kept_songs/total_songs*100:.1f}%)")
    print(f"Removing {removed_songs} songs ({removed_songs/total_songs*100:.1f}%)")
    
    # Save filtered data
    filtered_df.to_csv(output_file, index=False)
    print(f"Filtered data saved to {output_file}")
    
    return filtered_df

def main():
    # Create timestamp for output files
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # Define file paths
    spotify_input = 'updated_spotify_data_new.csv'
    spotify_output = f'filtered_spotify_data_{timestamp}.csv'
    billboard_input = 'billboard_lyrics_1964-2015.csv'
    billboard_output = f'filtered_billboard_data_{timestamp}.csv'
    
    # Filter Spotify data
    print("=" * 50)
    print("FILTERING SPOTIFY DATA")
    print("=" * 50)
    min_popularity = int(input("Enter minimum popularity score (0-100, recommended 50): ") or "50")
    spotify_df = filter_spotify_data(spotify_input, spotify_output, min_popularity)
    
    # Get list of popular artists from Spotify data
    popular_artists = set(spotify_df['Artist'].unique())
    print(f"Found {len(popular_artists)} unique artists in filtered Spotify data")
    
    # Filter Billboard data
    print("\n" + "=" * 50)
    print("FILTERING BILLBOARD DATA")
    print("=" * 50)
    use_rank = input("Filter Billboard by rank? (y/n): ").lower() == 'y'
    max_rank = None
    if use_rank:
        max_rank = int(input("Enter maximum rank to keep (e.g., 100): "))
    
    use_artists = input("Filter Billboard by artists in Spotify data? (y/n): ").lower() == 'y'
    reference_artists = popular_artists if use_artists else None
    
    billboard_df = filter_billboard_data(billboard_input, billboard_output, max_rank, reference_artists)
    
    print("\n" + "=" * 50)
    print("FILTERING COMPLETE")
    print("=" * 50)
    print(f"Spotify data: {len(spotify_df)} songs kept")
    print(f"Billboard data: {len(billboard_df)} songs kept")
    print("\nTo use these filtered datasets in the music quizzer app:")
    print(f"1. Rename {spotify_output} to updated_spotify_data_new.csv")
    print(f"2. Rename {billboard_output} to billboard_lyrics_1964-2015.csv")
    print("   OR update the file paths in app.py")

if __name__ == "__main__":
    main()
