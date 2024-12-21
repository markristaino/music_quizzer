import pandas as pd
from collections import Counter, defaultdict
from app import map_to_parent_genre

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
    
    # Analyze parent genres
    print("\nAnalyzing parent genres...")
    parent_genre_counts = defaultdict(int)
    songs_with_genre = 0
    
    for genres in df['Genres'].dropna():
        has_genre = False
        for genre in str(genres).split(','):
            parent_genre = map_to_parent_genre(genre.strip())
            if parent_genre:
                parent_genre_counts[parent_genre] += 1
                has_genre = True
        if has_genre:
            songs_with_genre += 1
    
    print("\nSongs by parent genre:")
    total_genre_assignments = sum(parent_genre_counts.values())
    for genre, count in sorted(parent_genre_counts.items(), key=lambda x: x[1], reverse=True):
        print(f"{genre}: {count} ({count/len(df)*100:.1f}% of total songs, {count/total_genre_assignments*100:.1f}% of genre assignments)")
    
    songs_without_genre = len(df) - songs_with_genre
    print(f"\nSongs with no genre: {songs_without_genre} ({songs_without_genre/len(df)*100:.1f}%)")
    
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
