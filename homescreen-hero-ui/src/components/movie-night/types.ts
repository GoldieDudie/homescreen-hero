export interface MovieResult {
    plex_rating_key: number;
    title: string;
    year: number | null;
    poster_url: string | null;
    overview: string | null;
    genres: string[] | null;
    duration_minutes: number | null;
    match_score: number;
    vibe_scores: Record<string, number>;
}
