import { describe, it, expect } from "vitest";
import {
    buildBlocks,
    orderBlocksForDisplay,
    type HubBlock,
    type HubOut,
} from "../LibraryHubsCard";

function hub(partial: Partial<HubOut> & { title: string }): HubOut {
    return {
        position: 0,
        hub_type: "external",
        group_name: null,
        pin_position: null,
        visibility_editable: true,
        ...partial,
    } as HubOut;
}

function titlesOf(blocks: HubBlock[]): string[] {
    return blocks.map((b) => (b.kind === "group" ? `[${b.groupName}]` : b.hub.title));
}

describe("orderBlocksForDisplay", () => {
    it("floats a pinned-bottom hub to the end regardless of DB position", () => {
        // Mirrors the live bug: Must See is pinned bottom but sits at a lower
        // DB position than the group blocks that follow it in Plex.
        const hubs: HubOut[] = [
            hub({ title: "Top Movies in (Genre)", position: 29 }),
            hub({ title: "Must See Movies", position: 30, pin_position: "bottom" }),
            hub({ title: "Pirates", position: 31, group_name: "Franchises+Studio" }),
            hub({ title: "Naval", position: 32, group_name: "Home Screen" }),
        ];
        const ordered = orderBlocksForDisplay(buildBlocks(hubs));
        expect(titlesOf(ordered)).toEqual([
            "Top Movies in (Genre)",
            "[Franchises+Studio]",
            "[Home Screen]",
            "Must See Movies",
        ]);
    });

    it("floats a pinned-top hub to the front", () => {
        const hubs: HubOut[] = [
            hub({ title: "Recently Released", position: 0 }),
            hub({ title: "Must See Anime", position: 5, pin_position: "top" }),
            hub({ title: "Library Playlists", position: 1 }),
        ];
        const ordered = orderBlocksForDisplay(buildBlocks(hubs));
        expect(titlesOf(ordered)).toEqual([
            "Must See Anime",
            "Recently Released",
            "Library Playlists",
        ]);
    });

    it("leaves non-pinned order untouched (stable)", () => {
        const hubs: HubOut[] = [
            hub({ title: "A", position: 0 }),
            hub({ title: "B", position: 1 }),
            hub({ title: "C", position: 2 }),
        ];
        const ordered = orderBlocksForDisplay(buildBlocks(hubs));
        expect(titlesOf(ordered)).toEqual(["A", "B", "C"]);
    });

    it("keeps top first and bottom last when both pins are present", () => {
        const hubs: HubOut[] = [
            hub({ title: "Bottom", position: 0, pin_position: "bottom" }),
            hub({ title: "Middle", position: 1 }),
            hub({ title: "Top", position: 2, pin_position: "top" }),
        ];
        const ordered = orderBlocksForDisplay(buildBlocks(hubs));
        expect(titlesOf(ordered)).toEqual(["Top", "Middle", "Bottom"]);
    });
});
