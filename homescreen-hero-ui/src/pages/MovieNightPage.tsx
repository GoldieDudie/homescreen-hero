import { useState, useEffect } from "react";
import { useNavigate, useOutletContext } from "react-router-dom";
import { useAuth } from "../utils/auth";
import type { LayoutContext } from "../layouts/UserLayout";
import {
    Home,
    RotateCcw,
    Shuffle,
    Loader2,
    ArrowLeft,
    ArrowRight,
    Timer,
    Clock,
    Hourglass,
    Sparkles,
    User,
    Users,
    Wifi,
    type LucideIcon,
} from "lucide-react";
import { fetchWithAuth } from "../utils/api";
import VibeGrid, { VIBES } from "../components/movie-night/VibeGrid";
import HostRoomFlow from "../components/movie-night/HostRoomFlow";

const DURATION_OPTIONS: { key: string | null; label: string; desc: string; icon: LucideIcon | null }[] = [
    { key: null, label: "Any Length", desc: "No preference", icon: null },
    { key: "quick", label: "Quick Watch", desc: "Under 100 min", icon: Timer },
    { key: "standard", label: "Standard", desc: "100–150 min", icon: Clock },
    { key: "long", label: "I'm Committed", desc: "Over 150 min", icon: Hourglass },
];

const REWATCH_OPTIONS: { key: string; label: string; desc: string; icon: LucideIcon }[] = [
    { key: "new", label: "Something New", desc: "Haven't seen it yet", icon: Sparkles },
    { key: "rewatch", label: "Rewatch a Fave", desc: "Something I've loved", icon: RotateCcw },
    { key: "any", label: "Don't Care", desc: "Surprise me", icon: Shuffle },
];

interface MovieResult {
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

type Phase = "mode_select" | "selecting" | "filtering" | "handoff" | "loading" | "revealing" | "remote";

export default function MovieNightPage() {
    const navigate = useNavigate();
    const { username, thumb } = useAuth();
    const { setHideNav } = useOutletContext<LayoutContext>();

    // Flow state
    const [phase, setPhase] = useState<Phase>("mode_select");

    // Show bottom nav on mode_select, hide during the flow
    useEffect(() => {
        setHideNav(phase !== "mode_select");
        return () => setHideNav(false);
    }, [phase, setHideNav]);
    const [mode, setMode] = useState<"solo" | "group" | "remote" | null>(null);
    const [currentPlayer, setCurrentPlayer] = useState(1);
    const playerCount = 2;

    // Player 1 picks
    const [selectedVibes, setSelectedVibes] = useState<string[]>([]);
    const [durationFilter, setDurationFilter] = useState<string | null>(null);
    const [rewatchMode, setRewatchMode] = useState<string>("new");

    // Player 2 picks
    const [selectedVibesP2, setSelectedVibesP2] = useState<string[]>([]);
    const [durationFilterP2, setDurationFilterP2] = useState<string | null>(null);
    const [rewatchModeP2, setRewatchModeP2] = useState<string>("any");

    // Results
    const [movies, setMovies] = useState<MovieResult[]>([]);
    const [currentIndex, setCurrentIndex] = useState(0);
    const [error, setError] = useState<string | null>(null);
    const [filtersApplied, setFiltersApplied] = useState<Record<string, string> | null>(null);

    // Route state to current player's picks
    const currentVibes = currentPlayer === 2 ? selectedVibesP2 : selectedVibes;
    const setCurrentVibes = currentPlayer === 2 ? setSelectedVibesP2 : setSelectedVibes;
    const currentDuration = currentPlayer === 2 ? durationFilterP2 : durationFilter;
    const setCurrentDuration = currentPlayer === 2 ? setDurationFilterP2 : setDurationFilter;
    const currentRewatch = currentPlayer === 2 ? rewatchModeP2 : rewatchMode;
    const setCurrentRewatch = currentPlayer === 2 ? setRewatchModeP2 : setRewatchMode;

    const toggleVibe = (key: string) => {
        setCurrentVibes((prev) => {
            if (prev.includes(key)) return prev.filter((v) => v !== key);
            return [...prev, key];
        });
    };

    const goToFilters = () => setPhase("filtering");
    const goBackToVibes = () => setPhase("selecting");

    const handleFilterNext = () => {
        if (mode === "group" && currentPlayer === 1) {
            setPhase("handoff");
        } else {
            findMovie();
        }
    };

    const findMovie = async () => {
        setPhase("loading");
        setError(null);
        try {
            let res: Response;

            if (mode === "group") {
                res = await fetchWithAuth("/api/movie-night/pick-group", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        players: [
                            { vibes: selectedVibes, duration: durationFilter, rewatch_mode: rewatchMode },
                            { vibes: selectedVibesP2, duration: durationFilterP2, rewatch_mode: rewatchModeP2 },
                        ],
                    }),
                });
            } else {
                res = await fetchWithAuth("/api/movie-night/pick", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        vibes: selectedVibes,
                        duration: durationFilter,
                        rewatch_mode: rewatchMode,
                    }),
                });
            }

            if (!res.ok) throw new Error("Failed to fetch movies");
            const data = await res.json();
            setFiltersApplied(data.filters_applied ?? null);
            if (data.movies.length === 0) {
                setError("No movies match these vibes and filters. Try adjusting!");
                setPhase("filtering");
                return;
            }
            setMovies(data.movies);
            setCurrentIndex(0);
            setPhase("revealing");
        } catch {
            setError("Something went wrong. Please try again.");
            setPhase("filtering");
        }
    };

    const tryAgain = () => {
        if (currentIndex < movies.length - 1) {
            setCurrentIndex((i) => i + 1);
        }
    };

    const startOver = () => {
        setMode(null);
        setCurrentPlayer(1);
        setSelectedVibes([]);
        setDurationFilter(null);
        setRewatchMode("new");
        setSelectedVibesP2([]);
        setDurationFilterP2(null);
        setRewatchModeP2("any");
        setMovies([]);
        setCurrentIndex(0);
        setPhase("mode_select");
        setError(null);
        setFiltersApplied(null);
    };

    const movie = movies[currentIndex];
    const isLastMovie = currentIndex >= movies.length - 1;

    // Vibes from all players that this movie actually scores well on
    const allSelectedVibes = mode === "group"
        ? [...new Set([...selectedVibes, ...selectedVibesP2])]
        : selectedVibes;
    const matchedVibes = movie
        ? allSelectedVibes.filter((v) => movie.vibe_scores[v] >= 0.2)
        : [];

    return (
        <div className="max-w-lg mx-auto">
            {/* Header */}
            <div className="flex items-center justify-between mb-6">
                <div>
                    <h1 className="text-3xl font-bold tracking-tight">Movie Night</h1>
                    <p className="text-sm text-user-accent uppercase tracking-wider font-semibold">
                        Vibe Picker
                    </p>
                </div>
                <div className="flex items-center gap-2">
                    <button
                        onClick={() => navigate("/user")}
                        className="p-2 rounded-xl text-user-muted hover:text-white transition-colors"
                        title="Home"
                    >
                        <Home size={20} />
                    </button>
                    {thumb ? (
                        <img
                            src={thumb}
                            alt={username ?? "User"}
                            className="h-9 w-9 rounded-full object-cover ring-2 ring-user-card-border"
                        />
                    ) : (
                        <div className="h-9 w-9 rounded-full bg-user-card flex items-center justify-center ring-2 ring-user-card-border">
                            <span className="text-sm font-semibold text-user-muted">
                                {username?.charAt(0).toUpperCase() ?? "?"}
                            </span>
                        </div>
                    )}
                </div>
            </div>

            {/* MODE SELECT PHASE */}
            {phase === "mode_select" && (
                <div className="animate-fade-in">
                    <p className="text-user-muted text-sm mb-4">
                        How are you watching tonight?
                    </p>
                    <div className="grid grid-cols-1 gap-3">
                        <button
                            onClick={() => { setMode("solo"); setPhase("selecting"); }}
                            className="rounded-2xl border border-user-card-border bg-user-card hover:border-user-accent/30 p-5 text-left transition-all duration-200 active:scale-[0.98]"
                        >
                            <User size={24} className="mb-2 text-user-accent" />
                            <p className="text-lg font-semibold">Solo</p>
                            <p className="text-xs text-user-muted mt-1">Just me tonight</p>
                        </button>
                        <button
                            onClick={() => { setMode("group"); setPhase("selecting"); }}
                            className="rounded-2xl border border-user-card-border bg-user-card hover:border-user-accent/30 p-5 text-left transition-all duration-200 active:scale-[0.98]"
                        >
                            <Users size={24} className="mb-2 text-user-accent" />
                            <p className="text-lg font-semibold">Group</p>
                            <p className="text-xs text-user-muted mt-1">Pass-the-phone with friends</p>
                        </button>
                        <button
                            onClick={() => { setMode("remote"); setPhase("remote"); }}
                            className="rounded-2xl border border-user-card-border bg-user-card hover:border-user-accent/30 p-5 text-left transition-all duration-200 active:scale-[0.98]"
                        >
                            <Wifi size={24} className="mb-2 text-user-accent" />
                            <p className="text-lg font-semibold">Remote</p>
                            <p className="text-xs text-user-muted mt-1">Share a room code</p>
                        </button>
                    </div>
                </div>
            )}

            {/* SELECTING PHASE */}
            {phase === "selecting" && (
                <div>
                    {/* Player indicator for group mode */}
                    {mode === "group" && (
                        <div className="text-center mb-3">
                            <span className="inline-block px-3 py-1 rounded-full bg-user-accent/10 border border-user-accent/30 text-xs font-semibold text-user-accent">
                                Player {currentPlayer} of {playerCount}
                            </span>
                        </div>
                    )}

                    <p className="text-user-muted text-sm mb-4">
                        Pick the vibes you're in the mood for
                    </p>

                    {error && (
                        <div className="mb-4 p-3 rounded-xl bg-red-500/10 border border-red-500/20 text-red-400 text-sm">
                            {error}
                        </div>
                    )}

                    {/* Vibe grid */}
                    <VibeGrid selectedVibes={currentVibes} onToggle={toggleVibe} />

                    {/* Next button */}
                    <button
                        onClick={goToFilters}
                        disabled={currentVibes.length < 1}
                        className={`
                            w-full mt-6 py-3.5 rounded-2xl font-semibold text-sm
                            transition-all duration-200 flex items-center justify-center gap-2
                            ${
                                currentVibes.length >= 1
                                    ? "bg-user-accent text-black hover:bg-user-accent-dim active:scale-[0.98]"
                                    : "bg-user-card text-user-muted border border-user-card-border cursor-not-allowed"
                            }
                        `}
                    >
                        {currentVibes.length >= 1 ? (
                            <>
                                Next
                                <ArrowRight size={16} />
                            </>
                        ) : (
                            "Pick at least 1 vibe"
                        )}
                    </button>
                </div>
            )}

            {/* FILTERING PHASE */}
            {phase === "filtering" && (
                <div className="animate-fade-in">
                    {/* Player indicator for group mode */}
                    {mode === "group" && (
                        <div className="text-center mb-3">
                            <span className="inline-block px-3 py-1 rounded-full bg-user-accent/10 border border-user-accent/30 text-xs font-semibold text-user-accent">
                                Player {currentPlayer} of {playerCount}
                            </span>
                        </div>
                    )}

                    <p className="text-user-muted text-sm mb-5">
                        Refine your pick
                    </p>

                    {error && (
                        <div className="mb-4 p-3 rounded-xl bg-red-500/10 border border-red-500/20 text-red-400 text-sm">
                            {error}
                        </div>
                    )}

                    {/* Duration picker */}
                    <h3 className="text-xs uppercase tracking-wider text-user-muted mb-2 font-semibold">
                        How long?
                    </h3>
                    <div className="grid grid-cols-2 gap-2 mb-5">
                        {DURATION_OPTIONS.map(({ key, label, desc, icon: Icon }) => {
                            const isSelected = currentDuration === key;
                            return (
                                <button
                                    key={key ?? "any"}
                                    onClick={() => setCurrentDuration(key)}
                                    className={`
                                        rounded-xl border p-3 text-left transition-all duration-200
                                        ${
                                            isSelected
                                                ? "border-user-accent bg-user-accent/10"
                                                : "border-user-card-border bg-user-card hover:border-user-accent/30"
                                        }
                                    `}
                                >
                                    {Icon && (
                                        <Icon
                                            size={18}
                                            className={`mb-1 ${isSelected ? "text-user-accent" : "text-user-muted"}`}
                                        />
                                    )}
                                    <p className={`text-sm font-semibold ${isSelected ? "text-white" : "text-slate-300"}`}>
                                        {label}
                                    </p>
                                    <p className="text-xs text-user-muted">{desc}</p>
                                </button>
                            );
                        })}
                    </div>

                    {/* Rewatch mode */}
                    <h3 className="text-xs uppercase tracking-wider text-user-muted mb-2 font-semibold">
                        Seen it before?
                    </h3>
                    <div className="grid grid-cols-3 gap-2 mb-6">
                        {REWATCH_OPTIONS.map(({ key, label, desc, icon: Icon }) => {
                            const isSelected = currentRewatch === key;
                            return (
                                <button
                                    key={key}
                                    onClick={() => setCurrentRewatch(key)}
                                    className={`
                                        rounded-xl border p-3 text-left transition-all duration-200
                                        ${
                                            isSelected
                                                ? "border-user-accent bg-user-accent/10"
                                                : "border-user-card-border bg-user-card hover:border-user-accent/30"
                                        }
                                    `}
                                >
                                    <Icon
                                        size={18}
                                        className={`mb-1 ${isSelected ? "text-user-accent" : "text-user-muted"}`}
                                    />
                                    <p className={`text-xs font-semibold mt-1 ${isSelected ? "text-white" : "text-slate-300"}`}>
                                        {label}
                                    </p>
                                    <p className="text-[10px] text-user-muted leading-tight mt-0.5">{desc}</p>
                                </button>
                            );
                        })}
                    </div>

                    {/* Navigation buttons */}
                    <div className="flex gap-3">
                        <button
                            onClick={goBackToVibes}
                            className="flex-1 py-3 rounded-2xl border border-user-card-border bg-user-card text-sm font-semibold text-user-muted hover:text-white hover:border-user-accent/30 transition-all duration-200 active:scale-[0.98] flex items-center justify-center gap-2"
                        >
                            <ArrowLeft size={16} />
                            Back
                        </button>
                        <button
                            onClick={handleFilterNext}
                            className="flex-1 py-3 rounded-2xl bg-user-accent text-black font-semibold text-sm hover:bg-user-accent-dim active:scale-[0.98] transition-all duration-200 flex items-center justify-center gap-2"
                        >
                            {mode === "group" && currentPlayer === 1 ? (
                                <>
                                    Next
                                    <ArrowRight size={16} />
                                </>
                            ) : mode === "group" ? (
                                "Find Our Movie"
                            ) : (
                                "Find My Movie"
                            )}
                        </button>
                    </div>
                </div>
            )}

            {/* HANDOFF PHASE */}
            {phase === "handoff" && (
                <div className="flex flex-col items-center justify-center py-16 animate-fade-in">
                    <div className="w-16 h-16 rounded-full bg-user-accent/10 border border-user-accent/30 flex items-center justify-center mb-5">
                        <Users size={32} className="text-user-accent" />
                    </div>
                    <h2 className="text-xl font-bold tracking-tight mb-2">Pass the Phone</h2>
                    <p className="text-user-muted text-sm text-center mb-8">
                        Hand your phone to the next person —<br />
                        it's their turn to pick vibes
                    </p>
                    <button
                        onClick={() => { setCurrentPlayer(2); setPhase("selecting"); }}
                        className="px-8 py-3 rounded-2xl bg-user-accent text-black font-semibold text-sm hover:bg-user-accent-dim active:scale-[0.98] transition-all duration-200"
                    >
                        I'm Ready
                    </button>
                </div>
            )}

            {/* LOADING PHASE */}
            {phase === "loading" && (
                <div className="flex flex-col items-center justify-center py-20 animate-fade-in">
                    <Loader2 size={32} className="animate-spin text-user-accent mb-4" />
                    <p className="text-user-muted text-sm">
                        {mode === "group" ? "Finding your movie…" : "Finding your movie…"}
                    </p>
                </div>
            )}

            {/* REVEALING PHASE */}
            {phase === "revealing" && movie && (
                <div key={currentIndex} className="animate-fade-in">
                    {/* Plex fallback notice */}
                    {filtersApplied?.rewatch_fallback && (
                        <p className="text-center text-xs text-amber-400/70 mb-3">
                            Watch history unavailable — showing all movies
                        </p>
                    )}

                    {/* Duration fallback notice */}
                    {filtersApplied?.duration_fallback && (
                        <p className="text-center text-xs text-amber-400/70 mb-3">
                            Couldn't agree on length — showing all durations
                        </p>
                    )}

                    {/* Poster */}
                    <div className="flex justify-center mb-5">
                        {movie.poster_url ? (
                            <img
                                src={movie.poster_url}
                                alt={movie.title}
                                className="w-52 aspect-[2/3] object-cover rounded-2xl shadow-2xl shadow-black/50"
                            />
                        ) : (
                            <div className="w-52 aspect-[2/3] rounded-2xl bg-user-card border border-user-card-border flex items-center justify-center">
                                <p className="text-user-muted text-sm">No poster</p>
                            </div>
                        )}
                    </div>

                    {/* Title + Year + Duration */}
                    <div className="text-center mb-4">
                        <h2 className="text-2xl font-bold tracking-tight">
                            {movie.title}
                        </h2>
                        <p className="text-user-muted text-sm mt-1">
                            {[
                                movie.year,
                                movie.duration_minutes ? `${movie.duration_minutes} min` : null,
                            ].filter(Boolean).join(" · ")}
                        </p>
                    </div>

                    {/* Genre pills */}
                    {movie.genres && movie.genres.length > 0 && (
                        <div className="flex flex-wrap justify-center gap-2 mb-3">
                            {movie.genres.map((genre) => (
                                <span
                                    key={genre}
                                    className="px-2.5 py-1 rounded-full bg-user-card border border-user-card-border text-xs text-user-muted"
                                >
                                    {genre}
                                </span>
                            ))}
                        </div>
                    )}

                    {/* Matched vibe pills */}
                    {matchedVibes.length > 0 && (
                        <div className="flex flex-wrap justify-center gap-2 mb-4">
                            {matchedVibes.map((v) => {
                                const vibe = VIBES.find((vb) => vb.key === v);
                                if (!vibe) return null;
                                const VibeIcon = vibe.icon;
                                return (
                                    <span
                                        key={v}
                                        className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-user-accent/10 border border-user-accent/30 text-xs text-user-accent"
                                    >
                                        <VibeIcon size={12} />
                                        {vibe.label}
                                    </span>
                                );
                            })}
                        </div>
                    )}

                    {/* Overview */}
                    {movie.overview && (
                        <p className="text-sm text-user-muted leading-relaxed text-center mb-6">
                            {movie.overview.length > 200
                                ? movie.overview.slice(0, 200) + "…"
                                : movie.overview}
                        </p>
                    )}

                    {/* Pick counter */}
                    <p className="text-center text-xs text-user-muted mb-3">
                        Pick {currentIndex + 1} of {movies.length}
                    </p>

                    {/* Action buttons */}
                    <div className="flex gap-3">
                        <button
                            onClick={startOver}
                            className="flex-1 py-3 rounded-2xl border border-user-card-border bg-user-card text-sm font-semibold text-user-muted hover:text-white hover:border-user-accent/30 transition-all duration-200 active:scale-[0.98] flex items-center justify-center gap-2"
                        >
                            <RotateCcw size={16} />
                            Start Over
                        </button>
                        <button
                            onClick={tryAgain}
                            disabled={isLastMovie}
                            className={`
                                flex-1 py-3 rounded-2xl text-sm font-semibold transition-all duration-200
                                flex items-center justify-center gap-2
                                ${
                                    isLastMovie
                                        ? "bg-user-card border border-user-card-border text-user-muted cursor-not-allowed opacity-50"
                                        : "bg-user-accent text-black hover:bg-user-accent-dim active:scale-[0.98]"
                                }
                            `}
                        >
                            <Shuffle size={16} />
                            Try Again
                        </button>
                    </div>

                    {isLastMovie && (
                        <p className="text-center text-xs text-user-muted mt-3">
                            That's all for these vibes!
                        </p>
                    )}
                </div>
            )}

            {/* REMOTE PHASE — delegates to HostRoomFlow */}
            {phase === "remote" && (
                <HostRoomFlow onBack={startOver} />
            )}
        </div>
    );
}
