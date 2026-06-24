import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "@/lib/api";
import { toast } from "sonner";
import SearchForm from "@/components/SearchForm";
import { Plus, Trash2, Search as SearchIcon, Zap } from "lucide-react";

function StatBox({ label, value, accent }) {
  return (
    <div className="brut-card p-4">
      <div className="brut-label">{label}</div>
      <div className={`font-mono text-3xl font-black ${accent || "text-black"}`}>{value}</div>
    </div>
  );
}

export default function Dashboard() {
  const [searches, setSearches] = useState([]);
  const [stats, setStats] = useState({ total_searches: 0, items_today: 0, autobuys_total: 0, autobuys_ok: 0 });
  const [worker, setWorker] = useState({ running: false, total_polls: 0, total_errors: 0, active_searches: 0 });
  const [showForm, setShowForm] = useState(false);

  const load = async () => {
    try {
      const [s, st, w] = await Promise.all([
        api.get("/searches"),
        api.get("/stats"),
        api.get("/worker/status"),
      ]);
      setSearches(s.data);
      setStats(st.data);
      setWorker(w.data);
    } catch (e) {
      toast.error("Failed to load dashboard");
    }
  };

  useEffect(() => {
    load();
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  }, []);

  const handleCreate = async (payload) => {
    try {
      await api.post("/searches", payload);
      toast.success("Search created");
      setShowForm(false);
      load();
    } catch (e) {
      toast.error("Create failed");
    }
  };

  const remove = async (id) => {
    if (!window.confirm("Delete this search?")) return;
    try {
      await api.delete(`/searches/${id}`);
      toast.success("Deleted");
      load();
    } catch {
      toast.error("Delete failed");
    }
  };

  return (
    <div className="space-y-8" data-testid="dashboard-page">
      <div className="flex items-end justify-between flex-wrap gap-4">
        <div>
          <h1 className="font-head text-4xl sm:text-5xl font-black tracking-tighter leading-none">
            Control Room
          </h1>
          <p className="font-mono text-xs uppercase tracking-widest text-gray-600 mt-2">
            // monitor vinted in real-time, configure autobuy targets
          </p>
        </div>
        <button onClick={() => setShowForm((v) => !v)} className="brut-btn flex items-center gap-2" data-testid="toggle-create-search-btn">
          <Plus size={16} /> {showForm ? "Close" : "New Search"}
        </button>
      </div>

      <div className="brut-border bg-black text-white shadow-[4px_4px_0px_0px_rgba(0,0,0,1)] p-4 flex items-center justify-between gap-4 flex-wrap" data-testid="worker-status">
        <div className="flex items-center gap-3">
          <span className={`w-3 h-3 rounded-full ${worker.running ? "bg-[#00C853] pulse-dot" : "bg-[#FF3B30]"}`}></span>
          <div>
            <div className="font-head font-black tracking-tight text-lg">BACKGROUND WORKER · {worker.running ? "ONLINE" : "OFFLINE"}</div>
            <div className="font-mono text-[10px] uppercase tracking-widest opacity-70">
              {worker.active_searches} active hunts · {worker.total_polls} total polls · {worker.total_errors} errors
            </div>
          </div>
        </div>
        <Link to="/settings" className="font-mono text-[10px] uppercase tracking-widest underline" data-testid="goto-settings-link">
          Configure Vinted session →
        </Link>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4" data-testid="stats-grid">
        <StatBox label="Searches" value={stats.total_searches} />
        <StatBox label="Items Today" value={stats.items_today} accent="text-[#002FA7]" />
        <StatBox label="Autobuys" value={stats.autobuys_total} />
        <StatBox label="Success" value={stats.autobuys_ok} accent="text-[#00C853]" />
      </div>

      {showForm && (
        <SearchForm onSubmit={handleCreate} onCancel={() => setShowForm(false)} submitLabel="Create Hunt" />
      )}

      <div className="space-y-3">
        <h2 className="font-head text-2xl font-black tracking-tighter">// Active Hunts</h2>
        {searches.length === 0 ? (
          <div className="brut-card p-12 text-center" data-testid="empty-searches">
            <SearchIcon size={32} className="mx-auto mb-3" />
            <div className="font-mono text-xs uppercase tracking-widest">No active hunts. Create one to start monitoring.</div>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {searches.map((s) => (
              <div key={s.id} className="brut-card p-4 flex flex-col gap-2" data-testid={`search-row-${s.id}`}>
                <div className="flex items-start justify-between gap-2">
                  <Link to={`/search/${s.id}`} className="font-head font-bold text-lg leading-tight hover:underline" data-testid={`search-open-${s.id}`}>
                    {s.name}
                  </Link>
                  <button onClick={() => remove(s.id)} className="brut-border bg-white p-1 hover:bg-[#FF3B30] hover:text-white" data-testid={`search-delete-${s.id}`}>
                    <Trash2 size={14} />
                  </button>
                </div>
                <div className="font-mono text-[10px] text-gray-600 uppercase">
                  {s.keyword || "no keyword"} · {s.price_from ?? "*"} - {s.price_to ?? "*"} {s.currency}
                </div>
                <div className="flex items-center gap-2 mt-2 flex-wrap">
                  {s.autobuy ? (
                    <span className="brut-border bg-[#00C853] text-black font-mono text-[10px] font-black uppercase px-2 py-1 flex items-center gap-1">
                      <Zap size={10} /> AUTOBUY ARMED
                    </span>
                  ) : (
                    <span className="brut-border bg-white font-mono text-[10px] font-bold uppercase px-2 py-1">manual</span>
                  )}
                  <span className={`brut-border font-mono text-[10px] font-black uppercase px-2 py-1 ${s.enabled ? "bg-[#002FA7] text-white" : "bg-gray-200"}`}>
                    {s.enabled ? `${s.polling_interval ?? 2}s` : "OFF"}
                  </span>
                  <span className="brut-border bg-black text-white font-mono text-[10px] font-bold uppercase px-2 py-1 ml-auto">
                    {s.items_found_total} found
                  </span>
                </div>
                <Link to={`/search/${s.id}`} className="brut-btn text-xs mt-2 text-center" data-testid={`search-monitor-${s.id}`}>
                  Open Live Feed →
                </Link>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
