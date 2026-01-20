import { Outlet } from "react-router-dom";
import TopNav from "../components/TopNav";
import DemoBanner from "../components/DemoBanner";

export default function AppLayout() {
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