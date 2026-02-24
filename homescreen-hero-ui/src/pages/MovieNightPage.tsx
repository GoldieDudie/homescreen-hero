import { useState, useEffect } from "react";
import { useNavigate, useOutletContext } from "react-router-dom";
import { LazyMotion, domAnimation, AnimatePresence } from "motion/react";
import { useAuth } from "../utils/auth";
import type { LayoutContext } from "../layouts/UserLayout";
import {
    Home,
    RotateCcw,
    Shuffle,
    ArrowLeft,
    ArrowRight,
    ChevronRight,
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
import VibeGrid from "../components/movie-night/VibeGrid";
import HostRoomFlow from "../components/movie-night/HostRoomFlow";
import CinematicLoader from "../components/movie-night/CinematicLoader";
import MovieRevealCard from "../components/movie-night/MovieRevealCard";
import type { MovieResult } from "../components/movie-night/types";

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

type Phase = "mode_select" | "setup" | "selecting" | "filtering" | "handoff" | "loading" | "revealing" | "remote";

export default function MovieNightPage() {
    const navigate = useNavigate();
    const { username, thumb } = useAuth();
    const { setHideNav } = useOutletContext<LayoutContext>();

    // Flow state
    const [phase, setPhase] = useState<Phase>("mode_select");
    const [slideDir, setSlideDir] = useState<"forward" | "back">("forward");
    const slideClass = slideDir === "forward" ? "animate-slide-right" : "animate-slide-left";

    const goTo = (next: Phase, dir: "forward" | "back" = "forward") => {
        setSlideDir(dir);
        setPhase(next);
    };

    // Hide bottom nav for the entire movie night flow
    useEffect(() => {
        setHideNav(true);
        return () => setHideNav(false);
    }, [setHideNav]);
    const [mode, setMode] = useState<"solo" | "group" | "remote" | null>(null);
    const [currentPlayer, setCurrentPlayer] = useState(1);
    const [playerCount, setPlayerCount] = useState(2);

    // All players' vibe picks (index 0 = player 1, etc.)
    const [allVibes, setAllVibes] = useState<string[][]>([[]]);

    // Host-only filters
    const [durationFilter, setDurationFilter] = useState<string | null>(null);
    const [rewatchMode, setRewatchMode] = useState<string>("new");

    // Results
    const [movies, setMovies] = useState<MovieResult[]>([]);
    const [currentIndex, setCurrentIndex] = useState(0);
    const [error, setError] = useState<string | null>(null);
    const [filtersApplied, setFiltersApplied] = useState<Record<string, string> | null>(null);

    const currentVibes = allVibes[currentPlayer - 1] ?? [];

    const toggleVibe = (key: string) => {
        setAllVibes((prev) => {
            const updated = [...prev];
            const playerVibes = updated[currentPlayer - 1] ?? [];
            updated[currentPlayer - 1] = playerVibes.includes(key)
                ? playerVibes.filter((v) => v !== key)
                : [...playerVibes, key];
            return updated;
        });
    };

    const handleFilterNext = () => goTo("selecting");
    const goBackToFilters = () => goTo("filtering", "back");

    const handleVibeNext = () => {
        if (mode === "group" && currentPlayer < playerCount) {
            goTo("handoff");
        } else {
            findMovie();
        }
    };

    const findMovie = async () => {
        goTo("loading");
        setError(null);
        try {
            let res: Response;

            if (mode === "group") {
                res = await fetchWithAuth("/api/movie-night/pick-group", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        players: allVibes.map((vibes, i) => ({
                            vibes,
                            duration: i === 0 ? durationFilter : null,
                            rewatch_mode: i === 0 ? rewatchMode : "any",
                        })),
                    }),
                });
            } else {
                res = await fetchWithAuth("/api/movie-night/pick", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        vibes: allVibes[0] ?? [],
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
                goTo("selecting", "back");
                return;
            }
            setMovies(data.movies);
            setCurrentIndex(0);
            goTo("revealing");
        } catch {
            setError("Something went wrong. Please try again.");
            goTo("selecting", "back");
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
        setPlayerCount(2);
        setAllVibes([[]]);
        setDurationFilter(null);
        setRewatchMode("new");
        setMovies([]);
        setCurrentIndex(0);
        goTo("mode_select", "back");
        setError(null);
        setFiltersApplied(null);
    };

    const movie = movies[currentIndex];
    const isLastMovie = currentIndex >= movies.length - 1;

    // Vibes from all players that this movie actually scores well on
    const allSelectedVibes = mode === "group"
        ? [...new Set(allVibes.flat())]
        : allVibes[0] ?? [];
    const matchedVibes = movie
        ? allSelectedVibes.filter((v) => movie.vibe_scores[v] >= 0.2)
        : [];

    return (
        <LazyMotion features={domAnimation}>
        <div className="max-w-lg mx-auto overflow-x-hidden px-1">
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
                    <div className="text-center mb-6">
                        <h2 className="text-xl font-bold tracking-tight">How are you watching tonight?</h2>
                        <p className="text-user-muted text-sm mt-1">Pick a mode to find the perfect film.</p>
                    </div>
                    <div className="grid grid-cols-1 gap-4">
                        {([
                            { key: "solo" as const, icon: User, label: "Solo", desc: "Just me, myself, and the screen", phase: "filtering" as Phase },
                            { key: "group" as const, icon: Users, label: "Group", desc: "Pass-the-phone with friends", phase: "setup" as Phase },
                            { key: "remote" as const, icon: Wifi, label: "Remote", desc: "For those long distance movie nights", phase: "remote" as Phase },
                        ]).map(({ key, icon: Icon, label, desc, phase: nextPhase }) => (
                            <button
                                key={key}
                                onClick={() => { setMode(key); goTo(nextPhase); }}
                                className="relative rounded-2xl border border-user-card-border bg-user-card hover:border-user-accent/30 px-5 py-6 text-center transition-all duration-200 active:scale-[0.98]"
                            >
                                <ChevronRight size={16} className="absolute top-4 right-4 text-user-muted/40" />
                                <div className="w-12 h-12 rounded-full bg-user-accent/15 flex items-center justify-center mx-auto mb-3">
                                    <Icon size={24} className="text-user-accent" />
                                </div>
                                <p className="text-lg font-bold">{label}</p>
                                <p className="text-xs text-user-muted mt-1">{desc}</p>
                            </button>
                        ))}
                    </div>
                </div>
            )}

            {/* SETUP PHASE — player count for group mode */}
            {phase === "setup" && (
                <div className={`flex flex-col items-center justify-center py-12 ${slideClass}`}>
                    <h2 className="text-lg font-bold tracking-tight mb-1">How many players?</h2>
                    <p className="text-xs text-user-muted mb-6">Everyone takes a turn picking vibes</p>

                    <div className="flex gap-2 w-full mb-8">
                        {[2, 3, 4, 5, 6].map((n) => (
                            <button
                                key={n}
                                onClick={() => setPlayerCount(n)}
                                className={`
                                    flex-1 py-3 rounded-xl border text-sm font-semibold transition-all duration-200
                                    ${playerCount === n
                                        ? "border-user-accent bg-user-accent/10 text-white"
                                        : "border-user-card-border bg-user-card text-user-muted hover:border-user-accent/30"
                                    }
                                `}
                            >
                                {n}
                            </button>
                        ))}
                    </div>

                    <div className="flex gap-3 w-full">
                        <button
                            onClick={() => { setMode(null); goTo("mode_select", "back"); }}
                            className="flex-1 py-3 rounded-2xl border border-user-card-border bg-user-card text-sm font-semibold text-user-muted hover:text-white hover:border-user-accent/30 transition-all duration-200 active:scale-[0.98] flex items-center justify-center gap-2"
                        >
                            <ArrowLeft size={16} />
                            Back
                        </button>
                        <button
                            onClick={() => {
                                setAllVibes(Array.from({ length: playerCount }, () => []));
                                goTo("filtering");
                            }}
                            className="flex-1 py-3 rounded-2xl bg-user-accent text-black font-semibold text-sm hover:bg-user-accent-dim active:scale-[0.98] transition-all duration-200 flex items-center justify-center gap-2"
                        >
                            Next
                            <ArrowRight size={16} />
                        </button>
                    </div>
                </div>
            )}

            {/* SELECTING PHASE */}
            {phase === "selecting" && (
                <div className={slideClass}>
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

                    {/* Navigation buttons */}
                    <div className="flex gap-3 mt-6">
                        {/* Back button — solo and host go back to filters, guests have no back */}
                        {!(mode === "group" && currentPlayer > 1) && (
                            <button
                                onClick={goBackToFilters}
                                className="flex-1 py-3.5 rounded-2xl border border-user-card-border bg-user-card text-sm font-semibold text-user-muted hover:text-white hover:border-user-accent/30 transition-all duration-200 active:scale-[0.98] flex items-center justify-center gap-2"
                            >
                                <ArrowLeft size={16} />
                                Back
                            </button>
                        )}
                        <button
                            onClick={handleVibeNext}
                            disabled={currentVibes.length < 1}
                            className={`
                                flex-1 py-3.5 rounded-2xl font-semibold text-sm
                                transition-all duration-200 flex items-center justify-center gap-2
                                ${
                                    currentVibes.length >= 1
                                        ? "bg-user-accent text-black hover:bg-user-accent-dim active:scale-[0.98]"
                                        : "bg-user-card text-user-muted border border-user-card-border cursor-not-allowed"
                                }
                            `}
                        >
                            {currentVibes.length < 1 ? (
                                "Pick at least 1 vibe"
                            ) : mode === "group" && currentPlayer < playerCount ? (
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

            {/* FILTERING PHASE */}
            {phase === "filtering" && (
                <div className={slideClass}>
                    <p className="text-user-muted text-sm mb-5">
                        Set the ground rules
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
                            const isSelected = durationFilter === key;
                            return (
                                <button
                                    key={key ?? "any"}
                                    onClick={() => setDurationFilter(key)}
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
                            const isSelected = rewatchMode === key;
                            return (
                                <button
                                    key={key}
                                    onClick={() => setRewatchMode(key)}
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
                            onClick={() => {
                                if (mode === "group") {
                                    goTo("setup", "back");
                                } else {
                                    setMode(null);
                                    goTo("mode_select", "back");
                                }
                            }}
                            className="flex-1 py-3 rounded-2xl border border-user-card-border bg-user-card text-sm font-semibold text-user-muted hover:text-white hover:border-user-accent/30 transition-all duration-200 active:scale-[0.98] flex items-center justify-center gap-2"
                        >
                            <ArrowLeft size={16} />
                            Back
                        </button>
                        <button
                            onClick={handleFilterNext}
                            className="flex-1 py-3 rounded-2xl bg-user-accent text-black font-semibold text-sm hover:bg-user-accent-dim active:scale-[0.98] transition-all duration-200 flex items-center justify-center gap-2"
                        >
                            Next
                            <ArrowRight size={16} />
                        </button>
                    </div>
                </div>
            )}

            {/* HANDOFF PHASE */}
            {phase === "handoff" && (
                <div className={`flex flex-col items-center justify-center py-16 ${slideClass}`}>
                    <div className="w-16 h-16 rounded-full bg-user-accent/10 border border-user-accent/30 flex items-center justify-center mb-5">
                        <Users size={32} className="text-user-accent" />
                    </div>
                    <h2 className="text-xl font-bold tracking-tight mb-2">Pass the Phone</h2>
                    <p className="text-user-muted text-sm text-center mb-1">
                        Hand your phone to the next person
                    </p>
                    <p className="text-user-accent text-sm font-semibold mb-8">
                        Player {currentPlayer + 1} of {playerCount}
                    </p>
                    <button
                        onClick={() => { setCurrentPlayer((p) => p + 1); goTo("selecting"); }}
                        className="px-8 py-3 rounded-2xl bg-user-accent text-black font-semibold text-sm hover:bg-user-accent-dim active:scale-[0.98] transition-all duration-200"
                    >
                        I'm Ready
                    </button>
                </div>
            )}

            {/* LOADING + REVEALING PHASES (animated transitions) */}
            <AnimatePresence mode="wait">
                {phase === "loading" && (
                    <CinematicLoader key="loader" />
                )}
                {phase === "revealing" && movie && (
                    <MovieRevealCard
                        key={`reveal-${currentIndex}`}
                        movie={movie}
                        matchedVibes={matchedVibes}
                        pickNumber={currentIndex + 1}
                        totalPicks={movies.length}
                        isLastMovie={isLastMovie}
                        isFirstReveal={currentIndex === 0}
                        filtersApplied={filtersApplied}
                        onTryAgain={tryAgain}
                        onStartOver={startOver}
                    />
                )}
            </AnimatePresence>

            {/* REMOTE PHASE — delegates to HostRoomFlow */}
            {phase === "remote" && (
                <HostRoomFlow onBack={startOver} />
            )}
        </div>
        </LazyMotion>
    );
}
