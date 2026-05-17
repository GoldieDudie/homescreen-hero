import React, { useCallback, useEffect, useMemo, useState } from "react";
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
import {
    GripVertical,
    Layers,
    Pin,
    ArrowUpToLine,
    ArrowDownToLine,
    X,
    RefreshCw,
    Loader2,
    AlertCircle,
    ChevronDown,
    ChevronRight,
    Tv,
    Film,
    Library,
} from "lucide-react";
import { Popover, PopoverTrigger, PopoverContent } from "./ui/popover";
import { fetchWithAuth } from "../utils/api";

// ── Types matching /api/libraries/{lib}/hubs ───────────────────────────────

type HubType = "collection" | "smart_hub" | "external";
type PinSlot = "top" | "bottom";

interface HubOut {
    title: string;
    position: number;
    hub_type: HubType;
    group_name: string | null;
    pin_position: PinSlot | null;
    promoted_to_own_home?: boolean | null;
    promoted_to_shared_home?: boolean | null;
    promoted_to_recommended?: boolean | null;
    visibility_editable: boolean;
}

interface LibraryHubsResponse {
    library_name: string;
    hubs: HubOut[];
}

interface SyncResponse extends LibraryHubsResponse {
    added: string[];
    removed: string[];
    plex_reorder_errors: string[];
}

interface BatchSaveResponse extends LibraryHubsResponse {
    plex_reorder_errors: string[];
    visibility_errors: string[];
}

interface LibraryConfig {
    name: string;
    enabled: boolean;
    type?: string;
}

// ── Block model (visual collapse of consecutive same-group hubs) ───────────

type HubBlock =
    | { kind: "single"; hub: HubOut }
    | { kind: "group"; groupName: string; hubs: HubOut[] };

function blockId(block: HubBlock, libraryName: string): string {
    return block.kind === "group"
        ? `lib::${libraryName}::group::${block.groupName}`
        : `lib::${libraryName}::hub::${block.hub.title}`;
}

function buildBlocks(hubs: HubOut[]): HubBlock[] {
    const result: HubBlock[] = [];
    let i = 0;
    while (i < hubs.length) {
        const hub = hubs[i];
        if (hub.group_name) {
            const groupName = hub.group_name;
            const groupHubs: HubOut[] = [];
            while (i < hubs.length && hubs[i].group_name === groupName) {
                groupHubs.push(hubs[i]);
                i++;
            }
            result.push({ kind: "group", groupName, hubs: groupHubs });
        } else {
            result.push({ kind: "single", hub });
            i++;
        }
    }
    return result;
}

function flattenBlocks(blocks: HubBlock[]): HubOut[] {
    const result: HubOut[] = [];
    for (const block of blocks) {
        if (block.kind === "group") {
            result.push(...block.hubs);
        } else {
            result.push(block.hub);
        }
    }
    // Renumber positions
    return result.map((h, idx) => ({ ...h, position: idx }));
}

// ── Dirty detection ────────────────────────────────────────────────────────

function isDirty(initial: HubOut[], current: HubOut[]): boolean {
    if (initial.length !== current.length) return true;
    for (let i = 0; i < current.length; i++) {
        const a = initial[i];
        const b = current[i];
        if (a.title !== b.title) return true;
        if (a.pin_position !== b.pin_position) return true;
        if ((a.promoted_to_own_home ?? false) !== (b.promoted_to_own_home ?? false)) return true;
        if ((a.promoted_to_shared_home ?? false) !== (b.promoted_to_shared_home ?? false)) return true;
        if ((a.promoted_to_recommended ?? false) !== (b.promoted_to_recommended ?? false)) return true;
    }
    return false;
}

// ── Per-hub UI primitives ──────────────────────────────────────────────────

function VisibilityCheckbox({
    checked,
    onChange,
    disabled,
    title,
}: {
    checked: boolean;
    onChange: (v: boolean) => void;
    disabled?: boolean;
    title?: string;
}) {
    return (
        <button
            type="button"
            disabled={disabled}
            title={title}
            onClick={() => onChange(!checked)}
            className={`w-4 h-4 rounded border flex items-center justify-center transition-colors shrink-0 ${
                checked
                    ? "bg-primary border-primary"
                    : "bg-transparent border-slate-600 hover:border-slate-400"
            } ${disabled ? "opacity-40 cursor-not-allowed" : "cursor-pointer"}`}
        >
            {checked && (
                <svg viewBox="0 0 10 8" className="w-2.5 h-2 fill-white">
                    <path d="M1 4l3 3 5-6" stroke="white" strokeWidth="1.5" fill="none" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
            )}
        </button>
    );
}

function PinControl({
    pinned,
    canPinTop,
    canPinBottom,
    onSetPin,
    onUnpin,
}: {
    pinned: PinSlot | null;
    canPinTop: boolean;
    canPinBottom: boolean;
    onSetPin: (p: PinSlot) => void;
    onUnpin: () => void;
}) {
    const [open, setOpen] = useState(false);
    const apply = (fn: () => void) => {
        fn();
        setOpen(false);
    };
    const icon = pinned === "bottom"
        ? <ArrowDownToLine size={10} className="ml-0.5" />
        : pinned === "top"
        ? <ArrowUpToLine size={10} className="ml-0.5" />
        : null;
    return (
        <Popover open={open} onOpenChange={setOpen}>
            <PopoverTrigger asChild>
                <button
                    type="button"
                    title={pinned ? `Pinned to ${pinned}` : "Pin"}
                    onClick={(e) => e.stopPropagation()}
                    className={`shrink-0 flex items-center px-1 py-0.5 rounded hover:bg-white/5 ${
                        pinned ? "text-primary" : "text-slate-600 hover:text-slate-400"
                    }`}
                >
                    <Pin size={11} className={pinned ? "fill-current" : ""} />
                    {icon}
                </button>
            </PopoverTrigger>
            <PopoverContent
                align="start"
                className="w-44 p-1 bg-slate-900/95 backdrop-blur-md border-slate-700/60"
                onClick={(e) => e.stopPropagation()}
            >
                <button
                    type="button"
                    disabled={pinned === "top" || !canPinTop}
                    onClick={() => apply(() => onSetPin("top"))}
                    title={!canPinTop && pinned !== "top" ? "Top slot already in use" : ""}
                    className="w-full flex items-center gap-2 px-2 py-1.5 rounded text-xs text-slate-200 hover:bg-white/5 disabled:opacity-40 disabled:cursor-default"
                >
                    <ArrowUpToLine size={12} className="text-slate-400" />
                    Pin to top
                </button>
                <button
                    type="button"
                    disabled={pinned === "bottom" || !canPinBottom}
                    onClick={() => apply(() => onSetPin("bottom"))}
                    title={!canPinBottom && pinned !== "bottom" ? "Bottom slot already in use" : ""}
                    className="w-full flex items-center gap-2 px-2 py-1.5 rounded text-xs text-slate-200 hover:bg-white/5 disabled:opacity-40 disabled:cursor-default"
                >
                    <ArrowDownToLine size={12} className="text-slate-400" />
                    Pin to bottom
                </button>
                {pinned && (
                    <>
                        <div className="my-1 border-t border-slate-700/40" />
                        <button
                            type="button"
                            onClick={() => apply(onUnpin)}
                            className="w-full flex items-center gap-2 px-2 py-1.5 rounded text-xs text-rose-300 hover:bg-rose-500/10"
                        >
                            <X size={12} />
                            Unpin
                        </button>
                    </>
                )}
            </PopoverContent>
        </Popover>
    );
}

// ── Single hub row (used inside both single and group blocks) ──────────────

function HubRow({
    hub,
    canPinTop,
    canPinBottom,
    onSetPin,
    onUnpin,
    onVisibilityChange,
    isGrouped,
}: {
    hub: HubOut;
    canPinTop: boolean;
    canPinBottom: boolean;
    onSetPin: (p: PinSlot) => void;
    onUnpin: () => void;
    onVisibilityChange: (home: boolean, shared: boolean, recommended: boolean) => void;
    isGrouped: boolean;
}) {
    const typeBadge =
        hub.hub_type === "smart_hub"
            ? <span className="text-[9px] px-1 py-0.5 rounded bg-amber-500/10 text-amber-300 uppercase">Plex Smart</span>
            : hub.hub_type === "external"
            ? <span className="text-[9px] px-1 py-0.5 rounded bg-slate-500/10 text-slate-300 uppercase">Plex</span>
            : null;

    return (
        <div className="flex items-center gap-3 px-2 py-1.5 text-sm">
            {isGrouped && <span className="w-3 shrink-0" />}
            <span className="flex items-center gap-2 flex-1 min-w-0">
                <span className="text-slate-200 truncate">{hub.title}</span>
                {typeBadge}
            </span>

            {/* Visibility */}
            <div className="flex items-center shrink-0">
                <div className="w-16 flex justify-center">
                    <VisibilityCheckbox
                        checked={!!hub.promoted_to_recommended}
                        onChange={(v) => onVisibilityChange(!!hub.promoted_to_own_home, !!hub.promoted_to_shared_home, v)}
                        disabled={!hub.visibility_editable}
                        title={hub.visibility_editable ? "Library Recommended" : "Set via group config"}
                    />
                </div>
                <div className="w-16 flex justify-center">
                    <VisibilityCheckbox
                        checked={!!hub.promoted_to_own_home}
                        onChange={(v) => onVisibilityChange(v, !!hub.promoted_to_shared_home, !!hub.promoted_to_recommended)}
                        disabled={!hub.visibility_editable}
                        title={hub.visibility_editable ? "Home" : "Set via group config"}
                    />
                </div>
                <div className="w-16 flex justify-center">
                    <VisibilityCheckbox
                        checked={!!hub.promoted_to_shared_home}
                        onChange={(v) => onVisibilityChange(!!hub.promoted_to_own_home, v, !!hub.promoted_to_recommended)}
                        disabled={!hub.visibility_editable}
                        title={hub.visibility_editable ? "Friends' Home" : "Set via group config"}
                    />
                </div>
            </div>

            {/* Pin */}
            <div className="w-10 flex justify-center shrink-0">
                <PinControl
                    pinned={hub.pin_position}
                    canPinTop={canPinTop}
                    canPinBottom={canPinBottom}
                    onSetPin={onSetPin}
                    onUnpin={onUnpin}
                />
            </div>
        </div>
    );
}

// ── Sortable block (group or single) ───────────────────────────────────────

function SortableBlock({
    block,
    libraryName,
    pinSlots,
    onSetPin,
    onUnpin,
    onVisibilityChange,
    expandedGroups,
    setGroupExpanded,
    dirty,
}: {
    block: HubBlock;
    libraryName: string;
    pinSlots: { top: string | null; bottom: string | null };
    onSetPin: (hubTitle: string, slot: PinSlot) => void;
    onUnpin: (hubTitle: string) => void;
    onVisibilityChange: (
        hubTitle: string,
        home: boolean,
        shared: boolean,
        recommended: boolean,
    ) => void;
    expandedGroups: Set<string>;
    setGroupExpanded: (groupName: string, expanded: boolean) => void;
    dirty: boolean;
}) {
    const id = blockId(block, libraryName);
    const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id });

    const style = {
        transform: CSS.Transform.toString(transform),
        transition: transition ?? "transform 150ms ease",
    };

    if (block.kind === "group") {
        const expanded = expandedGroups.has(block.groupName);
        const memberCount = block.hubs.length;
        const titles = block.hubs.map((h) => h.title).join(" · ");
        return (
            <div
                ref={setNodeRef}
                style={style}
                className={`rounded-lg border border-slate-800/60 ${isDragging ? "opacity-50" : ""} ${dirty ? "bg-primary/5" : ""}`}
            >
                <div className="flex items-center gap-3 px-2 py-2 hover:bg-white/5 rounded-t-lg">
                    <button
                        {...attributes}
                        {...listeners}
                        className="text-slate-600 hover:text-slate-400 cursor-grab active:cursor-grabbing shrink-0 touch-none"
                        onClick={(e) => e.stopPropagation()}
                        aria-label="Drag group"
                    >
                        <GripVertical size={14} />
                    </button>
                    <button
                        type="button"
                        onClick={() => setGroupExpanded(block.groupName, !expanded)}
                        className="text-slate-500 hover:text-slate-300 shrink-0"
                        aria-label={expanded ? "Collapse" : "Expand"}
                    >
                        {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                    </button>
                    <Layers size={13} className="text-slate-500 shrink-0" />
                    <span className="text-sm text-slate-200 truncate flex-1 min-w-0">
                        {block.groupName}
                        <span className="ml-2 text-[10px] text-slate-500">({memberCount})</span>
                    </span>
                    {!expanded && (
                        <span className="text-[10px] text-slate-500 truncate hidden sm:block flex-1 min-w-0">
                            {titles}
                        </span>
                    )}
                </div>
                {expanded && (
                    <div className="pl-6 border-t border-slate-800/40">
                        {block.hubs.map((hub) => (
                            <HubRow
                                key={hub.title}
                                hub={hub}
                                canPinTop={pinSlots.top === null || pinSlots.top === hub.title}
                                canPinBottom={pinSlots.bottom === null || pinSlots.bottom === hub.title}
                                onSetPin={(slot) => onSetPin(hub.title, slot)}
                                onUnpin={() => onUnpin(hub.title)}
                                onVisibilityChange={(h, s, r) => onVisibilityChange(hub.title, h, s, r)}
                                isGrouped
                            />
                        ))}
                    </div>
                )}
            </div>
        );
    }

    const hub = block.hub;
    const isTopPin = hub.pin_position === "top";
    const isBottomPin = hub.pin_position === "bottom";
    return (
        <div
            ref={setNodeRef}
            style={style}
            className={`flex items-center gap-3 px-2 py-2 rounded-lg hover:bg-white/5 transition-colors ${isDragging ? "opacity-50 bg-white/5" : ""} ${dirty ? "bg-primary/5" : ""} ${isBottomPin ? "bg-slate-800/30" : ""} ${isTopPin ? "bg-primary/5" : ""}`}
        >
            <button
                {...attributes}
                {...listeners}
                className="text-slate-600 hover:text-slate-400 cursor-grab active:cursor-grabbing shrink-0 touch-none"
                onClick={(e) => e.stopPropagation()}
                aria-label="Drag hub"
            >
                <GripVertical size={14} />
            </button>
            <HubRow
                hub={hub}
                canPinTop={pinSlots.top === null || pinSlots.top === hub.title}
                canPinBottom={pinSlots.bottom === null || pinSlots.bottom === hub.title}
                onSetPin={(slot) => onSetPin(hub.title, slot)}
                onUnpin={() => onUnpin(hub.title)}
                onVisibilityChange={(h, s, r) => onVisibilityChange(hub.title, h, s, r)}
                isGrouped={false}
            />
        </div>
    );
}

// ── Per-library section ────────────────────────────────────────────────────

function libraryIcon(type?: string) {
    if (type === "show") return <Tv size={14} className="text-slate-400" />;
    if (type === "movie") return <Film size={14} className="text-slate-400" />;
    return <Library size={14} className="text-slate-400" />;
}

function LibrarySection({
    libraryName,
    initialHubs,
    onSaved,
}: {
    libraryName: string;
    initialHubs: HubOut[];
    onSaved: (hubs: HubOut[]) => void;
}) {
    const [hubs, setHubs] = useState<HubOut[]>(initialHubs);
    const [saving, setSaving] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [expandedGroups, setExpandedGroups] = useState<Set<string>>(new Set());

    useEffect(() => {
        setHubs(initialHubs);
    }, [initialHubs]);

    const sensors = useSensors(
        useSensor(PointerSensor, { activationConstraint: { distance: 4 } }),
        useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
    );

    const blocks = useMemo(() => buildBlocks(hubs), [hubs]);
    const blockIds = blocks.map((b) => blockId(b, libraryName));
    const dirty = isDirty(initialHubs, hubs);

    const pinSlots = useMemo(() => {
        const top = hubs.find((h) => h.pin_position === "top")?.title ?? null;
        const bottom = hubs.find((h) => h.pin_position === "bottom")?.title ?? null;
        return { top, bottom };
    }, [hubs]);

    const handleDragEnd = useCallback(
        (event: DragEndEvent) => {
            const { active, over } = event;
            if (!over || active.id === over.id) return;
            const oldIndex = blockIds.indexOf(String(active.id));
            const newIndex = blockIds.indexOf(String(over.id));
            if (oldIndex < 0 || newIndex < 0) return;
            const newBlocks = arrayMove(blocks, oldIndex, newIndex);
            setHubs(flattenBlocks(newBlocks));
        },
        [blocks, blockIds],
    );

    const setGroupExpanded = useCallback((groupName: string, expanded: boolean) => {
        setExpandedGroups((prev) => {
            const next = new Set(prev);
            if (expanded) next.add(groupName);
            else next.delete(groupName);
            return next;
        });
    }, []);

    const setPin = useCallback((hubTitle: string, slot: PinSlot) => {
        setHubs((prev) =>
            prev.map((h) => {
                if (h.title === hubTitle) return { ...h, pin_position: slot };
                // Evict any other hub in the same slot
                if (h.pin_position === slot) return { ...h, pin_position: null };
                return h;
            }),
        );
    }, []);

    const unpin = useCallback((hubTitle: string) => {
        setHubs((prev) => prev.map((h) => (h.title === hubTitle ? { ...h, pin_position: null } : h)));
    }, []);

    const changeVisibility = useCallback(
        (hubTitle: string, home: boolean, shared: boolean, recommended: boolean) => {
            setHubs((prev) =>
                prev.map((h) =>
                    h.title === hubTitle
                        ? {
                              ...h,
                              promoted_to_own_home: home,
                              promoted_to_shared_home: shared,
                              promoted_to_recommended: recommended,
                          }
                        : h,
                ),
            );
        },
        [],
    );

    const handleCancel = useCallback(() => {
        setHubs(initialHubs);
    }, [initialHubs]);

    const handleSave = useCallback(async () => {
        setSaving(true);
        setError(null);
        try {
            // Diff visibility for change list
            const initialByTitle = new Map(initialHubs.map((h) => [h.title, h]));
            const visibility_changes = hubs
                .filter((h) => h.visibility_editable)
                .filter((h) => {
                    const init = initialByTitle.get(h.title);
                    if (!init) return false;
                    return (
                        (init.promoted_to_own_home ?? false) !== (h.promoted_to_own_home ?? false) ||
                        (init.promoted_to_shared_home ?? false) !== (h.promoted_to_shared_home ?? false) ||
                        (init.promoted_to_recommended ?? false) !== (h.promoted_to_recommended ?? false)
                    );
                })
                .map((h) => ({
                    hub_title: h.title,
                    home: !!h.promoted_to_own_home,
                    shared: !!h.promoted_to_shared_home,
                    recommended: !!h.promoted_to_recommended,
                }));

            const body = {
                ordered_hub_titles: hubs.map((h) => h.title),
                pins: {
                    top: pinSlots.top,
                    bottom: pinSlots.bottom,
                },
                visibility_changes,
            };

            const res = await fetchWithAuth(
                `/api/libraries/${encodeURIComponent(libraryName)}/hubs/batch`,
                {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify(body),
                },
            );
            if (!res.ok) {
                const txt = await res.text();
                throw new Error(`Save failed: ${res.status} ${txt}`);
            }
            const data: BatchSaveResponse = await res.json();
            const combinedErrors = [...(data.plex_reorder_errors ?? []), ...(data.visibility_errors ?? [])];
            if (combinedErrors.length > 0) {
                setError(combinedErrors.join("; "));
            }
            onSaved(data.hubs);
            setHubs(data.hubs);
        } catch (e: any) {
            setError(e?.message ?? String(e));
        } finally {
            setSaving(false);
        }
    }, [hubs, initialHubs, pinSlots, libraryName, onSaved]);

    return (
        <div className={`rounded-xl border ${dirty ? "border-primary/40" : "border-slate-800/60"} bg-slate-950/40`}>
            {/* Library header */}
            <div className="flex items-center gap-2 px-3 py-2 border-b border-slate-800/40">
                {libraryIcon()}
                <h3 className="text-sm font-medium text-slate-200 flex-1">{libraryName}</h3>
                <span className="text-[10px] text-slate-500">{hubs.length} hubs</span>
            </div>

            {/* Column headers */}
            <div className="flex items-center gap-3 px-2 py-1.5 text-[10px] text-slate-500 uppercase tracking-wide">
                <span className="w-4 shrink-0" />
                <span className="flex-1 min-w-0" />
                <div className="flex items-center shrink-0">
                    <div className="w-16 flex justify-center">Library Rec.</div>
                    <div className="w-16 flex justify-center">Home</div>
                    <div className="w-16 flex justify-center">Friends'</div>
                </div>
                <div className="w-10 flex justify-center shrink-0">Pin</div>
            </div>

            {/* Hub list */}
            <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={handleDragEnd}>
                <SortableContext items={blockIds} strategy={verticalListSortingStrategy}>
                    <div className="px-1 pb-1 space-y-1">
                        {blocks.map((block) => (
                            <SortableBlock
                                key={blockId(block, libraryName)}
                                block={block}
                                libraryName={libraryName}
                                pinSlots={pinSlots}
                                onSetPin={setPin}
                                onUnpin={unpin}
                                onVisibilityChange={changeVisibility}
                                expandedGroups={expandedGroups}
                                setGroupExpanded={setGroupExpanded}
                                dirty={dirty}
                            />
                        ))}
                    </div>
                </SortableContext>
            </DndContext>

            {/* Save/cancel footer */}
            {(dirty || error) && (
                <div className="flex items-center gap-3 px-3 py-2 border-t border-slate-800/40 bg-slate-900/60">
                    {error && (
                        <div className="flex items-center gap-1.5 text-xs text-rose-300 flex-1 min-w-0">
                            <AlertCircle size={12} />
                            <span className="truncate" title={error}>{error}</span>
                        </div>
                    )}
                    {!error && dirty && (
                        <div className="text-xs text-primary flex-1">Unsaved changes</div>
                    )}
                    <button
                        type="button"
                        onClick={handleCancel}
                        disabled={saving}
                        className="text-xs px-3 py-1 rounded border border-slate-700 hover:bg-white/5 text-slate-300 disabled:opacity-40"
                    >
                        Cancel
                    </button>
                    <button
                        type="button"
                        onClick={handleSave}
                        disabled={saving || !dirty}
                        className="text-xs px-3 py-1 rounded bg-primary hover:bg-primary/90 text-white disabled:opacity-40 flex items-center gap-1.5"
                    >
                        {saving && <Loader2 size={12} className="animate-spin" />}
                        Save
                    </button>
                </div>
            )}
        </div>
    );
}

// ── Top-level card ─────────────────────────────────────────────────────────

interface LibraryHubsCardProps {
    refreshKey?: number;
}

export default function LibraryHubsCard({ refreshKey }: LibraryHubsCardProps) {
    const [libraries, setLibraries] = useState<LibraryConfig[]>([]);
    const [hubsByLibrary, setHubsByLibrary] = useState<Record<string, HubOut[]>>({});
    const [loading, setLoading] = useState(true);
    const [syncing, setSyncing] = useState<string | null>(null);
    const [error, setError] = useState<string | null>(null);

    const loadLibraries = useCallback(async () => {
        try {
            const res = await fetchWithAuth("/api/libraries");
            if (!res.ok) throw new Error(`Failed to list libraries: ${res.status}`);
            const data = await res.json();
            const libs: LibraryConfig[] = (data.libraries ?? []).map((l: any) => ({
                name: l.name,
                enabled: l.enabled ?? true,
                type: l.type ?? undefined,
            }));
            return libs.filter((l) => l.enabled);
        } catch (e: any) {
            throw new Error(`Could not load library list: ${e?.message ?? e}`);
        }
    }, []);

    const loadOrSync = useCallback(async (libName: string): Promise<HubOut[]> => {
        // Try DB read first; if empty, run sync
        const getRes = await fetchWithAuth(
            `/api/libraries/${encodeURIComponent(libName)}/hubs`,
        );
        if (!getRes.ok) {
            const t = await getRes.text();
            throw new Error(`GET hubs failed for ${libName}: ${getRes.status} ${t}`);
        }
        const getData: LibraryHubsResponse = await getRes.json();
        if (getData.hubs.length > 0) {
            // Hydrate visibility flags via /sync (DB doesn't track them)
            const syncRes = await fetchWithAuth(
                `/api/libraries/${encodeURIComponent(libName)}/hubs/sync`,
                { method: "POST" },
            );
            if (!syncRes.ok) {
                // Fall back to DB-only data
                return getData.hubs;
            }
            const syncData: SyncResponse = await syncRes.json();
            return syncData.hubs;
        }
        // Empty DB — run sync to populate
        const syncRes = await fetchWithAuth(
            `/api/libraries/${encodeURIComponent(libName)}/hubs/sync`,
            { method: "POST" },
        );
        if (!syncRes.ok) {
            const t = await syncRes.text();
            throw new Error(`Sync failed for ${libName}: ${syncRes.status} ${t}`);
        }
        const syncData: SyncResponse = await syncRes.json();
        return syncData.hubs;
    }, []);

    const refresh = useCallback(async () => {
        setLoading(true);
        setError(null);
        try {
            const libs = await loadLibraries();
            setLibraries(libs);
            const results = await Promise.all(
                libs.map(async (lib) => {
                    try {
                        const hubs = await loadOrSync(lib.name);
                        return [lib.name, hubs] as const;
                    } catch (e: any) {
                        console.warn(`Failed to load hubs for ${lib.name}:`, e);
                        return [lib.name, [] as HubOut[]] as const;
                    }
                }),
            );
            const byLib: Record<string, HubOut[]> = {};
            for (const [name, hubs] of results) {
                byLib[name] = hubs;
            }
            setHubsByLibrary(byLib);
        } catch (e: any) {
            setError(e?.message ?? String(e));
        } finally {
            setLoading(false);
        }
    }, [loadLibraries, loadOrSync]);

    useEffect(() => {
        refresh();
    }, [refresh, refreshKey]);

    const handleManualSync = useCallback(
        async (libName: string) => {
            setSyncing(libName);
            try {
                const res = await fetchWithAuth(
                    `/api/libraries/${encodeURIComponent(libName)}/hubs/sync`,
                    { method: "POST" },
                );
                if (!res.ok) throw new Error(`Sync failed: ${res.status}`);
                const data: SyncResponse = await res.json();
                setHubsByLibrary((prev) => ({ ...prev, [libName]: data.hubs }));
            } catch (e: any) {
                console.error(e);
            } finally {
                setSyncing(null);
            }
        },
        [],
    );

    return (
        <div className="rounded-2xl border border-slate-800/60 bg-slate-950/40 backdrop-blur-sm">
            <div className="flex items-center justify-between gap-3 px-4 py-3 border-b border-slate-800/40">
                <div>
                    <h2 className="text-sm font-medium text-slate-100">Active Collections</h2>
                    <p className="text-[11px] text-slate-500">Per-library hub order. Drag to reorder.</p>
                </div>
                <button
                    type="button"
                    onClick={refresh}
                    disabled={loading}
                    className="text-xs flex items-center gap-1.5 px-2 py-1 rounded border border-slate-700 hover:bg-white/5 text-slate-300 disabled:opacity-40"
                >
                    {loading ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />}
                    Refresh
                </button>
            </div>

            {error && (
                <div className="px-4 py-2 text-xs text-rose-300 bg-rose-500/10 border-b border-rose-500/20 flex items-center gap-2">
                    <AlertCircle size={12} />
                    {error}
                </div>
            )}

            <div className="p-3 space-y-3">
                {loading && libraries.length === 0 && (
                    <div className="flex items-center justify-center py-8 text-xs text-slate-500">
                        <Loader2 size={14} className="animate-spin mr-2" /> Loading hubs from Plex…
                    </div>
                )}
                {libraries.map((lib) => (
                    <LibrarySection
                        key={lib.name}
                        libraryName={lib.name}
                        initialHubs={hubsByLibrary[lib.name] ?? []}
                        onSaved={(hubs) =>
                            setHubsByLibrary((prev) => ({ ...prev, [lib.name]: hubs }))
                        }
                    />
                ))}
                {!loading && libraries.length === 0 && (
                    <div className="text-xs text-slate-500 text-center py-6">No enabled libraries configured.</div>
                )}
            </div>
        </div>
    );
}
