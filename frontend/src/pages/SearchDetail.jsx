import { useEffect, useRef, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { api } from "@/lib/api";
import { toast } from "sonner";
import ItemCard from "@/components/ItemCard";
import SearchForm from "@/components/SearchForm";
import { Pause, Play, RefreshCw, ChevronLeft, Pencil, Zap } from "lucide-react";

export default function SearchDetail() {
  const { id } = useParams();
  const [search, setSearch] = useState(null);
  const [items, setItems] = useState([]);
  const [lastRun, setLastRun] = useState(null);
  const [polling, setPolling] = useState(true);
  const [loading, setLoading] = useState(false);
  const [newCount, setNewCount] = useState(0);
  const [editing, setEditing] = useState(false);
  const timerRef = useRef(null);

  const loadSearch = async () => {
    const { data } = await api.get(`/searches/${id}`);
    setSearch(data);
  };

  const runOnce = async () => {
    setLoading(true);
    try {
      const { data } = await api.post(`/searches/${id}/run`);
      setItems(data.items);
      setNewCount(data.new_count);
      setLastRun(new Date());
      if (data.new_count > 0) {
        toast.success(`${data.new_count} new item${data.new_count > 1 ? "s" : ""} found`);
      }
      if (data.autobuy_attempts?.length) {
        data.autobuy_attempts.forEach((a) => {
          if (a.result.success) toast.success(`Autobuy OK on item ${a.item_id}`);
          else toast.error(`Autobuy failed: ${a.result.message}`);
        });
      }
    } catch (e) {
      toast.error("Search failed: " + (e.response?.data?.detail || e.message));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadSearch();
    runOnce();
    // eslint-disable-next-line
  }, [id]);

  useEffect(() => {
    if (!polling) {
      if (timerRef.current) clearInterval(timerRef.current);
      return;
    }
    timerRef.current = setInterval(runOnce, 10000);
    return () => clearInterval(timerRef.current);
    // eslint-disable-next-line
  }, [polling, id]);

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
          <div className="flex items-center gap-2 mt-3">
            {search.autobuy ? (
              <span className="brut-border bg-[#00C853] text-black font-mono text-[10px] font-black uppercase px-2 py-1 flex items-center gap-1">
                <Zap size={10} /> AUTOBUY · MAX {search.max_autobuy_price ?? "∞"}€
              </span>
            ) : (
              <span className="brut-border bg-white font-mono text-[10px] font-bold uppercase px-2 py-1">MANUAL</span>
            )}
            <span className="brut-border bg-black text-white font-mono text-[10px] font-bold uppercase px-2 py-1">
              {items.length} live · {newCount} new
            </span>
          </div>
        </div>
        <div className="flex gap-2">
          <button onClick={() => setPolling((v) => !v)} className="brut-btn brut-btn-secondary text-xs flex items-center gap-2" data-testid="toggle-polling-btn">
            {polling ? <><Pause size={14} /> Pause</> : <><Play size={14} /> Resume</>}
          </button>
          <button onClick={runOnce} disabled={loading} className="brut-btn text-xs flex items-center gap-2" data-testid="refresh-btn">
            <RefreshCw size={14} className={loading ? "animate-spin" : ""} /> Refresh
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
          <span className={`w-2 h-2 rounded-full ${polling ? "bg-[#00C853] pulse-dot" : "bg-gray-400"}`}></span>
          {polling ? "Live · polling every 10s" : "Paused"}
        </div>
        <div>{lastRun ? `Last: ${lastRun.toLocaleTimeString()}` : "—"}</div>
      </div>

      {items.length === 0 ? (
        <div className="brut-card p-12 text-center" data-testid="no-items">
          <div className="font-mono text-xs uppercase tracking-widest">No items yet. Refresh or wait for next poll.</div>
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
