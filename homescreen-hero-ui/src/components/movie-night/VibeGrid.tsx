import {
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
} from "lucide-react";

export const VIBES = [
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

interface VibeGridProps {
    selectedVibes: string[];
    onToggle: (key: string) => void;
}

export default function VibeGrid({ selectedVibes, onToggle }: VibeGridProps) {
    return (
        <div className="grid grid-cols-2 gap-3">
            {VIBES.map(({ key, label, desc, icon: Icon }, index) => {
                const isSelected = selectedVibes.includes(key);
                return (
                    <button
                        key={key}
                        onClick={() => onToggle(key)}
                        className={`
                            animate-fade-in group rounded-2xl border p-4 text-left
                            transition-all duration-200 active:scale-[0.97]
                            ${
                                isSelected
                                    ? "border-user-accent bg-user-accent/10 shadow-lg shadow-user-accent/10"
                                    : "border-user-card-border bg-user-card hover:border-user-accent/30"
                            }
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
    );
}
