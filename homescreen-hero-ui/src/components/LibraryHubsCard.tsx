import { useCallback, useEffect, useMemo, useRef, useState } from "react";
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
    EyeOff,
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
    // Collapse only CONSECUTIVE same-group hubs (Plex order may scatter members).
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
        if (block.kind === "group") result.push(...block.hubs);
        else result.push(block.hub);
    }
    return result.map((h, idx) => ({ ...h, position: idx }));
}

// ── Layout constants (shared between header + rows for column alignment) ───

const COL_W = "w-16";
const PIN_W = "w-10";
const GRIP_W = "w-[18px]"; // GripVertical icon (14px) + tight padding

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
    disabled,
    disabledReason,
    onSetPin,
    onUnpin,
}: {
    pinned: PinSlot | null;
    canPinTop: boolean;
    canPinBottom: boolean;
    disabled?: boolean;
    disabledReason?: string;
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
    if (disabled) {
        return (
            <button
                type="button"
                disabled
                title={disabledReason || "Pin not available"}
                className="shrink-0 flex items-center px-1 py-0.5 rounded text-slate-700 cursor-not-allowed opacity-40"
            >
                <Pin size={11} />
            </button>
        );
    }
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

// ── Single hub row ─────────────────────────────────────────────────────────

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
            ? <span className="text-[9px] px-1 py-0.5 rounded bg-amber-500/10 text-amber-300 uppercase" title="Plex smart hub (Recently Added, Top Rated, etc.) — non-deletable">Plex Smart</span>
            : hub.hub_type === "external"
            ? <span className="text-[9px] px-1 py-0.5 rounded bg-slate-500/10 text-slate-300 uppercase" title="External hub not managed by HSH">Plex</span>
            : null;

    // HSH-managed collections (hub_type=collection) are pinned/visible via group config;
    // dashboard pin button is disabled to avoid confusing per-collection overrides.
    const pinDisabled = hub.hub_type === "collection";
    const pinDisabledReason = pinDisabled
        ? "Pin via the group's settings (HSH-managed collection)"
        : undefined;

    return (
        <div className="flex items-center gap-3 px-2 py-1.5 text-sm">
            {isGrouped && <span className="w-3 shrink-0" />}
            <span className="flex items-center gap-2 flex-1 min-w-0">
                <span className="text-slate-200 truncate">{hub.title}</span>
                {typeBadge}
            </span>

            <div className="flex items-center shrink-0">
                <div className={`${COL_W} flex justify-center`}>
                    <VisibilityCheckbox
                        checked={!!hub.promoted_to_recommended}
                        onChange={(v) => onVisibilityChange(!!hub.promoted_to_own_home, !!hub.promoted_to_shared_home, v)}
                        disabled={!hub.visibility_editable}
                        title={hub.visibility_editable ? "Library Recommended" : "Set via group config"}
                    />
                </div>
                <div className={`${COL_W} flex justify-center`}>
                    <VisibilityCheckbox
                        checked={!!hub.promoted_to_own_home}
                        onChange={(v) => onVisibilityChange(v, !!hub.promoted_to_shared_home, !!hub.promoted_to_recommended)}
                        disabled={!hub.visibility_editable}
                        title={hub.visibility_editable ? "Home" : "Set via group config"}
                    />
                </div>
                <div className={`${COL_W} flex justify-center`}>
                    <VisibilityCheckbox
                        checked={!!hub.promoted_to_shared_home}
                        onChange={(v) => onVisibilityChange(!!hub.promoted_to_own_home, v, !!hub.promoted_to_recommended)}
                        disabled={!hub.visibility_editable}
                        title={hub.visibility_editable ? "Friends' Home" : "Set via group config"}
                    />
                </div>
            </div>

            <div className={`${PIN_W} flex justify-center shrink-0`}>
                <PinControl
                    pinned={hub.pin_position}
                    canPinTop={canPinTop}
                    canPinBottom={canPinBottom}
                    disabled={pinDisabled}
                    disabledReason={pinDisabledReason}
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
    pending,
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
    pending: boolean;
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
                className={`rounded-lg border border-slate-800/60 ${isDragging ? "opacity-50" : ""} ${pending ? "bg-primary/5" : ""}`}
            >
                <div className="flex items-center gap-3 px-2 py-2 hover:bg-white/5 rounded-t-lg">
                    <button
                        {...attributes}
                        {...listeners}
                        className={`${GRIP_W} text-slate-600 hover:text-slate-400 cursor-grab active:cursor-grabbing shrink-0 touch-none flex justify-center`}
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
            className={`flex items-center gap-3 px-2 rounded-lg hover:bg-white/5 transition-colors ${isDragging ? "opacity-50 bg-white/5" : ""} ${pending ? "bg-primary/5" : ""} ${isBottomPin ? "bg-slate-800/30" : ""} ${isTopPin ? "bg-primary/5" : ""}`}
        >
            <button
                {...attributes}
                {...listeners}
                className={`${GRIP_W} text-slate-600 hover:text-slate-400 cursor-grab active:cursor-grabbing shrink-0 touch-none flex justify-center`}
                onClick={(e) => e.stopPropagation()}
                aria-label="Drag hub"
            >
                <GripVertical size={14} />
            </button>
            <div className="flex-1 min-w-0">
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
        </div>
    );
}

// ── Per-library section ────────────────────────────────────────────────────

function libraryIcon(type?: string) {
    if (type === "show") return <Tv size={14} className="text-slate-400" />;
    if (type === "movie") return <Film size={14} className="text-slate-400" />;
    return <Library size={14} className="text-slate-400" />;
}

// Push a small delay between chained moves so Plex's server has time to settle
// before the next PUT lands. Per the API investigation, rapid chained moves are
// where the server starts re-normalizing — short sleeps mitigate but don't
// eliminate that risk. Group drags use one sleep per member.
const MOVE_CHAIN_DELAY_MS = 250;

function sleep(ms: number): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms));
}

type ActionState = "idle" | "saving" | "error";

function LibrarySection({
    libraryName,
    libraryType,
    initialHubs,
    hideUnused,
    onHubsUpdated,
}: {
    libraryName: string;
    libraryType?: string;
    initialHubs: HubOut[];
    hideUnused: boolean;
    onHubsUpdated: (hubs: HubOut[]) => void;
}) {
    const [hubs, setHubs] = useState<HubOut[]>(initialHubs);
    const [actionState, setActionState] = useState<ActionState>("idle");
    const [errorMsg, setErrorMsg] = useState<string | null>(null);
    const [expandedGroups, setExpandedGroups] = useState<Set<string>>(new Set());
    const [pendingTitles, setPendingTitles] = useState<Set<string>>(new Set());

    // Keep latest hubs accessible inside async closures without stale-closure issues.
    const hubsRef = useRef(hubs);
    hubsRef.current = hubs;

    useEffect(() => {
        setHubs(initialHubs);
    }, [initialHubs]);

    const sensors = useSensors(
        useSensor(PointerSensor, { activationConstraint: { distance: 4 } }),
        useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
    );

    const visibleHubs = useMemo(() => {
        if (!hideUnused) return hubs;
        return hubs.filter((h) => {
            const anyOn =
                !!h.promoted_to_own_home ||
                !!h.promoted_to_shared_home ||
                !!h.promoted_to_recommended;
            // Always keep HSH-managed and pinned hubs visible so the user can see structure;
            // only hide truly-inert external/smart hubs.
            if (h.hub_type === "collection") return true;
            if (h.pin_position) return true;
            return anyOn;
        });
    }, [hubs, hideUnused]);

    const blocks = useMemo(() => buildBlocks(visibleHubs), [visibleHubs]);
    const blockIds = blocks.map((b) => blockId(b, libraryName));

    const pinSlots = useMemo(() => {
        const top = hubs.find((h) => h.pin_position === "top")?.title ?? null;
        const bottom = hubs.find((h) => h.pin_position === "bottom")?.title ?? null;
        return { top, bottom };
    }, [hubs]);

    const markPending = useCallback((titles: string[], on: boolean) => {
        setPendingTitles((prev) => {
            const next = new Set(prev);
            for (const t of titles) {
                if (on) next.add(t);
                else next.delete(t);
            }
            return next;
        });
    }, []);

    const setGroupExpanded = useCallback((groupName: string, expanded: boolean) => {
        setExpandedGroups((prev) => {
            const next = new Set(prev);
            if (expanded) next.add(groupName);
            else next.delete(groupName);
            return next;
        });
    }, []);

    // ── Single move helper (one PUT per call; chained group moves use sleep) ──

    const sendMove = useCallback(
        async (hubTitle: string, afterHubTitle: string | null): Promise<string | null> => {
            const res = await fetchWithAuth(
                `/api/libraries/${encodeURIComponent(libraryName)}/hubs/move`,
                {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        hub_title: hubTitle,
                        after_hub_title: afterHubTitle,
                    }),
                },
            );
            if (!res.ok) {
                const t = await res.text();
                return `Move failed (${res.status}): ${t}`;
            }
            const data = await res.json();
            return data.error ?? null;
        },
        [libraryName],
    );

    const handleDragEnd = useCallback(
        async (event: DragEndEvent) => {
            const { active, over } = event;
            if (!over || active.id === over.id) return;
            const oldIndex = blockIds.indexOf(String(active.id));
            const newIndex = blockIds.indexOf(String(over.id));
            if (oldIndex < 0 || newIndex < 0) return;

            const newBlocks = arrayMove(blocks, oldIndex, newIndex);
            const draggedBlock = blocks[oldIndex];
            const movedTitles =
                draggedBlock.kind === "group"
                    ? draggedBlock.hubs.map((h) => h.title)
                    : [draggedBlock.hub.title];

            // Compute anchor: the hub title that should be IMMEDIATELY before the
            // dragged block's first hub in the new order. Null = move to top.
            const flatNew = flattenBlocks(newBlocks);
            const firstMovedTitle = movedTitles[0];
            const firstIdx = flatNew.findIndex((h) => h.title === firstMovedTitle);
            const anchor = firstIdx > 0 ? flatNew[firstIdx - 1].title : null;

            // Optimistic UI: apply locally first
            const previousHubs = hubsRef.current;
            const optimistic = flattenBlocks(newBlocks);
            setHubs(optimistic);
            markPending(movedTitles, true);
            setActionState("saving");
            setErrorMsg(null);

            try {
                // Move first member to anchor
                let prevTitle: string | null = anchor;
                const errors: string[] = [];
                for (const title of movedTitles) {
                    const err = await sendMove(title, prevTitle);
                    if (err) errors.push(err);
                    prevTitle = title;
                    if (movedTitles.length > 1) await sleep(MOVE_CHAIN_DELAY_MS);
                }
                if (errors.length > 0) {
                    setErrorMsg(errors.join("; "));
                    setActionState("error");
                    // Don't revert on partial success — server state is what it is; user can refresh.
                } else {
                    setActionState("idle");
                    onHubsUpdated(optimistic);
                }
            } catch (e: any) {
                setErrorMsg(e?.message ?? String(e));
                setActionState("error");
                setHubs(previousHubs);
            } finally {
                markPending(movedTitles, false);
            }
        },
        [blocks, blockIds, sendMove, markPending, onHubsUpdated],
    );

    // ── Pin (POST /hubs/pins with full current state) ─────────────────────

    const sendPins = useCallback(
        async (top: string | null, bottom: string | null): Promise<string | null> => {
            const res = await fetchWithAuth(
                `/api/libraries/${encodeURIComponent(libraryName)}/hubs/pins`,
                {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ top, bottom }),
                },
            );
            if (!res.ok) {
                const t = await res.text();
                return `Pin failed (${res.status}): ${t}`;
            }
            const data = await res.json();
            const errors: string[] = data.errors ?? [];
            return errors.length > 0 ? errors.join("; ") : null;
        },
        [libraryName],
    );

    const setPin = useCallback(
        async (hubTitle: string, slot: PinSlot) => {
            const previousHubs = hubsRef.current;
            const optimistic = previousHubs.map((h) => {
                if (h.title === hubTitle) return { ...h, pin_position: slot };
                if (h.pin_position === slot) return { ...h, pin_position: null };
                return h;
            });
            setHubs(optimistic);
            markPending([hubTitle], true);
            setActionState("saving");
            setErrorMsg(null);

            const newTop = optimistic.find((h) => h.pin_position === "top")?.title ?? null;
            const newBottom = optimistic.find((h) => h.pin_position === "bottom")?.title ?? null;

            const err = await sendPins(newTop, newBottom);
            markPending([hubTitle], false);
            if (err) {
                setErrorMsg(err);
                setActionState("error");
                setHubs(previousHubs);
            } else {
                setActionState("idle");
                onHubsUpdated(optimistic);
            }
        },
        [sendPins, markPending, onHubsUpdated],
    );

    const unpin = useCallback(
        async (hubTitle: string) => {
            const previousHubs = hubsRef.current;
            const optimistic = previousHubs.map((h) =>
                h.title === hubTitle ? { ...h, pin_position: null } : h,
            );
            setHubs(optimistic);
            markPending([hubTitle], true);
            setActionState("saving");
            setErrorMsg(null);

            const newTop = optimistic.find((h) => h.pin_position === "top")?.title ?? null;
            const newBottom = optimistic.find((h) => h.pin_position === "bottom")?.title ?? null;

            const err = await sendPins(newTop, newBottom);
            markPending([hubTitle], false);
            if (err) {
                setErrorMsg(err);
                setActionState("error");
                setHubs(previousHubs);
            } else {
                setActionState("idle");
                onHubsUpdated(optimistic);
            }
        },
        [sendPins, markPending, onHubsUpdated],
    );

    // ── Visibility (POST /hubs/visibility per change; full 3-flag payload) ─

    const changeVisibility = useCallback(
        async (hubTitle: string, home: boolean, shared: boolean, recommended: boolean) => {
            const previousHubs = hubsRef.current;
            const optimistic = previousHubs.map((h) =>
                h.title === hubTitle
                    ? {
                          ...h,
                          promoted_to_own_home: home,
                          promoted_to_shared_home: shared,
                          promoted_to_recommended: recommended,
                      }
                    : h,
            );
            setHubs(optimistic);
            markPending([hubTitle], true);
            setActionState("saving");
            setErrorMsg(null);

            const res = await fetchWithAuth(
                `/api/libraries/${encodeURIComponent(libraryName)}/hubs/visibility`,
                {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ hub_title: hubTitle, home, shared, recommended }),
                },
            );
            markPending([hubTitle], false);
            if (!res.ok) {
                const t = await res.text();
                setErrorMsg(`Visibility failed (${res.status}): ${t}`);
                setActionState("error");
                setHubs(previousHubs);
                return;
            }
            const data = await res.json();
            if (data.error) {
                setErrorMsg(data.error);
                setActionState("error");
                setHubs(previousHubs);
            } else {
                setActionState("idle");
                onHubsUpdated(optimistic);
            }
        },
        [libraryName, markPending, onHubsUpdated],
    );

    const hiddenCount = hubs.length - visibleHubs.length;

    return (
        <div className="rounded-xl border border-slate-800/60 bg-slate-950/40">
            {/* Sticky library header */}
            <div className="sticky top-0 z-10 flex items-center gap-2 px-3 py-2 border-b border-slate-800/40 bg-slate-950/95 backdrop-blur-sm rounded-t-xl">
                {libraryIcon(libraryType)}
                <h3 className="text-sm font-medium text-slate-200 flex-1">{libraryName}</h3>
                {actionState === "saving" && (
                    <span className="text-[10px] text-slate-500 flex items-center gap-1">
                        <Loader2 size={10} className="animate-spin" /> Saving
                    </span>
                )}
                {actionState === "error" && errorMsg && (
                    <span className="text-[10px] text-rose-300 flex items-center gap-1" title={errorMsg}>
                        <AlertCircle size={10} /> Error
                    </span>
                )}
                <span className="text-[10px] text-slate-500">
                    {visibleHubs.length}{hiddenCount > 0 ? `/${hubs.length}` : ""} hubs
                </span>
            </div>

            {/* Column headers — same gap/padding/widths as a single-hub row */}
            <div className="flex items-center gap-3 px-2 py-1.5 text-[10px] text-slate-500 uppercase tracking-wide">
                <span className={`${GRIP_W} shrink-0`} />
                <span className="flex-1 min-w-0" />
                <div className="flex items-center shrink-0">
                    <div className={`${COL_W} flex justify-center`}>Library Rec.</div>
                    <div className={`${COL_W} flex justify-center`}>Home</div>
                    <div className={`${COL_W} flex justify-center`}>Friends'</div>
                </div>
                <div className={`${PIN_W} flex justify-center shrink-0`}>Pin</div>
            </div>

            {errorMsg && actionState === "error" && (
                <div className="mx-2 mb-1 px-2 py-1.5 rounded bg-rose-500/10 border border-rose-500/20 text-xs text-rose-300 flex items-start gap-2">
                    <AlertCircle size={12} className="mt-0.5 shrink-0" />
                    <span className="flex-1 break-words">{errorMsg}</span>
                    <button
                        type="button"
                        onClick={() => { setErrorMsg(null); setActionState("idle"); }}
                        className="text-rose-300 hover:text-rose-100 shrink-0"
                        aria-label="Dismiss"
                    >
                        <X size={12} />
                    </button>
                </div>
            )}

            <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={handleDragEnd}>
                <SortableContext items={blockIds} strategy={verticalListSortingStrategy}>
                    <div className="px-1 pb-1 space-y-1">
                        {blocks.map((block) => {
                            const blockTitles =
                                block.kind === "group"
                                    ? block.hubs.map((h) => h.title)
                                    : [block.hub.title];
                            const pending = blockTitles.some((t) => pendingTitles.has(t));
                            return (
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
                                    pending={pending}
                                />
                            );
                        })}
                    </div>
                </SortableContext>
            </DndContext>
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
    const [error, setError] = useState<string | null>(null);
    const [hideUnused, setHideUnused] = useState(false);

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
        const getRes = await fetchWithAuth(
            `/api/libraries/${encodeURIComponent(libName)}/hubs`,
        );
        if (!getRes.ok) {
            const t = await getRes.text();
            throw new Error(`GET hubs failed for ${libName}: ${getRes.status} ${t}`);
        }
        const getData: LibraryHubsResponse = await getRes.json();
        if (getData.hubs.length > 0) {
            const syncRes = await fetchWithAuth(
                `/api/libraries/${encodeURIComponent(libName)}/hubs/sync`,
                { method: "POST" },
            );
            if (!syncRes.ok) return getData.hubs;
            const syncData: SyncResponse = await syncRes.json();
            return syncData.hubs;
        }
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
                        // Bug #4 diagnostic: log raw hub_type distribution per library so
                        // future sessions can see why Plex Smart classification misfires.
                        const dist: Record<string, number> = {};
                        for (const h of hubs) dist[h.hub_type] = (dist[h.hub_type] ?? 0) + 1;
                        console.info(`[LibraryHubsCard] ${lib.name} hub_type distribution:`, dist);
                        return [lib.name, hubs] as const;
                    } catch (e: any) {
                        console.warn(`Failed to load hubs for ${lib.name}:`, e);
                        return [lib.name, [] as HubOut[]] as const;
                    }
                }),
            );
            const byLib: Record<string, HubOut[]> = {};
            for (const [name, hubs] of results) byLib[name] = hubs;
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

    return (
        <div className="rounded-2xl border border-slate-800/60 bg-slate-950/40 backdrop-blur-sm">
            <div className="flex items-center justify-between gap-3 px-4 py-3 border-b border-slate-800/40">
                <div>
                    <h2 className="text-sm font-medium text-slate-100">Active Collections</h2>
                    <p className="text-[11px] text-slate-500">Per-library hub order. Drag to reorder. Changes save immediately.</p>
                </div>
                <div className="flex items-center gap-2">
                    <button
                        type="button"
                        onClick={() => setHideUnused((v) => !v)}
                        title="Hide hubs that aren't currently displayed anywhere"
                        className={`text-xs flex items-center gap-1.5 px-2 py-1 rounded border ${
                            hideUnused
                                ? "border-primary/60 bg-primary/10 text-primary"
                                : "border-slate-700 hover:bg-white/5 text-slate-300"
                        }`}
                    >
                        <EyeOff size={12} />
                        Hide unused
                    </button>
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
                        libraryType={lib.type}
                        initialHubs={hubsByLibrary[lib.name] ?? []}
                        hideUnused={hideUnused}
                        onHubsUpdated={(hubs) =>
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
