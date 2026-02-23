import { useState, useEffect, useRef, useCallback } from "react";

interface PlayerInfo {
    player_name: string;
    is_host: boolean;
    has_submitted_vibes: boolean;
}

interface GuestMovieInfo {
    title: string;
    year: number | null;
    poster_url: string | null;
    overview: string | null;
    genres: string[] | null;
    duration_minutes: number | null;
    match_score: number;
}

export interface RoomPollResponse {
    room_code: string;
    state: string;
    players: PlayerInfo[];
    host_name: string;
    vibes_submitted_count: number;
    current_movie: GuestMovieInfo | null;
    current_movie_index: number;
    total_movies: number;
    votes: Record<string, boolean | null> | null;
    approved_movie: GuestMovieInfo | null;
    filters_applied: Record<string, string> | null;
}

const TERMINAL_STATES = new Set(["approved", "exhausted", "expired"]);

export default function useRoomPoll(playerToken: string | null, intervalMs = 3000) {
    const [data, setData] = useState<RoomPollResponse | null>(null);
    const [error, setError] = useState<string | null>(null);
    const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

    const poll = useCallback(async () => {
        if (!playerToken) return;
        try {
            const res = await fetch(`/api/movie-night/room/poll?token=${playerToken}`);
            if (res.status === 429) return; // rate limited, skip
            if (!res.ok) {
                setError("Room not found or session expired");
                return;
            }
            const json: RoomPollResponse = await res.json();
            setData(json);
            setError(null);

            // Stop polling on terminal states
            if (TERMINAL_STATES.has(json.state) && intervalRef.current) {
                clearInterval(intervalRef.current);
                intervalRef.current = null;
            }
        } catch {
            setError("Connection error");
        }
    }, [playerToken]);

    useEffect(() => {
        if (!playerToken) return;

        // Immediate first poll
        poll();

        intervalRef.current = setInterval(poll, intervalMs);

        return () => {
            if (intervalRef.current) {
                clearInterval(intervalRef.current);
                intervalRef.current = null;
            }
        };
    }, [playerToken, intervalMs, poll]);

    return { data, error, refetch: poll };
}
