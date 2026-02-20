import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Dice5, PlusCircle, Calendar, BarChart3, Lock, LogOut } from "lucide-react";
import { useAuth } from "../utils/auth";
import { fetchWithAuth } from "../utils/api";
import { timeAgo } from "../utils/dates";

const CAROUSEL_COUNT = 5;
const CAROUSEL_INTERVAL = 8000; // 8 seconds per slide

function getGreeting(): string {
    const hour = new Date().getHours();
    if (hour < 12) return "Good Morning";
    if (hour < 17) return "Good Afternoon";
    return "Good Evening";
}

interface ToolCardProps {
    icon: React.ReactNode;
    title: string;
    subtitle: string;
    onClick?: () => void;
    comingSoon?: boolean;
}

function ToolCard({ icon, title, subtitle, onClick, comingSoon }: ToolCardProps) {
    return (
        <button
            onClick={onClick}
            disabled={comingSoon}
            className={`relative group w-full rounded-2xl border border-user-card-border bg-user-card p-5 text-left transition-all duration-200 ${
                comingSoon
                    ? "opacity-50 cursor-not-allowed"
                    : "hover:border-user-accent/30 hover:bg-user-card/80 active:scale-[0.98]"
            }`}
        >
            {comingSoon && (
                <div className="absolute top-3 right-3">
                    <Lock size={12} className="text-user-muted" />
                </div>
            )}
            <div className="text-user-accent mb-3">{icon}</div>
            <p className="font-semibold text-white text-sm">{title}</p>
            <p className="text-xs text-user-muted uppercase tracking-wider mt-0.5">
                {subtitle}
            </p>
        </button>
    );
}

interface RecentMediaItem {
    title: string;
    year: number | null;
    thumb: string | null;
    art: string | null;
    type: string;
    added_at: string;
    summary: string | null;
}

function FeaturedCard() {
    const [items, setItems] = useState<RecentMediaItem[]>([]);
    const [active, setActive] = useState(0);
    const [loading, setLoading] = useState(true);
    const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

    useEffect(() => {
        // Verify an image URL actually loads in the browser
        const canLoad = (url: string) =>
            new Promise<boolean>((resolve) => {
                const img = new Image();
                img.onload = () => resolve(true);
                img.onerror = () => resolve(false);
                img.src = url;
            });

        fetchWithAuth(`/api/user/recent-media?limit=${CAROUSEL_COUNT * 2}`)
            .then((res) => res.json())
            .then(async (data) => {
                const candidates = (data.items ?? []).filter(
                    (i: RecentMediaItem) => i.art,
                );
                // Only keep items whose backdrop actually loads
                const checks = await Promise.all(
                    candidates.map(async (item: RecentMediaItem) => ({
                        item,
                        ok: await canLoad(item.art!),
                    })),
                );
                setItems(
                    checks
                        .filter((c) => c.ok)
                        .map((c) => c.item)
                        .slice(0, CAROUSEL_COUNT),
                );
            })
            .catch(() => {})
            .finally(() => setLoading(false));
    }, []);

    // Auto-rotate
    const resetTimer = useCallback(() => {
        if (timerRef.current) clearInterval(timerRef.current);
        if (items.length > 1) {
            timerRef.current = setInterval(() => {
                setActive((prev) => (prev + 1) % items.length);
            }, CAROUSEL_INTERVAL);
        }
    }, [items.length]);

    useEffect(() => {
        resetTimer();
        return () => { if (timerRef.current) clearInterval(timerRef.current); };
    }, [resetTimer]);

    const goTo = (index: number) => {
        setActive(index);
        resetTimer();
    };

    // Swipe support
    const touchStartX = useRef(0);
    const handleTouchStart = (e: React.TouchEvent) => {
        touchStartX.current = e.touches[0].clientX;
    };
    const handleTouchEnd = (e: React.TouchEvent) => {
        const delta = e.changedTouches[0].clientX - touchStartX.current;
        if (Math.abs(delta) > 50) {
            // Swipe left = next, swipe right = prev
            const next = delta < 0
                ? (active + 1) % items.length
                : (active - 1 + items.length) % items.length;
            goTo(next);
        }
    };

    // Loading skeleton
    if (loading) {
        return (
            <div className="relative rounded-2xl overflow-hidden border border-user-card-border bg-user-card h-56 animate-pulse">
                <div className="absolute inset-0 bg-gradient-to-br from-user-card-border/30 to-user-bg" />
            </div>
        );
    }

    // No data
    if (items.length === 0) {
        return (
            <div className="relative rounded-2xl overflow-hidden border border-user-card-border bg-user-card h-56">
                <div className="absolute inset-0 bg-gradient-to-br from-user-accent/8 via-user-card to-user-bg" />
                <div className="absolute inset-0 bg-gradient-to-t from-user-bg via-user-bg/70 to-transparent" />
                <div className="absolute bottom-0 left-0 right-0 p-5 z-20">
                    <h3 className="text-lg font-bold text-white">No Recent Content</h3>
                    <p className="text-sm text-user-muted mt-0.5">
                        Check out the latest additions to your server.
                    </p>
                </div>
            </div>
        );
    }

    const item = items[active];

    return (
        <div
            className="relative rounded-2xl overflow-hidden border border-user-card-border bg-user-card h-56 touch-pan-y"
            onTouchStart={handleTouchStart}
            onTouchEnd={handleTouchEnd}
        >
            {/* Background image — crossfade between slides */}
            {items.map((slide, i) => (
                (slide.art || slide.thumb) && (
                    <img
                        key={i}
                        src={slide.art ?? slide.thumb!}
                        alt={slide.title}
                        className={`absolute inset-0 w-full h-full object-cover transition-opacity duration-700 ${
                            i === active ? "opacity-100" : "opacity-0"
                        }`}
                    />
                )
            ))}

            {/* Gradient overlays */}
            <div className="absolute inset-0 bg-gradient-to-t from-user-bg via-user-bg/60 to-transparent z-10" />
            <div className="absolute inset-0 bg-user-bg/30 z-10" />

            {/* Content overlay */}
            <div className="absolute bottom-0 left-0 right-0 p-5 z-20">
                <div className="flex items-center gap-2 mb-2">
                    <span className="text-[10px] font-bold uppercase tracking-wider bg-user-accent text-user-bg px-2 py-0.5 rounded">
                        Recently Added
                    </span>
                    <span className="text-[10px] text-user-muted uppercase tracking-wider">
                        {timeAgo(item.added_at)}
                    </span>
                </div>
                <h3 className="text-lg font-bold text-white">
                    {item.title}{item.year ? ` (${item.year})` : ""}
                </h3>
                {item.summary && (
                    <p className="text-xs text-user-muted mt-0.5 line-clamp-1">
                        {item.summary}
                    </p>
                )}

                {/* Dot indicators */}
                {items.length > 1 && (
                    <div className="flex items-center gap-1.5 mt-3">
                        {items.map((_, i) => (
                            <div
                                key={i}
                                className={`rounded-full transition-all duration-300 ${
                                    i === active
                                        ? "w-5 h-1.5 bg-user-accent"
                                        : "w-1.5 h-1.5 bg-white/30"
                                }`}
                            />
                        ))}
                    </div>
                )}
            </div>
        </div>
    );
}

export default function UserHomePage() {
    const { username, thumb, logout } = useAuth();
    const navigate = useNavigate();

    const handleLogout = () => {
        logout();
        navigate("/login");
    };

    return (
        <div className="space-y-5">
            {/* Greeting + avatar row */}
            <div className="flex items-start justify-between">
                <div>
                    <h1 className="text-[1.7rem] font-extrabold tracking-tight leading-tight">
                        {getGreeting()},
                        <br />
                        <span className="text-user-accent italic">{username}</span>
                    </h1>
                    <p className="text-user-muted text-sm mt-1">The library is open.</p>
                </div>
                <div className="flex items-center gap-2 pt-1">
                    <button
                        onClick={handleLogout}
                        className="p-1.5 text-user-muted hover:text-white transition-colors duration-200"
                        title="Sign out"
                    >
                        <LogOut size={16} />
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

            {/* Featured / recently added */}
            <FeaturedCard />

            {/* Tool grid */}
            <div className="grid grid-cols-2 gap-3">
                <ToolCard
                    icon={<Dice5 size={24} />}
                    title="Movie Night"
                    subtitle="Vibe Picker"
                    onClick={() => navigate("/user/movie-night")}
                />
                <ToolCard
                    icon={<PlusCircle size={24} />}
                    title="Requests"
                    subtitle="Coming Soon"
                    comingSoon
                />
                <ToolCard
                    icon={<Calendar size={24} />}
                    title="Watch Party"
                    subtitle="Coming Soon"
                    comingSoon
                />
                <ToolCard
                    icon={<BarChart3 size={24} />}
                    title="My Stats"
                    subtitle="Coming Soon"
                    comingSoon
                />
            </div>
        </div>
    );
}
