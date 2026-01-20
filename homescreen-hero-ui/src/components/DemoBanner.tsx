import { useDemo } from "../utils/demo";
import { Info } from "lucide-react";

export default function DemoBanner() {
    const { isDemoMode, loading } = useDemo();

    if (loading || !isDemoMode) {
        return null;
    }

    return (
        <div className="bg-amber-500/90 text-amber-950 px-4 py-2 text-center text-sm font-medium flex items-center justify-center gap-2">
            <Info size={16} />
            <span>
                <strong>Demo Mode</strong> — This is a demo instance with mock data.
                Changes will not persist. Login: <code className="bg-amber-600/30 px-1.5 py-0.5 rounded text-xs font-mono">admin / demo</code>
            </span>
        </div>
    );
}
