import { useEffect, useState } from "react";
import { m } from "motion/react";
import confetti from "canvas-confetti";
import { RotateCcw, Shuffle } from "lucide-react";
import { VIBES } from "./VibeGrid";
import type { MovieResult } from "./types";

interface MovieRevealCardProps {
    movie: MovieResult;
    matchedVibes: string[];
    pickNumber: number;
    totalPicks: number;
    isLastMovie: boolean;
    isFirstReveal: boolean;
    filtersApplied: Record<string, string> | null;
    onTryAgain: () => void;
    onStartOver: () => void;
}

// Count-up hook for the match score
function useCountUp(target: number, duration = 800, delay = 500) {
    const [value, setValue] = useState(0);
    useEffect(() => {
        const start = performance.now() + delay;
        let raf: number;
        const step = (now: number) => {
            const elapsed = Math.max(0, now - start);
            const progress = Math.min(elapsed / duration, 1);
            const eased = 1 - Math.pow(1 - progress, 3); // ease-out cubic
            setValue(Math.round(eased * target));
            if (progress < 1) raf = requestAnimationFrame(step);
        };
        raf = requestAnimationFrame(step);
        return () => cancelAnimationFrame(raf);
    }, [target, duration, delay]);
    return value;
}

// Animation variants
const container = {
    hidden: {},
    visible: {
        transition: { staggerChildren: 0.12, delayChildren: 0.1 },
    },
    exit: {
        opacity: 0,
        scale: 0.95,
        transition: { duration: 0.25 },
    },
};

const posterVariant = {
    hidden: { opacity: 0, scale: 0.8 },
    visible: {
        opacity: 1,
        scale: 1,
        transition: { type: "spring" as const, stiffness: 300, damping: 25 },
    },
};

const fadeUp = {
    hidden: { opacity: 0, y: 20 },
    visible: { opacity: 1, y: 0, transition: { duration: 0.4, ease: "easeOut" as const } },
};

export default function MovieRevealCard({
    movie,
    matchedVibes,
    pickNumber,
    totalPicks,
    isLastMovie,
    isFirstReveal,
    filtersApplied,
    onTryAgain,
    onStartOver,
}: MovieRevealCardProps) {
    const scorePercent = Math.round(movie.match_score * 100);
    const displayScore = useCountUp(scorePercent, 800, isFirstReveal ? 500 : 0);

    // Fire confetti only on first reveal
    useEffect(() => {
        if (!isFirstReveal) return;
        const timer = setTimeout(() => {
            confetti({
                particleCount: 80,
                spread: 70,
                origin: { y: 0.4 },
                colors: ["#e5a00d", "#f5c842", "#ffffff", "#ffd700"],
            });
        }, 400);
        return () => clearTimeout(timer);
    }, [isFirstReveal]);

    // First reveal: full staggered entrance. Try Again: simple quick fade.
    const quickFade = {
        hidden: { opacity: 0 },
        visible: { opacity: 1, transition: { duration: 0.25 } },
    };
    const containerAnim = isFirstReveal ? container : quickFade;
    const itemAnim = isFirstReveal ? fadeUp : undefined;
    const posterAnim = isFirstReveal ? posterVariant : undefined;

    return (
        <m.div
            variants={containerAnim}
            initial="hidden"
            animate="visible"
            exit="exit"
        >
            {/* Fallback notices */}
            {filtersApplied?.rewatch_fallback && (
                <m.p variants={itemAnim} className="text-center text-xs text-amber-400/70 mb-3">
                    Watch history unavailable — showing all movies
                </m.p>
            )}
            {filtersApplied?.duration_fallback && (
                <m.p variants={itemAnim} className="text-center text-xs text-amber-400/70 mb-3">
                    Couldn't agree on length — showing all durations
                </m.p>
            )}

            {/* Poster with gold glow */}
            <m.div variants={posterAnim} className="flex justify-center mb-5">
                <div className="relative">
                    {/* Gold glow behind poster */}
                    <div className="absolute inset-0 rounded-2xl bg-user-accent/20 blur-2xl scale-105" />
                    {movie.poster_url ? (
                        <img
                            src={movie.poster_url}
                            alt={movie.title}
                            className="relative w-56 aspect-[2/3] object-cover rounded-2xl shadow-2xl shadow-black/50 animate-subtle-float"
                        />
                    ) : (
                        <div className="relative w-56 aspect-[2/3] rounded-2xl bg-user-card border border-user-card-border flex items-center justify-center">
                            <p className="text-user-muted text-sm">No poster</p>
                        </div>
                    )}
                </div>
            </m.div>

            {/* Match score pill */}
            <m.div variants={itemAnim} className="flex justify-center mb-3">
                <span className="px-3 py-1 rounded-full bg-user-accent/15 border border-user-accent/30 text-sm font-bold text-user-accent">
                    {displayScore}% Match
                </span>
            </m.div>

            {/* Title + year/duration */}
            <m.div variants={itemAnim} className="text-center mb-4">
                <h2 className="text-2xl font-bold tracking-tight">{movie.title}</h2>
                <p className="text-user-muted text-sm mt-1">
                    {[
                        movie.year,
                        movie.duration_minutes ? `${movie.duration_minutes} min` : null,
                    ].filter(Boolean).join(" · ")}
                </p>
            </m.div>

            {/* Genre pills */}
            {movie.genres && movie.genres.length > 0 && (
                <m.div variants={itemAnim} className="flex flex-wrap justify-center gap-2 mb-3">
                    {movie.genres.map((genre, i) => (
                        <m.span
                            key={genre}
                            initial={isFirstReveal ? { opacity: 0, scale: 0.8 } : undefined}
                            animate={isFirstReveal ? { opacity: 1, scale: 1 } : undefined}
                            transition={isFirstReveal ? { delay: 0.8 + i * 0.06, duration: 0.3 } : undefined}
                            className="px-2.5 py-1 rounded-full bg-user-card border border-user-card-border text-xs text-user-muted"
                        >
                            {genre}
                        </m.span>
                    ))}
                </m.div>
            )}

            {/* Matched vibe pills */}
            {matchedVibes.length > 0 && (
                <m.div variants={itemAnim} className="flex flex-wrap justify-center gap-2 mb-4">
                    {matchedVibes.map((v, i) => {
                        const vibe = VIBES.find((vb) => vb.key === v);
                        if (!vibe) return null;
                        const VibeIcon = vibe.icon;
                        return (
                            <m.span
                                key={v}
                                initial={isFirstReveal ? { opacity: 0, scale: 0.8 } : undefined}
                                animate={isFirstReveal ? { opacity: 1, scale: 1 } : undefined}
                                transition={isFirstReveal ? { delay: 1.0 + i * 0.06, duration: 0.3 } : undefined}
                                className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-user-accent/10 border border-user-accent/30 text-xs text-user-accent"
                            >
                                <VibeIcon size={12} />
                                {vibe.label}
                            </m.span>
                        );
                    })}
                </m.div>
            )}

            {/* Overview */}
            {movie.overview && (
                <m.p variants={itemAnim} className="text-sm text-user-muted leading-relaxed text-center mb-6">
                    {movie.overview.length > 200
                        ? movie.overview.slice(0, 200) + "…"
                        : movie.overview}
                </m.p>
            )}

            {/* Pick counter */}
            <m.p variants={itemAnim} className="text-center text-xs text-user-muted mb-3">
                Pick {pickNumber} of {totalPicks}
            </m.p>

            {/* Action buttons */}
            <m.div variants={itemAnim} className="flex gap-3">
                <button
                    onClick={onStartOver}
                    className="flex-1 py-3 rounded-2xl border border-user-card-border bg-user-card text-sm font-semibold text-user-muted hover:text-white hover:border-user-accent/30 transition-all duration-200 active:scale-[0.98] flex items-center justify-center gap-2"
                >
                    <RotateCcw size={16} />
                    Start Over
                </button>
                <button
                    onClick={onTryAgain}
                    disabled={isLastMovie}
                    className={`
                        flex-1 py-3 rounded-2xl text-sm font-semibold transition-all duration-200
                        flex items-center justify-center gap-2
                        ${isLastMovie
                            ? "bg-user-card border border-user-card-border text-user-muted cursor-not-allowed opacity-50"
                            : "bg-user-accent text-black hover:bg-user-accent-dim active:scale-[0.98]"
                        }
                    `}
                >
                    <Shuffle size={16} />
                    Try Again
                </button>
            </m.div>

            {isLastMovie && (
                <m.p variants={itemAnim} className="text-center text-xs text-user-muted mt-3">
                    That's all for these vibes!
                </m.p>
            )}
        </m.div>
    );
}
