import { useEffect, useRef, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { api } from "@/lib/api";
import { toast } from "sonner";
import ItemCard from "@/components/ItemCard";
import SearchForm from "@/components/SearchForm";
import { RefreshCw, ChevronLeft, Pencil, Zap, Power } from "lucide-react";

export default function SearchDetail() {
  const { id } = useParams();
  const [search, setSearch] = useState(null);
  const [items, setItems] = useState([]);
  const [meta, setMeta] = useState({});
  const [loading, setLoading] = useState(false);
  const [editing, setEditing] = useState(false);
  const seenIdsRef = useRef(new Set());
  const timerRef = useRef(null);

  const loadSearch = async () => {
    const { data } = await api.get(`/searches/${id}`);
    setSearch(data);
  };

  // Fetch the latest items the BACKGROUND WORKER has cached
  const fetchCache = async () => {
    try {
      const { data } = await api.get(`/searches/${id}/items?limit=48`);
      // mark items that we haven't seen yet in THIS browser session as "new"
      const fresh = data.items.map((it) => {
        const isNew = !seenIdsRef.current.has(it.id);
        return { ...it, is_new: isNew };
      });
      // After the first frame stop flashing already-seen items
      data.items.forEach((it) => seenIdsRef.current.add(it.id));
      setItems(fresh);
      setMeta({
        last_run_at: data.last_run_at,
        last_poll_duration_ms: data.last_poll_duration_ms,
        poll_count: data.poll_count,
        enabled: data.enabled,
        polling_interval: data.polling_interval,
      });
    } catch (e) {
      // silent
    }
  };

  const forceRun = async () => {
    setLoading(true);
    try {
      const { data } = await api.post(`/searches/${id}/run`);
      if (data.new_count > 0) toast.success(`${data.new_count} new item${data.new_count > 1 ? "s" : ""} found`);
      if (data.autobuy_attempts?.length) {
        data.autobuy_attempts.forEach((a) => {
          if (a.result.success) toast.success(`Autobuy OK on item ${a.item_id}`);
          else toast.error(`Autobuy failed: ${a.result.message}`);
        });
      }
      await fetchCache();
    } catch (e) {
      toast.error("Refresh failed: " + (e.response?.data?.detail || e.message));
    } finally {
      setLoading(false);
    }
  };

  const toggleEnabled = async () => {
    try {
      const { data } = await api.post(`/searches/${id}/toggle`);
      toast.success(data.enabled ? "Worker enabled" : "Worker disabled");
      loadSearch();
      fetchCache();
    } catch {
      toast.error("Toggle failed");
    }
  };

  useEffect(() => {
    loadSearch();
    fetchCache();
    timerRef.current = setInterval(fetchCache, 2000);
    return () => clearInterval(timerRef.current);
  }, [id]);

  const saveEdit = async (payload) => {
    try {
      await api.put(`/searches/${id}`, payload);
      toast.success("Updated");
      setEditing(false);
      loadSearch();
    } catch {
      toast.error("Update failed");
    }
  };

  if (!search) return <div className="font-mono text-sm pulse-dot">Loading hunt...</div>;

  const enabled = meta.enabled ?? search.enabled ?? true;
  const interval = meta.polling_interval ?? search.polling_interval ?? 2;
  const lastMs = meta.last_poll_duration_ms;

  return (
    <div className="space-y-6" data-testid="search-detail-page">
      <Link to="/" className="font-mono text-xs uppercase tracking-widest inline-flex items-center gap-1 hover:underline" data-testid="back-link">
        <ChevronLeft size={14} /> Back to control room
      </Link>

      <div className="brut-card p-6 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="font-head text-4xl font-black tracking-tighter">{search.name}</h1>
          <div className="font-mono text-xs uppercase tracking-widest text-gray-600 mt-1">
            {search.keyword || "no keyword"} · {search.price_from ?? "*"}–{search.price_to ?? "*"} {search.currency}
          </div>
          <div className="flex items-center gap-2 mt-3 flex-wrap">
            {search.autobuy ? (
              <span className="brut-border bg-[#00C853] text-black font-mono text-[10px] font-black uppercase px-2 py-1 flex items-center gap-1">
                <Zap size={10} /> AUTOBUY · MAX {search.max_autobuy_price ?? "∞"}€
              </span>
            ) : (
              <span className="brut-border bg-white font-mono text-[10px] font-bold uppercase px-2 py-1">MANUAL</span>
            )}
            <span className={`brut-border font-mono text-[10px] font-black uppercase px-2 py-1 ${enabled ? "bg-[#002FA7] text-white" : "bg-gray-200 text-black"}`}>
              {enabled ? `WORKER · ${interval}s` : "WORKER OFF"}
            </span>
            <span className="brut-border bg-black text-white font-mono text-[10px] font-bold uppercase px-2 py-1">
              {items.length} cached · {meta.poll_count ?? 0} polls
            </span>
            {lastMs != null && (
              <span className="brut-border bg-white font-mono text-[10px] font-bold uppercase px-2 py-1">last: {lastMs}ms</span>
            )}
          </div>
        </div>
        <div className="flex gap-2 flex-wrap">
          <button onClick={toggleEnabled} className={`brut-btn text-xs flex items-center gap-2 ${enabled ? "brut-btn-destructive" : "brut-btn-success"}`} data-testid="toggle-enabled-btn">
            <Power size={14} /> {enabled ? "Stop worker" : "Start worker"}
          </button>
          <button onClick={forceRun} disabled={loading} className="brut-btn brut-btn-secondary text-xs flex items-center gap-2" data-testid="refresh-btn">
            <RefreshCw size={14} className={loading ? "animate-spin" : ""} /> Force Run
          </button>
          <button onClick={() => setEditing((v) => !v)} className="brut-btn brut-btn-secondary text-xs flex items-center gap-2" data-testid="edit-search-btn">
            <Pencil size={14} /> Edit
          </button>
        </div>
      </div>

      {editing && (
        <SearchForm initial={search} onSubmit={saveEdit} onCancel={() => setEditing(false)} submitLabel="Save changes" />
      )}

      <div className="flex items-center justify-between font-mono text-xs uppercase tracking-widest">
        <div className="flex items-center gap-2">
          <span className={`w-2 h-2 rounded-full ${enabled ? "bg-[#00C853] pulse-dot" : "bg-gray-400"}`}></span>
          {enabled ? `Server-side polling every ${interval}s` : "Worker disabled"}
        </div>
        <div>{meta.last_run_at ? `Last poll: ${new Date(meta.last_run_at).toLocaleTimeString()}` : "—"}</div>
      </div>

      {items.length === 0 ? (
        <div className="brut-card p-12 text-center" data-testid="no-items">
          <div className="font-mono text-xs uppercase tracking-widest">Waiting for first hit... worker is on the case.</div>
          <div className="font-mono text-[10px] uppercase tracking-widest text-gray-500 mt-2">
            Tip: configure your Vinted session in Settings for full access.
          </div>
        </div>
      ) : (
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4" data-testid="items-grid">
          {items.map((it) => <ItemCard key={it.id} item={it} />)}
        </div>
      )}
    </div>
  );
}
