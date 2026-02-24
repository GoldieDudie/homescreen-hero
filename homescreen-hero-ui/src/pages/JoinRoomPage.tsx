import { useState, useEffect, useRef } from "react";
import { useParams } from "react-router-dom";
import {
    Loader2,
    ArrowRight,
    ThumbsUp,
    ThumbsDown,
    RotateCcw,
    Clapperboard,
} from "lucide-react";
import VibeGrid from "../components/movie-night/VibeGrid";
import useRoomPoll from "../hooks/useRoomPoll";

type GuestPhase = "join" | "vibes" | "waiting" | "voting" | "approved" | "exhausted" | "expired" | "error";

const USER_BG = "#080d1a";

export default function JoinRoomPage() {
    const { roomCode: urlCode } = useParams<{ roomCode?: string }>();

    // Match html/body bg so overscroll areas don't flash white
    useEffect(() => {
        const prevHtml = document.documentElement.style.backgroundColor;
        const prevBody = document.body.style.backgroundColor;
        document.documentElement.style.backgroundColor = USER_BG;
        document.body.style.backgroundColor = USER_BG;
        return () => {
            document.documentElement.style.backgroundColor = prevHtml;
            document.body.style.backgroundColor = prevBody;
        };
    }, []);

    const [phase, setPhase] = useState<GuestPhase>("join");
    const [roomCodeInput, setRoomCodeInput] = useState(
        (urlCode?.toUpperCase() ?? "").replace("HERO-", ""),
    );
    const [playerName, setPlayerName] = useState("");
    const [playerToken, setPlayerToken] = useState<string | null>(
        () => sessionStorage.getItem("room_player_token"),
    );
    const [selectedVibes, setSelectedVibes] = useState<string[]>([]);
    const [error, setError] = useState<string | null>(null);
    const [votingDisabled, setVotingDisabled] = useState(false);
    const [codeFocused, setCodeFocused] = useState(false);
    const codeInputRef = useRef<HTMLInputElement>(null);

    const { data: room, error: pollError } = useRoomPoll(playerToken);

    // Sync phase from poll state
    useEffect(() => {
        if (!room) return;
        switch (room.state) {
            case "waiting":
            case "vibes_submitted":
                // If we already submitted vibes, show waiting
                if (playerToken) {
                    const me = room.players.find(
                        (p) => p.has_submitted_vibes && !p.is_host,
                    );
                    // Rough check — if any non-host submitted vibes, assume it's us
                    if (me) setPhase("waiting");
                }
                break;
            case "voting":
                setPhase("voting");
                setVotingDisabled(false);
                break;
            case "approved":
                setPhase("approved");
                break;
            case "exhausted":
                setPhase("exhausted");
                break;
            case "expired":
                setPhase("expired");
                break;
        }
    }, [room, playerToken]);

    // Show poll errors
    useEffect(() => {
        if (pollError && playerToken) {
            setError(pollError);
        }
    }, [pollError, playerToken]);

    const toggleVibe = (key: string) => {
        setSelectedVibes((prev) =>
            prev.includes(key) ? prev.filter((v) => v !== key) : [...prev, key],
        );
    };

    const handleJoin = async () => {
        setError(null);
        const code = roomCodeInput.trim().toUpperCase();
        const name = playerName.trim();
        if (!code || !name) {
            setError("Room code and name are required");
            return;
        }

        try {
            const fullCode = `HERO-${code}`;
            const res = await fetch("/api/movie-night/room/join", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ room_code: fullCode, player_name: name }),
            });
            if (res.status === 404) { setError("Room not found"); return; }
            if (res.status === 409) { setError("Room is full"); return; }
            if (!res.ok) { setError("Failed to join room"); return; }

            const data = await res.json();
            sessionStorage.setItem("room_player_token", data.player_token);
            setPlayerToken(data.player_token);
            setPhase("vibes");
        } catch {
            setError("Connection error");
        }
    };

    const handleSubmitVibes = async () => {
        if (!playerToken || selectedVibes.length < 1) return;
        setError(null);
        try {
            const res = await fetch(`/api/movie-night/room/vibes?token=${playerToken}`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ vibes: selectedVibes }),
            });
            if (!res.ok) {
                setError("Failed to submit vibes");
                return;
            }
            setPhase("waiting");
        } catch {
            setError("Connection error");
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
            // Poll will pick up the state change
        } catch {
            setVotingDisabled(false);
        }
    };

    const currentMovie = room?.current_movie;
    const approvedMovie = room?.approved_movie;

    // Check if we already voted on the current movie
    const myName = room?.players.find((p) => !p.is_host)?.player_name;
    const myVote = room?.votes && myName ? room.votes[myName] : undefined;
    const hasVoted = myVote !== undefined && myVote !== null;

    return (
        <div className="min-h-screen bg-user-bg text-white relative overflow-hidden">
            {/* Background glow — only visible on join phase */}
            {phase === "join" && (
                <div className="absolute top-1/4 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[500px] h-[500px] rounded-full bg-user-accent/5 blur-[120px] pointer-events-none" />
            )}

            <div className="max-w-lg mx-auto px-5 pb-10 relative z-10">
                {/* ERROR BANNER */}
                {error && (
                    <div className="mb-4 pt-6 px-0">
                        <div className="p-3 rounded-xl bg-red-500/10 border border-red-500/20 text-red-400 text-sm">
                            {error}
                        </div>
                    </div>
                )}

                {/* JOIN PHASE */}
                {phase === "join" && (
                    <div className="animate-fade-in flex flex-col items-center justify-center min-h-screen -mt-10">
                        {/* Icon */}
                        <div className="mb-5 p-4 rounded-2xl bg-user-accent/10 border border-user-accent/20">
                            <Clapperboard size={40} className="text-user-accent" />
                        </div>

                        <h1 className="text-3xl font-bold tracking-tight mb-1">Movie Night</h1>
                        <p className="text-sm text-user-accent uppercase tracking-wider font-semibold mb-6">
                            Join a Room
                        </p>

                        <div className="space-y-3 mb-6 w-full">
                            {/* Split-flap code input */}
                            <div
                                className="flex items-center justify-center gap-1.5 mb-2 cursor-text"
                                onClick={() => codeInputRef.current?.focus()}
                            >
                                {"HERO".split("").map((char, i) => (
                                    <span
                                        key={`prefix-${i}`}
                                        className="inline-flex items-center justify-center w-10 h-12 rounded-lg bg-user-card-border/40 border border-user-card-border text-2xl font-mono font-bold text-white shadow-md shadow-black/20"
                                    >
                                        {char}
                                    </span>
                                ))}
                                <span className="text-2xl font-mono font-bold text-user-muted/50 mx-0.5">-</span>
                                {Array.from({ length: 4 }).map((_, i) => {
                                    const isCursor = codeFocused && i === roomCodeInput.length && roomCodeInput.length < 4;
                                    return (
                                        <span
                                            key={`input-${i}`}
                                            className={`inline-flex items-center justify-center w-10 h-12 rounded-lg text-2xl font-mono font-bold shadow-md shadow-black/20 transition-all duration-200 ${
                                                roomCodeInput[i]
                                                    ? "border-2 border-solid border-user-accent/50 bg-user-card-border/60 text-white"
                                                    : isCursor
                                                        ? "border-2 border-solid border-user-accent/70 bg-user-card-border/30"
                                                        : "border-2 border-dashed border-user-card-border/80 bg-user-card-border/20 text-user-muted/30"
                                            }`}
                                        >
                                            {roomCodeInput[i] || (isCursor ? <span className="text-user-accent animate-blink">|</span> : "_")}
                                        </span>
                                    );
                                })}
                            </div>
                            <input
                                ref={codeInputRef}
                                type="text"
                                value={roomCodeInput}
                                onChange={(e) => setRoomCodeInput(e.target.value.toUpperCase().replace(/[^A-Z0-9]/g, ""))}
                                onFocus={() => setCodeFocused(true)}
                                onBlur={() => setCodeFocused(false)}
                                className="sr-only"
                                maxLength={4}
                                autoFocus
                            />
                            <input
                                type="text"
                                placeholder="Display Name"
                                value={playerName}
                                onChange={(e) => setPlayerName(e.target.value)}
                                className="w-full px-4 py-3 rounded-xl bg-user-card-border/40 border border-user-card-border text-white text-center placeholder-white/30 text-base focus:outline-none focus:border-user-accent/50 transition-colors duration-200"
                                maxLength={20}
                            />
                        </div>

                        <button
                            onClick={handleJoin}
                            disabled={!roomCodeInput.trim() || !playerName.trim()}
                            className={`
                                w-full py-3.5 rounded-2xl font-semibold text-sm
                                transition-all duration-300 flex items-center justify-center gap-2
                                ${
                                    roomCodeInput.trim() && playerName.trim()
                                        ? "bg-user-accent text-black hover:bg-user-accent-dim active:scale-[0.98] shadow-lg shadow-user-accent/25"
                                        : "bg-user-card-border/40 text-user-muted/50 border border-user-card-border cursor-not-allowed"
                                }
                            `}
                        >
                            Join Room
                            <ArrowRight size={16} />
                        </button>
                    </div>
                )}

                {/* Header for non-join phases */}
                {phase !== "join" && (
                    <div className="mb-6 pt-6">
                        <h1 className="text-3xl font-bold tracking-tight">Movie Night</h1>
                        <p className="text-sm text-user-accent uppercase tracking-wider font-semibold">
                            {room?.room_code ?? ""}
                        </p>
                    </div>
                )}

                {/* VIBES PHASE */}
                {phase === "vibes" && (
                    <div className="animate-fade-in">
                        <p className="text-user-muted text-sm mb-4">
                            Pick the vibes you're in the mood for
                        </p>

                        <VibeGrid selectedVibes={selectedVibes} onToggle={toggleVibe} />

                        <button
                            onClick={handleSubmitVibes}
                            disabled={selectedVibes.length < 1}
                            className={`
                                w-full mt-6 py-3.5 rounded-2xl font-semibold text-sm
                                transition-all duration-200 flex items-center justify-center gap-2
                                ${
                                    selectedVibes.length >= 1
                                        ? "bg-user-accent text-black hover:bg-user-accent-dim active:scale-[0.98]"
                                        : "bg-user-card text-user-muted border border-user-card-border cursor-not-allowed"
                                }
                            `}
                        >
                            {selectedVibes.length >= 1 ? (
                                <>
                                    Submit Vibes
                                    <ArrowRight size={16} />
                                </>
                            ) : (
                                "Pick at least 1 vibe"
                            )}
                        </button>
                    </div>
                )}

                {/* WAITING PHASE */}
                {phase === "waiting" && (
                    <div className="flex flex-col items-center justify-center py-20 animate-fade-in">
                        <Loader2 size={32} className="animate-spin text-user-accent mb-4" />
                        <p className="text-user-muted text-sm">Waiting for everyone...</p>
                        {room && (
                            <p className="text-user-muted text-xs mt-2">
                                {room.vibes_submitted_count} of {room.players.length} submitted
                            </p>
                        )}
                    </div>
                )}

                {/* VOTING PHASE */}
                {phase === "voting" && currentMovie && (
                    <div className="animate-fade-in">
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
                            <h2 className="text-2xl font-bold tracking-tight">
                                {currentMovie.title}
                            </h2>
                            <p className="text-user-muted text-sm mt-1">
                                {[
                                    currentMovie.year,
                                    currentMovie.duration_minutes ? `${currentMovie.duration_minutes} min` : null,
                                ].filter(Boolean).join(" · ")}
                            </p>
                        </div>

                        {/* Genre pills */}
                        {currentMovie.genres && currentMovie.genres.length > 0 && (
                            <div className="flex flex-wrap justify-center gap-2 mb-3">
                                {currentMovie.genres.map((genre) => (
                                    <span
                                        key={genre}
                                        className="px-2.5 py-1 rounded-full bg-user-card border border-user-card-border text-xs text-user-muted"
                                    >
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

                        {/* Pick counter */}
                        <p className="text-center text-xs text-user-muted mb-4">
                            Movie {(room?.current_movie_index ?? 0) + 1} of {room?.total_movies ?? 0}
                        </p>

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
                    </div>
                )}

                {/* APPROVED PHASE */}
                {phase === "approved" && approvedMovie && (
                    <div className="animate-fade-in text-center">
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
                        <h2 className="text-2xl font-bold tracking-tight mb-1">
                            {approvedMovie.title}
                        </h2>
                        <p className="text-user-muted text-sm mb-4">
                            {[
                                approvedMovie.year,
                                approvedMovie.duration_minutes ? `${approvedMovie.duration_minutes} min` : null,
                            ].filter(Boolean).join(" · ")}
                        </p>
                        <div className="inline-block px-4 py-2 rounded-full bg-green-500/10 border border-green-500/30 text-green-400 text-sm font-semibold">
                            Everyone agreed — enjoy the movie!
                        </div>
                    </div>
                )}

                {/* EXHAUSTED PHASE */}
                {phase === "exhausted" && (
                    <div className="flex flex-col items-center justify-center py-20 animate-fade-in">
                        <RotateCcw size={32} className="text-user-muted mb-4" />
                        <h2 className="text-lg font-bold mb-2">No agreement reached</h2>
                        <p className="text-user-muted text-sm text-center">
                            You went through all the picks without agreeing.<br />
                            Ask the host to start a new session with different vibes!
                        </p>
                    </div>
                )}

                {/* EXPIRED PHASE */}
                {phase === "expired" && (
                    <div className="flex flex-col items-center justify-center py-20 animate-fade-in">
                        <p className="text-user-muted text-sm">This session has expired.</p>
                    </div>
                )}
            </div>
        </div>
    );
}
