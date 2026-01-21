import { createContext, useContext, useState, useEffect } from "react";
import type { ReactNode } from "react";

type DemoContextType = {
    isDemoMode: boolean;
    loading: boolean;
};

const DemoContext = createContext<DemoContextType>({
    isDemoMode: false,
    loading: true,
});

export function DemoProvider({ children }: { children: ReactNode }) {
    const [isDemoMode, setIsDemoMode] = useState(false);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        // Check if we're in demo mode by calling the backend
        fetch("/api/health/demo-mode")
            .then((res) => res.json())
            .then((data) => {
                setIsDemoMode(data.demo_mode === true);
            })
            .catch(() => {
                // Default to false if check fails
                setIsDemoMode(false);
            })
            .finally(() => {
                setLoading(false);
            });
    }, []);

    return (
        <DemoContext.Provider value={{ isDemoMode, loading }}>
            {children}
        </DemoContext.Provider>
    );
}

export function useDemo() {
    return useContext(DemoContext);
}
