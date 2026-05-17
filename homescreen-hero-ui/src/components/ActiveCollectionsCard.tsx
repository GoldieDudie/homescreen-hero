import { useCallback, useEffect, useMemo, useState } from "react";
import { useBlocker, useNavigate } from "react-router-dom";
import {
    DndContext,
    closestCenter,
    KeyboardSensor,
    PointerSensor,
    useSensor,
    useSensors,
} from "@dnd-kit/core";
import type { DragEndEvent } from "@dnd-kit/core";
import {
    arrayMove,
    SortableContext,
    sortableKeyboardCoordinates,
    useSortable,
    verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { GripVertical, Layers, Pin, ChevronRight } from "lucide-react";
import { fetchWithAuth } from "../utils/api";
import { useTheme } from "../utils/theme";

// ── Types ──────────────────────────────────────────────────────────────────

interface CollectionRef {
    library: string;
    name: string;
}

// Legacy export — kept so DashboardPage import doesn't break
export type ActiveCollection = {
    title: string;
    poster_url?: string | null;
    library?: string | null;
    promoted_to_own_home?: boolean;
    promoted_to_shared?: boolean;
    promoted_to_recommended?: boolean;
    is_pinned?: boolean;
    display_order?: number;
};

interface ActiveCollectionOut {
    title: string;
    library?: string | null;
    poster_url?: string | null;
    promoted_to_own_home: boolean;
    promoted_to_shared: boolean;
    promoted_to_recommended: boolean;
    is_pinned: boolean;
    display_order: number;
}

interface DashboardGroupItem {
    type: "group";
    group_name: string;
    group_index: number;
    collections: CollectionRef[];
    active_collections: ActiveCollectionOut[];
    display_order: number;
    promoted_to_own_home: boolean;
    promoted_to_shared: boolean;
    promoted_to_recommended: boolean;
}

interface DashboardIndividualItem {
    type: "individual";
    title: string;
    library?: string | null;
    poster_url?: string | null;
    promoted_to_own_home: boolean;
    promoted_to_shared: boolean;
    promoted_to_recommended: boolean;
    is_pinned: boolean;
    display_order: number;
}

type DashboardItem = DashboardGroupItem | DashboardIndividualItem;

interface DashboardLibraryRow {
    name: string;
    items: DashboardItem[];
}

interface DashboardCollectionsResponse {
    libraries: DashboardLibraryRow[];
}

// ── Helpers ────────────────────────────────────────────────────────────────

function itemId(item: DashboardItem): string {
    return item.type === "group"
        ? `group::${item.group_name}`
        : `individual::${item.library ?? ""}::${item.title}`;
}

// ── VisibilityCheckbox ─────────────────────────────────────────────────────

function VisibilityCheckbox({
    checked,
    onChange,
    disabled,
}: {
    checked: boolean;
    onChange: (v: boolean) => void;
    disabled?: boolean;
}) {
    return (
        <button
            type="button"
            disabled={disabled}
            onClick={() => onChange(!checked)}
            className={`w-4 h-4 rounded border flex items-center justify-center transition-colors shrink-0 ${
                checked
                    ? "bg-primary border-primary"
                    : "bg-transparent border-slate-600 hover:border-slate-400"
            } ${disabled ? "opacity-40 cursor-not-allowed" : "cursor-pointer"}`}
            aria-checked={checked}
        >
            {checked && (
                <svg viewBox="0 0 10 8" className="w-2.5 h-2 fill-white">
                    <path d="M1 4l3 3 5-6" stroke="white" strokeWidth="1.5" fill="none" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
            )}
        </button>
    );
}

// ── SortableRow ────────────────────────────────────────────────────────────

function SortableGroupRow({
    item,
    onVisibilityChange,
    dirty,
}: {
    item: DashboardGroupItem;
    onVisibilityChange: (home: boolean, shared: boolean, rec: boolean) => void;
    dirty: boolean;
}) {
    const navigate = useNavigate();
    const id = itemId(item);
    const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id });

    const style = {
        transform: CSS.Transform.toString(transform),
        transition: transition ?? "transform 150ms ease",
    };

    const activeNames = item.active_collections.map(c => c.title).join(" · ");

    return (
        <div
            ref={setNodeRef}
            style={style}
            className={`flex items-center gap-3 px-2 py-2 rounded-lg hover:bg-white/5 transition-colors ${isDragging ? "opacity-50 bg-white/5" : ""} ${dirty ? "bg-primary/5" : ""}`}
        >
            {/* Drag handle */}
            <button
                {...attributes}
                {...listeners}
                className="text-slate-600 hover:text-slate-400 cursor-grab active:cursor-grabbing shrink-0 touch-none"
                onClick={e => e.stopPropagation()}
            >
                <GripVertical size={14} />
            </button>

            {/* Name */}
            <button
                type="button"
                onClick={() => navigate("/groups")}
                className="flex items-center gap-2 flex-1 min-w-0 text-left group/name"
            >
                {dirty && <span className="w-1.5 h-1.5 rounded-full bg-primary shrink-0" title="Unsaved" />}
                <Layers size={13} className="text-slate-500 shrink-0" />
                <span className="text-sm text-slate-200 truncate group-hover/name:text-white transition-colors">
                    {item.group_name}
                </span>
                {activeNames && (
                    <span className="text-[10px] text-slate-500 truncate hidden sm:block">
                        {activeNames}
                    </span>
                )}
            </button>

            {/* Visibility checkboxes — 64px cells to align with header labels */}
            <div className="flex items-center shrink-0">
                <div className="w-16 flex justify-center">
                    <VisibilityCheckbox
                        checked={item.promoted_to_own_home}
                        onChange={v => onVisibilityChange(v, item.promoted_to_shared, item.promoted_to_recommended)}
                    />
                </div>
                <div className="w-16 flex justify-center">
                    <VisibilityCheckbox
                        checked={item.promoted_to_shared}
                        onChange={v => onVisibilityChange(item.promoted_to_own_home, v, item.promoted_to_recommended)}
                    />
                </div>
                <div className="w-16 flex justify-center">
                    <VisibilityCheckbox
                        checked={item.promoted_to_recommended}
                        onChange={v => onVisibilityChange(item.promoted_to_own_home, item.promoted_to_shared, v)}
                    />
                </div>
            </div>
        </div>
    );
}

function SortableIndividualRow({
    item,
    onVisibilityChange,
    dirty,
}: {
    item: DashboardIndividualItem;
    onVisibilityChange: (home: boolean, shared: boolean, rec: boolean) => void;
    dirty: boolean;
}) {
    const navigate = useNavigate();
    const id = itemId(item);
    const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id });

    const style = {
        transform: CSS.Transform.toString(transform),
        transition: transition ?? "transform 150ms ease",
    };

    return (
        <div
            ref={setNodeRef}
            style={style}
            className={`flex items-center gap-3 px-2 py-2 rounded-lg hover:bg-white/5 transition-colors ${isDragging ? "opacity-50 bg-white/5" : ""} ${dirty ? "bg-primary/5" : ""}`}
        >
            {/* Drag handle */}
            <button
                {...attributes}
                {...listeners}
                className="text-slate-600 hover:text-slate-400 cursor-grab active:cursor-grabbing shrink-0 touch-none"
                onClick={e => e.stopPropagation()}
            >
                <GripVertical size={14} />
            </button>

            {/* Name */}
            <button
                type="button"
                onClick={() => {
                    if (item.library) navigate(`/collections/${encodeURIComponent(item.library)}/${encodeURIComponent(item.title)}`);
                }}
                className="flex items-center gap-2 flex-1 min-w-0 text-left group/name"
            >
                {dirty && <span className="w-1.5 h-1.5 rounded-full bg-primary shrink-0" title="Unsaved" />}
                {item.is_pinned && <Pin size={11} className="text-primary fill-current shrink-0" />}
                <span className="text-sm text-slate-200 truncate group-hover/name:text-white transition-colors">
                    {item.title}
                </span>
            </button>

            {/* Visibility checkboxes — 64px cells to align with header labels */}
            <div className="flex items-center shrink-0">
                <div className="w-16 flex justify-center">
                    <VisibilityCheckbox
                        checked={item.promoted_to_own_home}
                        onChange={v => onVisibilityChange(v, item.promoted_to_shared, item.promoted_to_recommended)}
                    />
                </div>
                <div className="w-16 flex justify-center">
                    <VisibilityCheckbox
                        checked={item.promoted_to_shared}
                        onChange={v => onVisibilityChange(item.promoted_to_own_home, v, item.promoted_to_recommended)}
                    />
                </div>
                <div className="w-16 flex justify-center">
                    <VisibilityCheckbox
                        checked={item.promoted_to_recommended}
                        onChange={v => onVisibilityChange(item.promoted_to_own_home, item.promoted_to_shared, v)}
                    />
                </div>
            </div>
        </div>
    );
}

// ── LibrarySection ─────────────────────────────────────────────────────────

function LibrarySection({
    row,
    expanded,
    onToggleExpand,
    dirtyIds,
    onItemsReordered,
    onGroupVisibility,
    onIndividualVisibility,
}: {
    row: DashboardLibraryRow;
    expanded: boolean;
    onToggleExpand: () => void;
    dirtyIds: Set<string>;
    onItemsReordered: (libraryName: string, newItems: DashboardItem[]) => void;
    onGroupVisibility: (item: DashboardGroupItem, home: boolean, shared: boolean, rec: boolean) => void;
    onIndividualVisibility: (item: DashboardIndividualItem, home: boolean, shared: boolean, rec: boolean) => void;
}) {
    const sensors = useSensors(
        useSensor(PointerSensor, { activationConstraint: { distance: 8 } }),
        useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
    );

    const handleDragEnd = useCallback(async (event: DragEndEvent) => {
        const { active, over } = event;
        if (!over || active.id === over.id) return;

        const activeIdx = row.items.findIndex(i => itemId(i) === active.id);
        const overIdx = row.items.findIndex(i => itemId(i) === over.id);
        if (activeIdx === -1 || overIdx === -1) return;

        const reordered = arrayMove([...row.items], activeIdx, overIdx);
        onItemsReordered(row.name, reordered);

        const orderedRefs: CollectionRef[] = reordered.flatMap(item => {
            if (item.type === "group") {
                return item.active_collections
                    .filter(c => c.library)
                    .map(c => ({ library: c.library as string, name: c.title }));
            }
            return item.library ? [{ library: item.library, name: item.title }] : [];
        });

        try {
            const r = await fetchWithAuth("/api/collections/reorder", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ ordered_collections: orderedRefs }),
            });
            if (!r.ok) throw new Error("Reorder failed");
        } catch {
            onItemsReordered(row.name, row.items);
        }
    }, [row, onItemsReordered]);

    if (row.items.length === 0) return null;

    return (
        <div>
            {/* Section header */}
            <button
                type="button"
                onClick={onToggleExpand}
                className="w-full flex items-center gap-2 px-2 py-2 rounded-lg hover:bg-white/5 transition-colors group/header"
            >
                <ChevronRight
                    size={13}
                    className={`text-slate-500 transition-transform duration-150 shrink-0 ${expanded ? "rotate-90" : ""}`}
                />
                <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
                    {row.name}
                </span>
                <span className="text-xs text-slate-600 font-normal ml-1">{row.items.length}</span>
            </button>

            {/* Expanded rows */}
            {expanded && (
                <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={handleDragEnd}>
                    <SortableContext
                        items={row.items.map(itemId)}
                        strategy={verticalListSortingStrategy}
                    >
                        <div className="ml-5">
                            {row.items.map(item =>
                                item.type === "group" ? (
                                    <SortableGroupRow
                                        key={itemId(item)}
                                        item={item}
                                        onVisibilityChange={(h, s, r) => onGroupVisibility(item, h, s, r)}
                                        dirty={dirtyIds.has(itemId(item))}
                                    />
                                ) : (
                                    <SortableIndividualRow
                                        key={itemId(item)}
                                        item={item}
                                        onVisibilityChange={(h, s, r) => onIndividualVisibility(item, h, s, r)}
                                        dirty={dirtyIds.has(itemId(item))}
                                    />
                                )
                            )}
                        </div>
                    </SortableContext>
                </DndContext>
            )}
        </div>
    );
}

// ── ActiveCollectionsCard ──────────────────────────────────────────────────

export default function ActiveCollectionsCard({ refreshKey }: { refreshKey?: number }) {
    const { accent } = useTheme();
    const cinematic = accent === "plex-orange";

    const [libraries, setLibraries] = useState<DashboardLibraryRow[]>([]);
    const [loading, setLoading] = useState(true);
    const [expandedLibs, setExpandedLibs] = useState<Record<string, boolean>>({});
    const [pending, setPending] = useState<Record<string, { home: boolean; shared: boolean; rec: boolean; kind: "group" | "individual" }>>({});
    const [saving, setSaving] = useState(false);

    const fetchDashboard = useCallback(async () => {
        setLoading(true);
        try {
            const r = await fetchWithAuth("/api/collections/dashboard");
            if (!r.ok) throw new Error(`HTTP ${r.status}`);
            const data: DashboardCollectionsResponse = await r.json();
            setLibraries(data.libraries ?? []);
        } catch (e) {
            console.error("Failed to fetch dashboard collections:", e);
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        void fetchDashboard();
        setPending({});
    }, [fetchDashboard, refreshKey]);

    const handleItemsReordered = useCallback((libraryName: string, newItems: DashboardItem[]) => {
        setLibraries(prev =>
            prev.map(lib => lib.name === libraryName ? { ...lib, items: newItems } : lib)
        );
    }, []);

    // Merge pending edits over server state for rendering + counts
    const effectiveLibraries = useMemo(() => libraries.map(lib => ({
        ...lib,
        items: lib.items.map(i => {
            const p = pending[itemId(i)];
            if (!p) return i;
            return { ...i, promoted_to_own_home: p.home, promoted_to_shared: p.shared, promoted_to_recommended: p.rec };
        }),
    })), [libraries, pending]);

    const stagePending = useCallback((
        item: DashboardItem,
        home: boolean,
        shared: boolean,
        rec: boolean,
    ) => {
        const key = itemId(item);
        const original = {
            home: item.promoted_to_own_home,
            shared: item.promoted_to_shared,
            rec: item.promoted_to_recommended,
        };
        setPending(prev => {
            const next = { ...prev };
            // If toggling back to server state, drop the entry
            if (home === original.home && shared === original.shared && rec === original.rec) {
                delete next[key];
            } else {
                next[key] = { home, shared, rec, kind: item.type };
            }
            return next;
        });
    }, []);

    const handleGroupVisibility = useCallback((item: DashboardGroupItem, h: boolean, s: boolean, r: boolean) => {
        stagePending(item, h, s, r);
    }, [stagePending]);

    const handleIndividualVisibility = useCallback((item: DashboardIndividualItem, h: boolean, s: boolean, r: boolean) => {
        if (!item.library) return;
        stagePending(item, h, s, r);
    }, [stagePending]);

    const dirtyIds = useMemo(() => new Set(Object.keys(pending)), [pending]);
    const dirtyCount = dirtyIds.size;

    // Warn on browser tab close / refresh while changes are pending
    useEffect(() => {
        if (dirtyCount === 0) return;
        const handler = (e: BeforeUnloadEvent) => {
            e.preventDefault();
            e.returnValue = "";
        };
        window.addEventListener("beforeunload", handler);
        return () => window.removeEventListener("beforeunload", handler);
    }, [dirtyCount]);

    // Confirm on in-app navigation while changes are pending
    const blocker = useBlocker(dirtyCount > 0);
    useEffect(() => {
        if (blocker.state !== "blocked") return;
        const ok = window.confirm(
            `You have ${dirtyCount} unsaved change${dirtyCount === 1 ? "" : "s"} to active collections. Discard and continue?`
        );
        if (ok) {
            setPending({});
            blocker.proceed();
        } else {
            blocker.reset();
        }
    }, [blocker, dirtyCount]);

    const handleSave = useCallback(async () => {
        if (dirtyCount === 0) return;
        setSaving(true);
        try {
            // Find each pending change's source item and fire the right API
            const all = libraries.flatMap(lib => lib.items);
            const tasks = Object.entries(pending).map(async ([key, p]) => {
                const item = all.find(i => itemId(i) === key);
                if (!item) return;
                if (item.type === "group" && p.kind === "group") {
                    const r = await fetchWithAuth(`/api/admin/config/groups/${item.group_index}/visibility`, {
                        method: "PATCH",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ visibility_home: p.home, visibility_shared: p.shared, visibility_recommended: p.rec }),
                    });
                    if (!r.ok) throw new Error(`Group save failed: ${item.group_name}`);
                } else if (item.type === "individual" && p.kind === "individual" && item.library) {
                    const r = await fetchWithAuth("/api/collections/toggle-pin", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({
                            collection_name: item.title,
                            library: item.library,
                            home: p.home || undefined,
                            shared: p.shared || undefined,
                            recommended: p.rec || undefined,
                        }),
                    });
                    if (!r.ok) throw new Error(`Pin save failed: ${item.title}`);
                }
            });
            await Promise.all(tasks);
            setPending({});
            await fetchDashboard();
        } catch (e) {
            console.error("Save failed:", e);
        } finally {
            setSaving(false);
        }
    }, [pending, libraries, dirtyCount, fetchDashboard]);

    const handleCancel = useCallback(() => setPending({}), []);

    const toggleLib = useCallback((name: string) => {
        setExpandedLibs(prev => ({ ...prev, [name]: !prev[name] }));
    }, []);

    const expandAll = useCallback(() => {
        setExpandedLibs(Object.fromEntries(libraries.map(l => [l.name, true])));
    }, [libraries]);

    const collapseAll = useCallback(() => setExpandedLibs({}), []);

    const allExpanded = libraries.length > 0 && libraries.every(l => expandedLibs[l.name]);

    const counts = useMemo(() => {
        const all = effectiveLibraries.flatMap(lib => lib.items);
        return {
            all: all.length,
            my_home: all.filter(i => i.promoted_to_own_home).length,
            shared: all.filter(i => i.promoted_to_shared).length,
            recommended: all.filter(i => i.promoted_to_recommended).length,
        };
    }, [effectiveLibraries]);

    // Column headers — same 64px cells as checkbox rows
    const colHeaders = (
        <div className="flex items-center shrink-0 text-[10px] font-semibold text-slate-500 uppercase tracking-wider select-none">
            <span className="w-16 text-center">Home</span>
            <span className="w-16 text-center">Shared</span>
            <span className="w-16 text-center">Rec</span>
        </div>
    );

    return (
        <div className={cinematic ? "py-2" : "rounded-xl border border-primary/30 bg-gradient-to-br from-primary/5 via-slate-900/50 to-slate-900/50 shadow-lg shadow-primary/5 px-5 py-4 transition-all duration-300 hover:bg-slate-800/30"}>
            {/* Header */}
            <div className="flex items-start justify-between mb-3 gap-4">
                <div>
                    <h3 className="text-lg font-bold text-white tracking-tight">Active Collections</h3>
                    <p className="text-sm text-slate-400 mt-0.5">Currently featured on your Plex home screen</p>
                </div>
                {!loading && counts.all > 0 && (
                    <div className="text-xs text-slate-400 pt-1 shrink-0 tabular-nums">
                        <span className="text-slate-200 font-semibold">{counts.my_home}</span> on Home
                        <span className="text-slate-600 mx-2">·</span>
                        <span className="text-slate-200 font-semibold">{counts.shared}</span> Shared
                        <span className="text-slate-600 mx-2">·</span>
                        <span className="text-slate-200 font-semibold">{counts.recommended}</span> Rec
                        <span className="text-slate-600 mx-2">·</span>
                        <span className="text-slate-200 font-semibold">{counts.all}</span> Total
                    </div>
                )}
            </div>

            {/* Toolbar: expand/collapse all + save/cancel */}
            {!loading && libraries.length > 0 && (
                <div className="flex items-center justify-between mb-2 px-1">
                    <button
                        type="button"
                        onClick={allExpanded ? collapseAll : expandAll}
                        className="text-xs text-slate-400 hover:text-white transition-colors"
                    >
                        {allExpanded ? "Collapse all" : "Expand all"}
                    </button>
                    {dirtyCount > 0 && (
                        <div className="flex items-center gap-2">
                            <span className="text-xs text-slate-400 tabular-nums">
                                {dirtyCount} unsaved
                            </span>
                            <button
                                type="button"
                                onClick={handleCancel}
                                disabled={saving}
                                className="px-3 py-1 text-xs font-semibold rounded-md text-slate-300 hover:text-white hover:bg-white/5 transition-colors disabled:opacity-50"
                            >
                                Cancel
                            </button>
                            <button
                                type="button"
                                onClick={handleSave}
                                disabled={saving}
                                className="px-3 py-1 text-xs font-semibold rounded-md bg-primary text-white hover:bg-primary/90 transition-colors disabled:opacity-50"
                            >
                                {saving ? "Saving…" : "Save"}
                            </button>
                        </div>
                    )}
                </div>
            )}

            {loading ? (
                <div className="space-y-2">
                    {Array.from({ length: 4 }).map((_, i) => (
                        <div key={i} className="h-8 rounded-lg bg-slate-800/60 animate-pulse" />
                    ))}
                </div>
            ) : libraries.length === 0 ? (
                <div className="text-sm text-slate-400 py-4">No active collections yet.</div>
            ) : (
                <>
                    {/* Column headers — right-aligned to match checkbox columns */}
                    <div className="flex items-center justify-end mb-1 px-2">
                        {colHeaders}
                    </div>
                    <div className="space-y-0.5">
                        {effectiveLibraries.map(lib => (
                            <LibrarySection
                                key={lib.name}
                                row={lib}
                                expanded={!!expandedLibs[lib.name]}
                                onToggleExpand={() => toggleLib(lib.name)}
                                dirtyIds={dirtyIds}
                                onItemsReordered={handleItemsReordered}
                                onGroupVisibility={handleGroupVisibility}
                                onIndividualVisibility={handleIndividualVisibility}
                            />
                        ))}
                    </div>
                </>
            )}
        </div>
    );
}
