import pandas as pd
from collections import Counter

def analyze_spotify_data(file_path):
    print(f"Loading data from {file_path}...")
    df = pd.read_csv(file_path)
    
    # Analyze genres
    print("\nAnalyzing genres...")
    # Split genre strings into individual genres and count
    all_genres = []
    for genres in df['Genres'].dropna():
        all_genres.extend([g.strip() for g in genres.split(',')])
    
    genre_counts = Counter(all_genres)
    print("\nTop 20 genres:")
    for genre, count in genre_counts.most_common(20):
        print(f"{genre}: {count}")
    
    # Analyze decades
    print("\nAnalyzing decades...")
    df['Decade'] = (df['Year'].astype(int) // 10) * 10
    decade_counts = df['Decade'].value_counts().sort_index()
    
    print("\nSongs per decade:")
    for decade, count in decade_counts.items():
        print(f"{decade}s: {count}")
    
    # Additional stats
    print("\nAdditional Stats:")
    print(f"Total unique genres: {len(genre_counts)}")
    print(f"Total songs: {len(df)}")
    print(f"Songs with genres: {df['Genres'].notna().sum()}")
    print(f"Songs without genres: {df['Genres'].isna().sum()}")
    
    # Average genres per song
    genres_per_song = df['Genres'].dropna().str.count(',') + 1
    print(f"Average genres per song: {genres_per_song.mean():.2f}")

if __name__ == "__main__":
    analyze_spotify_data('updated_spotify_data_new.csv')
