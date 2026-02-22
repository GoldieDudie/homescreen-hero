import { useState } from "react";
import { useNavigate } from "react-router-dom";
import {
    ArrowLeft,
    Popcorn,
    Skull,
    Brain,
    Heart,
    HeartCrack,
    Compass,
    Laugh,
    Eclipse,
    Sun,
    Star,
    BookOpen,
    RotateCcw,
    Shuffle,
    Loader2,
} from "lucide-react";
import { fetchWithAuth } from "../utils/api";

const VIBES = [
    { key: "popcorn_night", label: "Popcorn Night", desc: "Blockbusters & comfort watches", icon: Popcorn },
    { key: "nerve_wracking", label: "Nerve Wracking", desc: "Thrillers & horror", icon: Skull },
    { key: "mind_bending", label: "Mind Bending", desc: "Sci-fi & twisty plots", icon: Brain },
    { key: "hopeless_romantic", label: "Hopeless Romantic", desc: "Love stories & romance", icon: Heart },
    { key: "gut_punch", label: "Gut Punch", desc: "Heavy drama & emotional", icon: HeartCrack },
    { key: "epic_adventure", label: "Epic Adventure", desc: "Fantasy & epic scale", icon: Compass },
    { key: "cheap_laughs", label: "Cheap Laughs", desc: "Comedy & buddy films", icon: Laugh },
    { key: "dark_twisted", label: "Dark & Twisted", desc: "Crime, noir & morally gray", icon: Eclipse },
    { key: "feel_good", label: "Feel Good", desc: "Uplifting & warm", icon: Sun },
    { key: "kid_at_heart", label: "Kid At Heart", desc: "Animation & family", icon: Star },
    { key: "true_story", label: "True Story", desc: "Biopics & documentaries", icon: BookOpen },
] as const;

interface MovieResult {
    plex_rating_key: number;
    title: string;
    year: number | null;
    poster_url: string | null;
    overview: string | null;
    genres: string[] | null;
    match_score: number;
    vibe_scores: Record<string, number>;
}

type Phase = "selecting" | "loading" | "revealing";

export default function MovieNightPage() {
    const navigate = useNavigate();
    const [phase, setPhase] = useState<Phase>("selecting");
    const [selectedVibes, setSelectedVibes] = useState<string[]>([]);
    const [movies, setMovies] = useState<MovieResult[]>([]);
    const [currentIndex, setCurrentIndex] = useState(0);
    const [error, setError] = useState<string | null>(null);

    const toggleVibe = (key: string) => {
        setSelectedVibes((prev) => {
            if (prev.includes(key)) return prev.filter((v) => v !== key);
            if (prev.length >= 3) return prev;
            return [...prev, key];
        });
    };

    const findMovie = async () => {
        setPhase("loading");
        setError(null);
        try {
            const res = await fetchWithAuth("/api/movie-night/pick", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ vibes: selectedVibes }),
            });
            if (!res.ok) throw new Error("Failed to fetch movies");
            const data = await res.json();
            if (data.movies.length === 0) {
                setError("No movies match these vibes. Try different ones!");
                setPhase("selecting");
                return;
            }
            setMovies(data.movies);
            setCurrentIndex(0);
            setPhase("revealing");
        } catch {
            setError("Something went wrong. Please try again.");
            setPhase("selecting");
        }
    };

    const tryAgain = () => {
        if (currentIndex < movies.length - 1) {
            setCurrentIndex((i) => i + 1);
        }
    };

    const startOver = () => {
        setSelectedVibes([]);
        setMovies([]);
        setCurrentIndex(0);
        setPhase("selecting");
        setError(null);
    };

    const movie = movies[currentIndex];
    const isLastMovie = currentIndex >= movies.length - 1;

    // Vibes the user picked that this movie actually scores well on
    const matchedVibes = movie
        ? selectedVibes.filter((v) => movie.vibe_scores[v] >= 0.2)
        : [];

    return (
        <div className="max-w-lg mx-auto">
            {/* Header */}
            <div className="flex items-center gap-3 mb-6">
                <button
                    onClick={() => navigate("/user")}
                    className="p-2 -ml-2 rounded-xl text-user-muted hover:text-white transition-colors"
                >
                    <ArrowLeft size={20} />
                </button>
                <div>
                    <h1 className="text-xl font-bold tracking-tight">Movie Night</h1>
                    <p className="text-xs text-user-muted uppercase tracking-wider">
                        Vibe Picker
                    </p>
                </div>
            </div>

            {/* SELECTING PHASE */}
            {(phase === "selecting" || phase === "loading") && (
                <div>
                    <p className="text-user-muted text-sm mb-4">
                        Pick 2–3 vibes you're in the mood for
                    </p>

                    {error && (
                        <div className="mb-4 p-3 rounded-xl bg-red-500/10 border border-red-500/20 text-red-400 text-sm">
                            {error}
                        </div>
                    )}

                    {/* Vibe grid */}
                    <div className="grid grid-cols-2 gap-3">
                        {VIBES.map(({ key, label, desc, icon: Icon }, index) => {
                            const isSelected = selectedVibes.includes(key);
                            const isDisabled =
                                (!isSelected && selectedVibes.length >= 3) ||
                                phase === "loading";
                            return (
                                <button
                                    key={key}
                                    onClick={() => toggleVibe(key)}
                                    disabled={isDisabled}
                                    className={`
                                        animate-fade-in group rounded-2xl border p-4 text-left
                                        transition-all duration-200
                                        ${
                                            isSelected
                                                ? "border-user-accent bg-user-accent/10 shadow-lg shadow-user-accent/10"
                                                : "border-user-card-border bg-user-card hover:border-user-accent/30"
                                        }
                                        ${isDisabled ? "opacity-40 cursor-not-allowed" : "active:scale-[0.97]"}
                                    `}
                                    style={{ animationDelay: `${index * 0.04}s` }}
                                >
                                    <Icon
                                        size={22}
                                        className={`mb-2 transition-colors ${
                                            isSelected
                                                ? "text-user-accent"
                                                : "text-user-muted group-hover:text-user-accent"
                                        }`}
                                    />
                                    <p
                                        className={`text-sm font-semibold ${
                                            isSelected ? "text-white" : "text-slate-300"
                                        }`}
                                    >
                                        {label}
                                    </p>
                                    <p className="text-xs text-user-muted mt-0.5">{desc}</p>
                                </button>
                            );
                        })}
                    </div>

                    {/* Find button */}
                    <button
                        onClick={findMovie}
                        disabled={selectedVibes.length < 2 || phase === "loading"}
                        className={`
                            w-full mt-6 py-3.5 rounded-2xl font-semibold text-sm
                            transition-all duration-200
                            ${
                                selectedVibes.length >= 2 && phase !== "loading"
                                    ? "bg-user-accent text-black hover:bg-user-accent-dim active:scale-[0.98]"
                                    : "bg-user-card text-user-muted border border-user-card-border cursor-not-allowed"
                            }
                        `}
                    >
                        {phase === "loading" ? (
                            <span className="flex items-center justify-center gap-2">
                                <Loader2 size={18} className="animate-spin" />
                                Finding your movie…
                            </span>
                        ) : selectedVibes.length >= 2 ? (
                            `Find My Movie (${selectedVibes.length}/3)`
                        ) : (
                            "Pick at least 2 vibes"
                        )}
                    </button>
                </div>
            )}

            {/* REVEALING PHASE */}
            {phase === "revealing" && movie && (
                <div key={currentIndex} className="animate-fade-in">
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

                    {/* Title + Year */}
                    <div className="text-center mb-4">
                        <h2 className="text-2xl font-bold tracking-tight">
                            {movie.title}
                        </h2>
                        {movie.year && (
                            <p className="text-user-muted text-sm mt-1">{movie.year}</p>
                        )}
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
        </div>
    );
}
