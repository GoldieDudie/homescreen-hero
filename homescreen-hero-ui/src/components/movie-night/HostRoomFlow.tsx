import { useState, useEffect } from "react";
import {
    ArrowLeft,
    ArrowRight,
    Timer,
    Clock,
    Hourglass,
    Sparkles,
    RotateCcw,
    Shuffle,
    Loader2,
    Copy,
    Check,
    ThumbsUp,
    ThumbsDown,
    type LucideIcon,
} from "lucide-react";
import { fetchWithAuth } from "../../utils/api";
import VibeGrid from "./VibeGrid";
import useRoomPoll from "../../hooks/useRoomPoll";

const DURATION_OPTIONS: { key: string | null; label: string; desc: string; icon: LucideIcon | null }[] = [
    { key: null, label: "Any Length", desc: "No preference", icon: null },
    { key: "quick", label: "Quick Watch", desc: "Under 100 min", icon: Timer },
    { key: "standard", label: "Standard", desc: "100-150 min", icon: Clock },
    { key: "long", label: "I'm Committed", desc: "Over 150 min", icon: Hourglass },
];

const REWATCH_OPTIONS: { key: string; label: string; desc: string; icon: LucideIcon }[] = [
    { key: "new", label: "Something New", desc: "Haven't seen it yet", icon: Sparkles },
    { key: "rewatch", label: "Rewatch a Fave", desc: "Something I've loved", icon: RotateCcw },
    { key: "any", label: "Don't Care", desc: "Surprise me", icon: Shuffle },
];

type HostPhase = "vibes" | "filters" | "creating" | "waiting" | "voting" | "approved" | "exhausted";

interface HostRoomFlowProps {
    onBack: () => void;
}

export default function HostRoomFlow({ onBack }: HostRoomFlowProps) {
    const [phase, setPhase] = useState<HostPhase>("vibes");
    const [selectedVibes, setSelectedVibes] = useState<string[]>([]);
    const [durationFilter, setDurationFilter] = useState<string | null>(null);
    const [rewatchMode, setRewatchMode] = useState<string>("new");
    const [maxPlayers, setMaxPlayers] = useState(4);
    const [error, setError] = useState<string | null>(null);
    const [playerToken, setPlayerToken] = useState<string | null>(null);
    const [roomCode, setRoomCode] = useState<string | null>(null);
    const [copied, setCopied] = useState(false);
    const [votingDisabled, setVotingDisabled] = useState(false);
    const [matchingInProgress, setMatchingInProgress] = useState(false);

    const { data: room } = useRoomPoll(playerToken);

    // Sync phase from poll state
    const effectivePhase = (() => {
        if (!room) return phase;
        if (room.state === "voting") return "voting";
        if (room.state === "approved") return "approved";
        if (room.state === "exhausted") return "exhausted";
        if (room.state === "expired") { onBack(); return phase; }
        return phase;
    })();

    const toggleVibe = (key: string) => {
        setSelectedVibes((prev) =>
            prev.includes(key) ? prev.filter((v) => v !== key) : [...prev, key],
        );
    };

    const handleCreateRoom = async () => {
        setPhase("creating");
        setError(null);
        try {
            const res = await fetchWithAuth("/api/movie-night/room/create", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    duration: durationFilter,
                    rewatch_mode: rewatchMode,
                    max_players: maxPlayers,
                }),
            });
            if (!res.ok) throw new Error("Failed to create room");
            const data = await res.json();
            setRoomCode(data.room_code);
            setPlayerToken(data.host_player_token);

            // Submit host vibes immediately
            const vibesRes = await fetch(`/api/movie-night/room/vibes?token=${data.host_player_token}`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ vibes: selectedVibes }),
            });
            if (!vibesRes.ok) throw new Error("Failed to submit vibes");

            setPhase("waiting");
        } catch {
            setError("Failed to create room. Please try again.");
            setPhase("filters");
        }
    };

    const handleCopyCode = () => {
        if (!roomCode) return;
        const url = `${window.location.origin}/join/${roomCode.replace("HERO-", "")}`;
        navigator.clipboard.writeText(url);
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
    };

    const handleStartMatching = async () => {
        if (!playerToken) return;
        setMatchingInProgress(true);
        setError(null);
        try {
            const res = await fetchWithAuth(`/api/movie-night/room/start-matching?token=${playerToken}`, {
                method: "POST",
            });
            if (!res.ok) {
                const data = await res.json().catch(() => null);
                setError(data?.detail ?? "Failed to start matching");
            }
            // Poll will transition to voting
        } catch {
            setError("Connection error");
        } finally {
            setMatchingInProgress(false);
        }
    };

    const handleVote = async (approve: boolean) => {
        if (!playerToken || votingDisabled) return;
        setVotingDisabled(true);
        try {
            await fetch(`/api/movie-night/room/vote?token=${playerToken}`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ approve }),
            });
        } catch {
            setVotingDisabled(false);
        }
    };

    const handleCancelRoom = async () => {
        if (!roomCode) return;
        await fetchWithAuth(`/api/movie-night/room/${roomCode}`, { method: "DELETE" });
        onBack();
    };

    // Reset votingDisabled when movie index changes (new movie to vote on)
    const movieIndex = room?.current_movie_index ?? -1;
    useEffect(() => {
        setVotingDisabled(false);
    }, [movieIndex]);

    const allVibesSubmitted = room
        ? room.vibes_submitted_count === room.players.length
        : false;

    const currentMovie = room?.current_movie;
    const approvedMovie = room?.approved_movie;

    // Check if host already voted
    const myName = room?.players.find((p) => p.is_host)?.player_name;
    const myVote = room?.votes && myName ? room.votes[myName] : undefined;
    const hasVoted = myVote !== undefined && myVote !== null;

    return (
        <div className="animate-fade-in">
            {error && (
                <div className="mb-4 p-3 rounded-xl bg-red-500/10 border border-red-500/20 text-red-400 text-sm">
                    {error}
                </div>
            )}

            {/* VIBES PHASE */}
            {effectivePhase === "vibes" && (
                <>
                    <p className="text-user-muted text-sm mb-4">
                        Pick the vibes you're in the mood for
                    </p>

                    <VibeGrid selectedVibes={selectedVibes} onToggle={toggleVibe} />

                    <div className="flex gap-3 mt-6">
                        <button
                            onClick={onBack}
                            className="flex-1 py-3 rounded-2xl border border-user-card-border bg-user-card text-sm font-semibold text-user-muted hover:text-white hover:border-user-accent/30 transition-all duration-200 active:scale-[0.98] flex items-center justify-center gap-2"
                        >
                            <ArrowLeft size={16} />
                            Back
                        </button>
                        <button
                            onClick={() => setPhase("filters")}
                            disabled={selectedVibes.length < 1}
                            className={`
                                flex-1 py-3 rounded-2xl font-semibold text-sm
                                transition-all duration-200 flex items-center justify-center gap-2
                                ${
                                    selectedVibes.length >= 1
                                        ? "bg-user-accent text-black hover:bg-user-accent-dim active:scale-[0.98]"
                                        : "bg-user-card text-user-muted border border-user-card-border cursor-not-allowed"
                                }
                            `}
                        >
                            {selectedVibes.length >= 1 ? (
                                <>Next <ArrowRight size={16} /></>
                            ) : "Pick at least 1 vibe"}
                        </button>
                    </div>
                </>
            )}

            {/* FILTERS PHASE */}
            {effectivePhase === "filters" && (
                <>
                    <p className="text-user-muted text-sm mb-5">
                        Set filters for the room
                    </p>

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
                                        ${isSelected
                                            ? "border-user-accent bg-user-accent/10"
                                            : "border-user-card-border bg-user-card hover:border-user-accent/30"
                                        }
                                    `}
                                >
                                    {Icon && (
                                        <Icon size={18} className={`mb-1 ${isSelected ? "text-user-accent" : "text-user-muted"}`} />
                                    )}
                                    <p className={`text-sm font-semibold ${isSelected ? "text-white" : "text-slate-300"}`}>{label}</p>
                                    <p className="text-xs text-user-muted">{desc}</p>
                                </button>
                            );
                        })}
                    </div>

                    {/* Rewatch mode */}
                    <h3 className="text-xs uppercase tracking-wider text-user-muted mb-2 font-semibold">
                        Seen it before?
                    </h3>
                    <div className="grid grid-cols-3 gap-2 mb-5">
                        {REWATCH_OPTIONS.map(({ key, label, desc, icon: Icon }) => {
                            const isSelected = rewatchMode === key;
                            return (
                                <button
                                    key={key}
                                    onClick={() => setRewatchMode(key)}
                                    className={`
                                        rounded-xl border p-3 text-left transition-all duration-200
                                        ${isSelected
                                            ? "border-user-accent bg-user-accent/10"
                                            : "border-user-card-border bg-user-card hover:border-user-accent/30"
                                        }
                                    `}
                                >
                                    <Icon size={18} className={`mb-1 ${isSelected ? "text-user-accent" : "text-user-muted"}`} />
                                    <p className={`text-xs font-semibold mt-1 ${isSelected ? "text-white" : "text-slate-300"}`}>{label}</p>
                                    <p className="text-[10px] text-user-muted leading-tight mt-0.5">{desc}</p>
                                </button>
                            );
                        })}
                    </div>

                    {/* Max players */}
                    <h3 className="text-xs uppercase tracking-wider text-user-muted mb-2 font-semibold">
                        Max players
                    </h3>
                    <div className="flex gap-2 mb-6">
                        {[2, 3, 4, 5, 6].map((n) => (
                            <button
                                key={n}
                                onClick={() => setMaxPlayers(n)}
                                className={`
                                    w-10 h-10 rounded-xl border text-sm font-semibold transition-all duration-200
                                    ${maxPlayers === n
                                        ? "border-user-accent bg-user-accent/10 text-white"
                                        : "border-user-card-border bg-user-card text-user-muted hover:border-user-accent/30"
                                    }
                                `}
                            >
                                {n}
                            </button>
                        ))}
                    </div>

                    {/* Navigation */}
                    <div className="flex gap-3">
                        <button
                            onClick={() => setPhase("vibes")}
                            className="flex-1 py-3 rounded-2xl border border-user-card-border bg-user-card text-sm font-semibold text-user-muted hover:text-white hover:border-user-accent/30 transition-all duration-200 active:scale-[0.98] flex items-center justify-center gap-2"
                        >
                            <ArrowLeft size={16} />
                            Back
                        </button>
                        <button
                            onClick={handleCreateRoom}
                            className="flex-1 py-3 rounded-2xl bg-user-accent text-black font-semibold text-sm hover:bg-user-accent-dim active:scale-[0.98] transition-all duration-200 flex items-center justify-center gap-2"
                        >
                            Create Room
                            <ArrowRight size={16} />
                        </button>
                    </div>
                </>
            )}

            {/* CREATING PHASE */}
            {effectivePhase === "creating" && (
                <div className="flex flex-col items-center justify-center py-20">
                    <Loader2 size={32} className="animate-spin text-user-accent mb-4" />
                    <p className="text-user-muted text-sm">Creating room...</p>
                </div>
            )}

            {/* WAITING ROOM */}
            {effectivePhase === "waiting" && roomCode && (
                <div className="text-center">
                    <p className="text-user-muted text-sm mb-4">Share this code with your group</p>

                    {/* Big room code */}
                    <div className="mb-4">
                        <p className="text-4xl font-mono font-bold tracking-[0.3em] text-white">
                            {roomCode}
                        </p>
                    </div>

                    {/* Copy link button */}
                    <button
                        onClick={handleCopyCode}
                        className="inline-flex items-center gap-2 px-4 py-2 rounded-xl border border-user-card-border bg-user-card text-sm text-user-muted hover:text-white hover:border-user-accent/30 transition-all duration-200 mb-6"
                    >
                        {copied ? <Check size={16} className="text-green-400" /> : <Copy size={16} />}
                        {copied ? "Copied!" : "Copy invite link"}
                    </button>

                    {/* Player list */}
                    <div className="mb-6">
                        <h3 className="text-xs uppercase tracking-wider text-user-muted mb-2 font-semibold">
                            Players ({room?.players.length ?? 1})
                        </h3>
                        <div className="space-y-2">
                            {room?.players.map((p) => (
                                <div
                                    key={p.player_name}
                                    className="flex items-center justify-between px-4 py-2.5 rounded-xl bg-user-card border border-user-card-border"
                                >
                                    <span className="text-sm font-medium">
                                        {p.player_name}
                                        {p.is_host && (
                                            <span className="ml-2 text-xs text-user-accent">(host)</span>
                                        )}
                                    </span>
                                    <span className={`text-xs ${p.has_submitted_vibes ? "text-green-400" : "text-user-muted"}`}>
                                        {p.has_submitted_vibes ? "Ready" : "Picking vibes..."}
                                    </span>
                                </div>
                            ))}
                        </div>
                    </div>

                    {/* Start matching button (only when all submitted) */}
                    {allVibesSubmitted && (room?.players.length ?? 0) >= 2 ? (
                        <button
                            onClick={handleStartMatching}
                            disabled={matchingInProgress}
                            className="w-full py-3.5 rounded-2xl bg-user-accent text-black font-semibold text-sm hover:bg-user-accent-dim active:scale-[0.98] transition-all duration-200 flex items-center justify-center gap-2"
                        >
                            {matchingInProgress ? (
                                <Loader2 size={18} className="animate-spin" />
                            ) : (
                                "Find Our Movie"
                            )}
                        </button>
                    ) : (
                        <p className="text-user-muted text-xs">
                            {(room?.players.length ?? 1) < 2
                                ? "Waiting for players to join..."
                                : "Waiting for everyone to submit vibes..."}
                        </p>
                    )}

                    {/* Cancel */}
                    <button
                        onClick={handleCancelRoom}
                        className="mt-4 text-xs text-user-muted hover:text-red-400 transition-colors"
                    >
                        Cancel Room
                    </button>
                </div>
            )}

            {/* VOTING PHASE */}
            {effectivePhase === "voting" && currentMovie && (
                <>
                    {/* Poster */}
                    <div className="flex justify-center mb-5">
                        {currentMovie.poster_url ? (
                            <img
                                src={currentMovie.poster_url}
                                alt={currentMovie.title}
                                className="w-52 aspect-[2/3] object-cover rounded-2xl shadow-2xl shadow-black/50"
                            />
                        ) : (
                            <div className="w-52 aspect-[2/3] rounded-2xl bg-user-card border border-user-card-border flex items-center justify-center">
                                <p className="text-user-muted text-sm">No poster</p>
                            </div>
                        )}
                    </div>

                    {/* Title + meta */}
                    <div className="text-center mb-4">
                        <h2 className="text-2xl font-bold tracking-tight">{currentMovie.title}</h2>
                        <p className="text-user-muted text-sm mt-1">
                            {[
                                currentMovie.year,
                                currentMovie.duration_minutes ? `${currentMovie.duration_minutes} min` : null,
                            ].filter(Boolean).join(" \u00b7 ")}
                        </p>
                    </div>

                    {/* Genres */}
                    {currentMovie.genres && currentMovie.genres.length > 0 && (
                        <div className="flex flex-wrap justify-center gap-2 mb-3">
                            {currentMovie.genres.map((genre) => (
                                <span key={genre} className="px-2.5 py-1 rounded-full bg-user-card border border-user-card-border text-xs text-user-muted">
                                    {genre}
                                </span>
                            ))}
                        </div>
                    )}

                    {/* Overview */}
                    {currentMovie.overview && (
                        <p className="text-sm text-user-muted leading-relaxed text-center mb-6">
                            {currentMovie.overview.length > 200
                                ? currentMovie.overview.slice(0, 200) + "\u2026"
                                : currentMovie.overview}
                        </p>
                    )}

                    {/* Pick counter + vote status */}
                    <p className="text-center text-xs text-user-muted mb-2">
                        Movie {(room?.current_movie_index ?? 0) + 1} of {room?.total_movies ?? 0}
                    </p>

                    {/* Vote tallies */}
                    {room?.votes && (
                        <div className="flex justify-center gap-3 mb-4">
                            {Object.entries(room.votes).map(([name, vote]) => (
                                <span
                                    key={name}
                                    className={`text-xs px-2 py-1 rounded-full border ${
                                        vote === true ? "border-green-500/30 text-green-400" :
                                        vote === false ? "border-red-500/30 text-red-400" :
                                        "border-user-card-border text-user-muted"
                                    }`}
                                >
                                    {name}: {vote === true ? "Yes" : vote === false ? "No" : "..."}
                                </span>
                            ))}
                        </div>
                    )}

                    {/* Vote buttons */}
                    {hasVoted ? (
                        <div className="text-center py-4">
                            <p className="text-user-muted text-sm">
                                {myVote ? "You voted yes" : "You voted no"} — waiting for others...
                            </p>
                        </div>
                    ) : (
                        <div className="flex gap-3">
                            <button
                                onClick={() => handleVote(false)}
                                disabled={votingDisabled}
                                className="flex-1 py-3.5 rounded-2xl border border-user-card-border bg-user-card text-sm font-semibold text-user-muted hover:text-red-400 hover:border-red-400/30 transition-all duration-200 active:scale-[0.98] flex items-center justify-center gap-2"
                            >
                                <ThumbsDown size={18} />
                                Nah
                            </button>
                            <button
                                onClick={() => handleVote(true)}
                                disabled={votingDisabled}
                                className="flex-1 py-3.5 rounded-2xl bg-user-accent text-black font-semibold text-sm hover:bg-user-accent-dim active:scale-[0.98] transition-all duration-200 flex items-center justify-center gap-2"
                            >
                                <ThumbsUp size={18} />
                                Let's Watch
                            </button>
                        </div>
                    )}
                </>
            )}

            {/* APPROVED PHASE */}
            {effectivePhase === "approved" && approvedMovie && (
                <div className="text-center">
                    <div className="flex justify-center mb-5">
                        {approvedMovie.poster_url ? (
                            <img
                                src={approvedMovie.poster_url}
                                alt={approvedMovie.title}
                                className="w-52 aspect-[2/3] object-cover rounded-2xl shadow-2xl shadow-black/50"
                            />
                        ) : (
                            <div className="w-52 aspect-[2/3] rounded-2xl bg-user-card border border-user-card-border flex items-center justify-center">
                                <p className="text-user-muted text-sm">No poster</p>
                            </div>
                        )}
                    </div>
                    <h2 className="text-2xl font-bold tracking-tight mb-1">{approvedMovie.title}</h2>
                    <p className="text-user-muted text-sm mb-4">
                        {[
                            approvedMovie.year,
                            approvedMovie.duration_minutes ? `${approvedMovie.duration_minutes} min` : null,
                        ].filter(Boolean).join(" \u00b7 ")}
                    </p>
                    <div className="inline-block px-4 py-2 rounded-full bg-green-500/10 border border-green-500/30 text-green-400 text-sm font-semibold mb-6">
                        Everyone agreed — enjoy the movie!
                    </div>
                    <div>
                        <button
                            onClick={onBack}
                            className="px-6 py-2.5 rounded-2xl border border-user-card-border bg-user-card text-sm font-semibold text-user-muted hover:text-white hover:border-user-accent/30 transition-all duration-200"
                        >
                            Start Over
                        </button>
                    </div>
                </div>
            )}

            {/* EXHAUSTED PHASE */}
            {effectivePhase === "exhausted" && (
                <div className="flex flex-col items-center justify-center py-20">
                    <RotateCcw size={32} className="text-user-muted mb-4" />
                    <h2 className="text-lg font-bold mb-2">No agreement reached</h2>
                    <p className="text-user-muted text-sm text-center mb-6">
                        You went through all the picks without agreeing.
                    </p>
                    <button
                        onClick={onBack}
                        className="px-6 py-2.5 rounded-2xl border border-user-card-border bg-user-card text-sm font-semibold text-user-muted hover:text-white hover:border-user-accent/30 transition-all duration-200"
                    >
                        Try Different Vibes
                    </button>
                </div>
            )}
        </div>
    );
}
