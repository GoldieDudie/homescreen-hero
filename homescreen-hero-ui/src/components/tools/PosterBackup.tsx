import { useState, useEffect } from "react";
import {
    Loader2,
    CheckCircle2,
    AlertTriangle,
    Check,
    Image,
    Film,
    Tv,
    Trash2,
    RotateCcw,
    HardDrive,
    Clock,
} from "lucide-react";
import { fetchWithAuth } from "../../utils/api";
import Toast from "../Toast";
import {
    Dialog,
    DialogContent,
    DialogHeader,
    DialogFooter,
    DialogTitle,
    DialogDescription,
    DialogCloseButton,
} from "@/components/ui/dialog";

type PosterBackupProps = {
    onClose: () => void;
};

type LibraryInfo = {
    name: string;
    type: string;
    movie_count: number;
    show_count: number;
    collection_count: number;
};

type LibrarySelection = {
    library_name: string;
    include_movies: boolean;
    include_shows: boolean;
    include_collections: boolean;
};

type BackupSummary = {
    id: string;
    created_at: string;
    total_posters: number;
    movies: number;
    shows: number;
    collections: number;
    size_mb: number;
    libraries: string[];
};

type BackupResult = {
    id: string;
    total_posters: number;
    movies: number;
    shows: number;
    collections: number;
    errors: number;
};

type Progress = {
    processed: number;
    total: number;
    title: string;
};

// SSE stream reader helper
async function readSSEStream(
    response: Response,
    onEvent: (data: Record<string, unknown>) => void,
) {
    const reader = response.body?.getReader();
    if (!reader) throw new Error("No response body");

    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const events = buffer.split("\n\n");
        buffer = events.pop() || "";

        for (const event of events) {
            if (!event.trim()) continue;
            const dataMatch = event.match(/^data: (.+)$/m);
            if (!dataMatch) continue;
            try {
                onEvent(JSON.parse(dataMatch[1]));
            } catch {
                // skip unparseable events
            }
        }
    }
}

export default function PosterBackup({ onClose }: PosterBackupProps) {
    const [libraries, setLibraries] = useState<LibraryInfo[]>([]);
    const [selections, setSelections] = useState<Record<string, LibrarySelection>>({});
    const [backups, setBackups] = useState<BackupSummary[]>([]);
    const [loading, setLoading] = useState(true);
    const [backing, setBacking] = useState(false);
    const [restoring, setRestoring] = useState<string | null>(null);
    const [deleting, setDeleting] = useState<string | null>(null);
    const [result, setResult] = useState<BackupResult | null>(null);
    const [progress, setProgress] = useState<Progress | null>(null);
    const [toast, setToast] = useState<{ message: string; type: "success" | "error" } | null>(null);

    useEffect(() => {
        Promise.all([
            fetchWithAuth("/api/tools/poster-backup/libraries").then((r) => r.json()),
            fetchWithAuth("/api/tools/poster-backup/list").then((r) => r.json()),
        ])
            .then(([libs, bkps]) => {
                setLibraries(libs);
                setBackups(bkps);
                const sel: Record<string, LibrarySelection> = {};
                for (const lib of libs) {
                    sel[lib.name] = {
                        library_name: lib.name,
                        include_movies: lib.type === "movie",
                        include_shows: lib.type === "show",
                        include_collections: true,
                    };
                }
                setSelections(sel);
            })
            .catch(() => setToast({ message: "Failed to load libraries", type: "error" }))
            .finally(() => setLoading(false));
    }, []);

    const toggleSelection = (libName: string, field: keyof LibrarySelection) => {
        setSelections((prev) => ({
            ...prev,
            [libName]: {
                ...prev[libName],
                [field]: !prev[libName][field],
            },
        }));
    };

    const hasAnySelected = Object.values(selections).some(
        (s) => s.include_movies || s.include_shows || s.include_collections
    );

    const handleBackup = async () => {
        const selected = Object.values(selections).filter(
            (s) => s.include_movies || s.include_shows || s.include_collections
        );
        if (selected.length === 0) return;

        setBacking(true);
        setResult(null);
        setProgress(null);
        try {
            const r = await fetchWithAuth("/api/tools/poster-backup/start", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ libraries: selected }),
            });
            if (!r.ok) {
                const text = await r.text();
                throw new Error(text || "Backup failed");
            }

            await readSSEStream(r, (data) => {
                if (data.type === "progress") {
                    setProgress({
                        processed: data.processed as number,
                        total: data.total as number,
                        title: data.title as string,
                    });
                } else if (data.type === "complete") {
                    const res = data as unknown as BackupResult;
                    setResult(res);
                    setToast({ message: `Backed up ${res.total_posters} posters`, type: "success" });
                } else if (data.type === "error") {
                    throw new Error(data.message as string);
                }
            });

            // Refresh backup list
            const listR = await fetchWithAuth("/api/tools/poster-backup/list");
            setBackups(await listR.json());
        } catch (e) {
            setToast({ message: String(e), type: "error" });
        } finally {
            setBacking(false);
            setProgress(null);
        }
    };

    const handleRestore = async (backupId: string) => {
        setRestoring(backupId);
        setProgress(null);
        try {
            const r = await fetchWithAuth(`/api/tools/poster-backup/restore/${backupId}`, {
                method: "POST",
            });
            if (!r.ok) throw new Error(await r.text());

            let finalResult = { total_restored: 0, errors: 0 };
            await readSSEStream(r, (data) => {
                if (data.type === "progress") {
                    setProgress({
                        processed: data.processed as number,
                        total: data.total as number,
                        title: data.title as string,
                    });
                } else if (data.type === "complete") {
                    finalResult = { total_restored: data.total_restored as number, errors: data.errors as number };
                }
            });

            setToast({
                message: `Restored ${finalResult.total_restored} posters${finalResult.errors > 0 ? ` (${finalResult.errors} errors)` : ""}`,
                type: finalResult.errors > 0 ? "error" : "success",
            });
        } catch (e) {
            setToast({ message: String(e), type: "error" });
        } finally {
            setRestoring(null);
            setProgress(null);
        }
    };

    const handleDelete = async (backupId: string) => {
        setDeleting(backupId);
        try {
            const r = await fetchWithAuth(`/api/tools/poster-backup/${backupId}`, {
                method: "DELETE",
            });
            if (!r.ok) throw new Error(await r.text());
            setBackups((prev) => prev.filter((b) => b.id !== backupId));
            setToast({ message: "Backup deleted", type: "success" });
        } catch (e) {
            setToast({ message: String(e), type: "error" });
        } finally {
            setDeleting(null);
        }
    };

    const formatDate = (iso: string) => {
        try {
            return new Date(iso).toLocaleDateString(undefined, {
                year: "numeric",
                month: "short",
                day: "numeric",
                hour: "2-digit",
                minute: "2-digit",
            });
        } catch {
            return iso;
        }
    };

    const isWorking = backing || restoring !== null;
    const progressPct = progress ? Math.round((progress.processed / progress.total) * 100) : 0;

    return (
        <>
            <Dialog open onOpenChange={(open) => { if (!open && !isWorking) onClose(); }}>
                <DialogContent className="max-w-2xl">
                    <DialogHeader>
                        <div>
                            <DialogTitle>Poster Backup / Restore</DialogTitle>
                            <DialogDescription>
                                Backup and restore your Plex posters for movies, shows, and collections.
                            </DialogDescription>
                        </div>
                        <DialogCloseButton />
                    </DialogHeader>

                    <div className="p-6 space-y-6 overflow-y-auto max-h-[60vh] scrollbar-hover-only">
                        {loading ? (
                            <div className="flex items-center justify-center py-12">
                                <Loader2 className="h-6 w-6 animate-spin text-slate-400" />
                            </div>
                        ) : (
                            <>
                                {/* Progress Bar */}
                                {isWorking && progress && (
                                    <div className="space-y-2">
                                        <div className="flex items-center justify-between text-sm">
                                            <span className="text-slate-300">
                                                {backing ? "Backing up" : "Restoring"}: {progress.title}
                                            </span>
                                            <span className="text-slate-400 tabular-nums">
                                                {progress.processed} / {progress.total}
                                            </span>
                                        </div>
                                        <div className="h-2 w-full rounded-full bg-slate-800 overflow-hidden">
                                            <div
                                                className="h-full rounded-full bg-primary transition-all duration-300 ease-out"
                                                style={{ width: `${progressPct}%` }}
                                            />
                                        </div>
                                        <p className="text-xs text-slate-500 text-right">{progressPct}%</p>
                                    </div>
                                )}

                                {/* Library Selection (hidden during work) */}
                                {!isWorking && (
                                    <div>
                                        <h3 className="text-sm font-semibold text-white mb-3">Select What to Back Up</h3>
                                        <div className="space-y-2">
                                            {libraries.map((lib) => {
                                                const sel = selections[lib.name];
                                                if (!sel) return null;
                                                return (
                                                    <div
                                                        key={lib.name}
                                                        className="rounded-lg border border-slate-800/60 bg-slate-900/50 p-4"
                                                    >
                                                        <div className="flex items-center gap-2 mb-3">
                                                            {lib.type === "movie" ? (
                                                                <Film className="h-4 w-4 text-slate-400" />
                                                            ) : (
                                                                <Tv className="h-4 w-4 text-slate-400" />
                                                            )}
                                                            <span className="text-sm font-medium text-white">{lib.name}</span>
                                                            <span className="text-xs text-slate-500">
                                                                {lib.type === "movie" ? `${lib.movie_count} movies` : `${lib.show_count} shows`}
                                                                {lib.collection_count > 0 && ` · ${lib.collection_count} collections`}
                                                            </span>
                                                        </div>
                                                        <div className="flex items-center gap-4">
                                                            {lib.type === "movie" && (
                                                                <label className="flex items-center gap-2 cursor-pointer" onClick={() => toggleSelection(lib.name, "include_movies")}>
                                                                    <div className={`w-4 h-4 rounded border flex items-center justify-center transition-all flex-shrink-0 ${sel.include_movies ? "bg-primary border-primary" : "border-slate-600"}`}>
                                                                        {sel.include_movies && <Check size={12} className="text-white" />}
                                                                    </div>
                                                                    <span className="text-sm text-slate-300">Movies</span>
                                                                </label>
                                                            )}
                                                            {lib.type === "show" && (
                                                                <label className="flex items-center gap-2 cursor-pointer" onClick={() => toggleSelection(lib.name, "include_shows")}>
                                                                    <div className={`w-4 h-4 rounded border flex items-center justify-center transition-all flex-shrink-0 ${sel.include_shows ? "bg-primary border-primary" : "border-slate-600"}`}>
                                                                        {sel.include_shows && <Check size={12} className="text-white" />}
                                                                    </div>
                                                                    <span className="text-sm text-slate-300">Shows</span>
                                                                </label>
                                                            )}
                                                            {lib.collection_count > 0 && (
                                                                <label className="flex items-center gap-2 cursor-pointer" onClick={() => toggleSelection(lib.name, "include_collections")}>
                                                                    <div className={`w-4 h-4 rounded border flex items-center justify-center transition-all flex-shrink-0 ${sel.include_collections ? "bg-primary border-primary" : "border-slate-600"}`}>
                                                                        {sel.include_collections && <Check size={12} className="text-white" />}
                                                                    </div>
                                                                    <span className="text-sm text-slate-300">Collections</span>
                                                                </label>
                                                            )}
                                                        </div>
                                                    </div>
                                                );
                                            })}
                                        </div>
                                    </div>
                                )}

                                {/* Backup Result */}
                                {result && (
                                    <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-4 py-3">
                                        <div className="flex items-center gap-2.5 mb-3">
                                            <CheckCircle2 className="h-4 w-4 text-emerald-400 shrink-0" />
                                            <p className="text-sm font-medium text-emerald-300">Backup complete</p>
                                        </div>
                                        <div className="grid grid-cols-4 gap-3">
                                            <div className="text-center">
                                                <p className="text-lg font-semibold text-white">{result.total_posters}</p>
                                                <p className="text-xs text-slate-400">total</p>
                                            </div>
                                            <div className="text-center">
                                                <p className="text-lg font-semibold text-white">{result.movies}</p>
                                                <p className="text-xs text-slate-400">movies</p>
                                            </div>
                                            <div className="text-center">
                                                <p className="text-lg font-semibold text-white">{result.shows}</p>
                                                <p className="text-xs text-slate-400">shows</p>
                                            </div>
                                            <div className="text-center">
                                                <p className="text-lg font-semibold text-white">{result.collections}</p>
                                                <p className="text-xs text-slate-400">collections</p>
                                            </div>
                                        </div>
                                        {result.errors > 0 && (
                                            <div className="flex items-center gap-2 mt-3">
                                                <AlertTriangle className="h-3.5 w-3.5 text-amber-400" />
                                                <p className="text-xs text-amber-300">{result.errors} poster{result.errors !== 1 ? "s" : ""} failed to download</p>
                                            </div>
                                        )}
                                    </div>
                                )}

                                {/* Existing Backups */}
                                {backups.length > 0 && !isWorking && (
                                    <div>
                                        <h3 className="text-sm font-semibold text-white mb-3">Previous Backups</h3>
                                        <div className="space-y-2">
                                            {backups.map((backup) => (
                                                <div
                                                    key={backup.id}
                                                    className="rounded-lg border border-slate-800/60 bg-slate-900/50 p-4"
                                                >
                                                    <div className="flex items-center justify-between">
                                                        <div className="space-y-1">
                                                            <div className="flex items-center gap-2">
                                                                <Clock className="h-3.5 w-3.5 text-slate-500" />
                                                                <span className="text-sm font-medium text-white">
                                                                    {formatDate(backup.created_at)}
                                                                </span>
                                                            </div>
                                                            <div className="flex items-center gap-3 text-xs text-slate-400">
                                                                <span className="flex items-center gap-1">
                                                                    <Image className="h-3 w-3" />
                                                                    {backup.total_posters} posters
                                                                </span>
                                                                {backup.movies > 0 && <span>{backup.movies} movies</span>}
                                                                {backup.shows > 0 && <span>{backup.shows} shows</span>}
                                                                {backup.collections > 0 && <span>{backup.collections} collections</span>}
                                                                <span className="flex items-center gap-1">
                                                                    <HardDrive className="h-3 w-3" />
                                                                    {backup.size_mb} MB
                                                                </span>
                                                            </div>
                                                            <div className="text-xs text-slate-500">
                                                                {backup.libraries.join(", ")}
                                                            </div>
                                                        </div>
                                                        <div className="flex items-center gap-2">
                                                            <button
                                                                type="button"
                                                                onClick={() => handleRestore(backup.id)}
                                                                disabled={restoring !== null || deleting !== null}
                                                                className="rounded-lg border border-slate-700 bg-slate-800 px-3 py-1.5 text-xs font-medium text-slate-300 hover:bg-slate-700 transition-colors disabled:opacity-50 flex items-center gap-1.5"
                                                            >
                                                                <RotateCcw className="h-3 w-3" />
                                                                Restore
                                                            </button>
                                                            <button
                                                                type="button"
                                                                onClick={() => handleDelete(backup.id)}
                                                                disabled={restoring !== null || deleting !== null}
                                                                className="rounded-lg border border-slate-700 bg-slate-800 px-3 py-1.5 text-xs font-medium text-red-400 hover:bg-red-500/20 hover:border-red-500/40 transition-colors disabled:opacity-50 flex items-center gap-1.5"
                                                            >
                                                                {deleting === backup.id ? (
                                                                    <Loader2 className="h-3 w-3 animate-spin" />
                                                                ) : (
                                                                    <Trash2 className="h-3 w-3" />
                                                                )}
                                                                {deleting === backup.id ? "Deleting..." : "Delete"}
                                                            </button>
                                                        </div>
                                                    </div>
                                                </div>
                                            ))}
                                        </div>
                                    </div>
                                )}
                            </>
                        )}
                    </div>

                    <DialogFooter>
                        <button
                            type="button"
                            onClick={onClose}
                            disabled={isWorking}
                            className="rounded-lg border border-slate-700 bg-slate-800 px-4 py-2 text-sm font-medium text-slate-300 hover:bg-slate-700 transition-colors disabled:opacity-50"
                        >
                            {result ? "Done" : "Cancel"}
                        </button>
                        {!result && (
                            <button
                                type="button"
                                onClick={handleBackup}
                                disabled={isWorking || !hasAnySelected || loading}
                                className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary-hover disabled:opacity-50 transition-colors flex items-center gap-2"
                            >
                                {backing && <Loader2 className="h-4 w-4 animate-spin" />}
                                {backing ? "Backing Up..." : "Back Up Now"}
                            </button>
                        )}
                    </DialogFooter>
                </DialogContent>
            </Dialog>

            {toast && (
                <Toast
                    message={toast.message}
                    type={toast.type}
                    onClose={() => setToast(null)}
                />
            )}
        </>
    );
}
