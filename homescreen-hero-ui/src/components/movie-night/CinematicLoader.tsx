import { useState, useEffect } from "react";
import { m, AnimatePresence } from "motion/react";
import { Clapperboard } from "lucide-react";

const MESSAGES = [
    "Scanning your library…",
    "Matching vibes…",
    "Curating the perfect pick…",
    "Almost there…",
];

export default function CinematicLoader() {
    const [msgIndex, setMsgIndex] = useState(0);

    useEffect(() => {
        const interval = setInterval(() => {
            setMsgIndex((i) => (i + 1) % MESSAGES.length);
        }, 1200);
        return () => clearInterval(interval);
    }, []);

    return (
        <m.div
            key="loading"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0, scale: 0.95, transition: { duration: 0.2 } }}
            className="flex flex-col items-center justify-center py-20"
        >
            {/* Pulsing accent glow behind icon */}
            <div className="relative mb-6">
                <div className="absolute inset-0 rounded-full bg-user-accent/20 blur-xl animate-pulse scale-150" />
                <div className="relative w-16 h-16 rounded-full bg-user-accent/10 border border-user-accent/30 flex items-center justify-center">
                    <Clapperboard size={28} className="text-user-accent" />
                </div>
            </div>

            {/* Cycling messages with crossfade */}
            <AnimatePresence mode="wait">
                <m.p
                    key={msgIndex}
                    initial={{ opacity: 0, y: 8 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, y: -8 }}
                    transition={{ duration: 0.25 }}
                    className="text-user-muted text-sm"
                >
                    {MESSAGES[msgIndex]}
                </m.p>
            </AnimatePresence>
        </m.div>
    );
}
