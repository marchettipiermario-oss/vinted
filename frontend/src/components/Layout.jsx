import { Outlet, Link, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "@/contexts/AuthContext";
import { LogOut, LayoutGrid, Settings as SettingsIcon, Activity, Tag } from "lucide-react";

export default function Layout() {
  const { user, logout } = useAuth();
  const loc = useLocation();
  const nav = useNavigate();

  const navItem = (to, label, Icon) => {
    const active = loc.pathname === to || (to === "/" && loc.pathname.startsWith("/search"));
    return (
      <Link
        to={to}
        data-testid={`nav-${label.toLowerCase()}`}
        className={`flex items-center gap-2 px-3 py-2 brut-border font-mono text-xs font-bold uppercase tracking-widest ${
          active ? "bg-black text-white" : "bg-white text-black hover:bg-black hover:text-white"
        }`}
      >
        <Icon size={14} /> {label}
      </Link>
    );
  };

  return (
    <div className="min-h-screen bg-[#F9FAFB]">
      <header className="brut-border border-x-0 border-t-0 bg-white">
        <div className="max-w-[1400px] mx-auto px-4 sm:px-6 py-4 flex flex-wrap items-center gap-4">
          <Link to="/" className="flex items-center gap-2" data-testid="brand-link">
            <div className="w-8 h-8 bg-[#002FA7] brut-border flex items-center justify-center">
              <Activity size={18} className="text-white" />
            </div>
            <div className="font-head font-black text-2xl tracking-tighter leading-none">
              VINTED<span className="text-[#FF3B30]">.</span>BOT
            </div>
          </Link>
          <nav className="flex gap-2 ml-auto flex-wrap">
            {navItem("/", "Dashboard", LayoutGrid)}
            {navItem("/listings", "Crosslist", Tag)}
            {navItem("/earnings", "Earnings", Activity)}
            {navItem("/settings", "Settings", SettingsIcon)}
            <span className="font-mono text-xs uppercase tracking-widest px-3 py-2 bg-[#F9FAFB] brut-border" data-testid="user-email">
              {user?.email}
            </span>
            <button
              data-testid="logout-btn"
              onClick={async () => { await logout(); nav("/login"); }}
              className="brut-btn brut-btn-destructive text-xs flex items-center gap-2"
            >
              <LogOut size={14} /> Logout
            </button>
          </nav>
        </div>
      </header>
      <main className="max-w-[1400px] mx-auto px-4 sm:px-6 py-8">
        <Outlet />
      </main>
    </div>
  );
}
