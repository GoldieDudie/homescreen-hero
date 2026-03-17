import { useState, useEffect, useCallback } from "react";
import { Outlet } from "react-router-dom";
import TopNav from "../components/TopNav";
import Sidebar from "../components/Sidebar";
import TopBar from "../components/TopBar";
import Toast from "../components/Toast";
import { Sheet, SheetContent, SheetTitle } from "../components/ui/sheet";
import { useTheme } from "../utils/theme";
import { PageHeaderProvider } from "../utils/pageHeader";
import { OnboardingProvider } from "../utils/onboarding";
import { Github, Info } from "lucide-react";

const isDemo = import.meta.env.VITE_DEMO_MODE === "true";

function DemoBanner() {
    if (!isDemo) return null;
    return (
        <div className="w-full bg-primary/90 text-white text-center text-xs font-medium py-1.5 px-4 flex items-center justify-center gap-3">
            <Info size={13} className="shrink-0" />
            <span>You're viewing homescreen-hero in demo mode. Some actions are disabled.</span>
            <a
                href="https://github.com/trentferguson/homescreen-hero"
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 underline underline-offset-2 hover:opacity-80 transition-opacity"
            >
                <Github size={12} />
                View on GitHub
            </a>
        </div>
    );
}

function TopNavLayout() {
    return (
        <div className="min-h-screen bg-slate-50 text-slate-900 dark:bg-slate-950 dark:text-slate-100">
            <DemoBanner />
            <TopNav />

            <main className="mx-auto max-w-7xl px-4 py-6">
                <Outlet />
            </main>
        </div>
    );
}

function SidebarLayout() {
    const [mobileNavOpen, setMobileNavOpen] = useState(false);
    const closeMobileNav = () => setMobileNavOpen(false);

    return (
        <PageHeaderProvider>
        <div className="min-h-screen bg-[#11161b] text-slate-100">
            <DemoBanner />
            {/* Desktop sidebar */}
            <div className="hidden lg:fixed lg:inset-y-0 lg:flex lg:w-60" style={isDemo ? { top: "30px" } : undefined}>
                <Sidebar />
            </div>

            {/* Mobile sidebar */}
            <Sheet open={mobileNavOpen} onOpenChange={setMobileNavOpen}>
                <SheetContent side="left" className="w-60 p-0 bg-[#12161b] border-slate-800/60">
                    <SheetTitle className="sr-only">Navigation</SheetTitle>
                    <Sidebar onNavigate={closeMobileNav} />
                </SheetContent>
            </Sheet>

            {/* Content area offset by sidebar width on desktop */}
            <div className={`lg:pl-60 flex flex-col ${isDemo ? "min-h-[calc(100vh-30px)]" : "min-h-screen"}`}>
                <TopBar onMenuClick={() => setMobileNavOpen(true)} />

                <main className="flex-1 mx-auto w-full max-w-7xl px-4 py-6 lg:px-6">
                    <Outlet />
                </main>
            </div>
        </div>
        </PageHeaderProvider>
    );
}

export default function AppLayout() {
    const { accent } = useTheme();
    const [demoToast, setDemoToast] = useState(false);

    const handleDemoBlocked = useCallback(() => {
        setDemoToast(true);
    }, []);

    useEffect(() => {
        window.addEventListener("demo-blocked", handleDemoBlocked);
        return () => window.removeEventListener("demo-blocked", handleDemoBlocked);
    }, [handleDemoBlocked]);

    return (
        <OnboardingProvider>
            {accent === "plex-orange" ? <SidebarLayout /> : <TopNavLayout />}
            {demoToast && (
                <Toast
                    message="This action is disabled in demo mode."
                    type="error"
                    onClose={() => setDemoToast(false)}
                    duration={4000}
                />
            )}
        </OnboardingProvider>
    );
}
