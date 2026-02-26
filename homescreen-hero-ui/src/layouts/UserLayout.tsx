import { useEffect, useState } from "react";
import { Outlet, NavLink, useNavigate } from "react-router-dom";
import { Home, Compass, Download, User, ArrowLeft } from "lucide-react";
import { useAuth } from "../utils/auth";

const NAV_ITEMS = [
    { to: "/user", icon: Home, label: "Home", end: true },
    { to: "/user/browse", icon: Compass, label: "Browse", end: false },
    { to: "/user/requests", icon: Download, label: "Requests", end: false },
    { to: "/user/account", icon: User, label: "Account", end: false },
];

const USER_BG = "#080d1a";

export interface LayoutContext {
    setHideNav: (hide: boolean) => void;
}

export default function UserLayout() {
    const [hideNav, setHideNav] = useState(false);
    const { role } = useAuth();
    const navigate = useNavigate();
    const isAdmin = role === "admin";

    // Set html/body bg to match so iOS overscroll doesn't flash white
    useEffect(() => {
        const prevHtml = document.documentElement.style.backgroundColor;
        const prevBody = document.body.style.backgroundColor;
        document.documentElement.style.backgroundColor = USER_BG;
        document.body.style.backgroundColor = USER_BG;
        return () => {
            document.documentElement.style.backgroundColor = prevHtml;
            document.body.style.backgroundColor = prevBody;
        };
    }, []);

    return (
        <div className="min-h-screen bg-user-bg text-white flex flex-col">
            {/* Admin preview banner */}
            {isAdmin && (
                <div className="flex items-center justify-between px-4 py-2 bg-user-accent/10 border-b border-user-accent/20">
                    <span className="text-xs font-medium text-user-accent">Viewing as User</span>
                    <button
                        onClick={() => navigate("/")}
                        className="flex items-center gap-1.5 text-xs font-medium text-user-accent hover:text-white transition-colors"
                    >
                        <ArrowLeft size={14} />
                        Back to Admin
                    </button>
                </div>
            )}

            {/* Main content — scrollable, padded for bottom nav */}
            <main className={`flex-1 overflow-y-auto px-5 pt-6 ${hideNav ? "pb-6" : "pb-20"}`}>
                <Outlet context={{ setHideNav } satisfies LayoutContext} />
            </main>

            {/* Bottom navigation — fixed pill (hidden on focused pages) */}
            <nav className={`fixed bottom-4 left-4 right-4 z-50 ${hideNav ? "hidden" : ""}`}>
                <div className="max-w-lg mx-auto flex items-center justify-around bg-user-card/95 backdrop-blur-xl border border-user-card-border rounded-2xl py-2 px-1">
                    {NAV_ITEMS.map(({ to, icon: Icon, label, end }) => (
                        <NavLink
                            key={to}
                            to={to}
                            end={end}
                            className={({ isActive }) =>
                                `flex flex-col items-center gap-1 px-4 py-1.5 transition-colors duration-200 ${
                                    isActive
                                        ? "text-user-accent"
                                        : "text-user-muted hover:text-white"
                                }`
                            }
                        >
                            {({ isActive }) => (
                                <>
                                    <Icon size={22} strokeWidth={isActive ? 2.5 : 2} />
                                    <span className="text-[10px] uppercase tracking-wider font-semibold">
                                        {label}
                                    </span>
                                </>
                            )}
                        </NavLink>
                    ))}
                </div>
            </nav>
        </div>
    );
}
