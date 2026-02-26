import { NavLink, useNavigate } from "react-router-dom";
import { User, LogOut, Settings, Eye } from "lucide-react";
import IconButton from "./IconButton";
import VersionBadge from "./VersionBadge";
import { Popover, PopoverTrigger, PopoverContent } from "./ui/popover";
import { useAuth } from "../utils/auth";

function NavItem({ to, label }: { to: string; label: string }) {
    return (
        <NavLink
            to={to}
            className={({ isActive }) =>
                `px-3 py-2 text-sm font-semibold transition-colors ${isActive
                    ? "text-slate-900 dark:text-white"
                    : "text-slate-600 hover:text-slate-900 dark:text-slate-400 dark:hover:text-white"
                }`
            }
            end={to === "/"}
        >
            {label}
        </NavLink>
    );
}

export default function TopNav() {
    const { logout, username, authEnabled, thumb } = useAuth();
    const navigate = useNavigate();

    const handleLogout = () => {
        logout();
        navigate("/login");
    };

    return (
        <header className="sticky top-0 z-50 border-b border-slate-200/80 bg-white/80 backdrop-blur-xl dark:border-slate-800/60 dark:bg-slate-950/80 transition-all duration-300">
            <div className="mx-auto max-w-7xl px-4 h-16 flex items-center justify-between">
                {/* LEFT: Logo */}
                <div className="flex items-center gap-3">
                    <NavLink to="/" className="flex items-center group">
                        <img
                            src="/logo.svg"
                            alt="homescreen-hero"
                            className="h-10 w-auto select-none transition-transform duration-200 group-hover:scale-105"
                        />
                    </NavLink>
                    <h1 className="text-2xl font-medium text-slate-900 dark:text-white tracking-tight" style={{ fontFamily: 'Oxanium' }}>homescreen-hero</h1>
                </div>

                {/* CENTER: Nav */}
                <nav className="hidden md:flex items-center gap-1">
                    <NavItem to="/" label="Dashboard" />
                    <NavItem to="/groups" label="Groups" />
                    <NavItem to="/collections" label="Collections" />
                    <NavItem to="/integrations" label="Integrations" />
                    <NavItem to="/tools" label="Tools" />
                </nav>

                {/* RIGHT: Version + Icons */}
                <div className="flex items-center gap-3">
                    <VersionBadge />
                    <IconButton label="Settings" onClick={() => navigate("/settings")}>
                        <Settings size={20} />
                    </IconButton>

                    <Popover>
                        <PopoverTrigger asChild>
                            <button
                                className="text-slate-400 hover:text-white transition-colors rounded-full focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500"
                                aria-label="User menu"
                            >
                                {thumb ? (
                                    <img
                                        src={thumb}
                                        alt={username ?? "User"}
                                        className="h-6 w-6 rounded-full object-cover"
                                    />
                                ) : (
                                    <User size={20} />
                                )}
                            </button>
                        </PopoverTrigger>
                        <PopoverContent align="end" sideOffset={8} className="w-48 p-1.5">
                            {/* Username */}
                            <div className="px-3 py-2 text-xs font-medium text-slate-400 truncate">
                                {username ?? "User"}
                            </div>

                            {/* Switch to User View */}
                            <button
                                onClick={() => navigate("/user")}
                                className="flex items-center gap-2 w-full px-3 py-2 text-sm text-slate-200 hover:bg-slate-800 rounded-lg transition-colors"
                            >
                                <Eye size={16} className="text-slate-400" />
                                User View
                            </button>

                            {/* Logout */}
                            {authEnabled && (
                                <button
                                    onClick={handleLogout}
                                    className="flex items-center gap-2 w-full px-3 py-2 text-sm text-slate-200 hover:bg-slate-800 rounded-lg transition-colors"
                                >
                                    <LogOut size={16} className="text-slate-400" />
                                    Sign Out
                                </button>
                            )}
                        </PopoverContent>
                    </Popover>
                </div>
            </div>
        </header>
    );
}