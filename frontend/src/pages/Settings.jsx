import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { toast } from "sonner";
import { Check, AlertTriangle, Trash2, Plus, Zap } from "lucide-react";

export default function Settings() {
  const [cfg, setCfg] = useState({ domain: "www.vinted.it", cookie: "", user_agent: "", configured: false });
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [pool, setPool] = useState([]);
  const [newLabel, setNewLabel] = useState("");
  const [newCookie, setNewCookie] = useState("");
  const [tg, setTg] = useState({ bot_token: "", chat_id: "", notify_drops: true, notify_autobuy: true, configured: false });

  const saveTg = async () => {
    try {
      await api.put("/telegram/config", { bot_token: tg.bot_token, chat_id: tg.chat_id, notify_drops: tg.notify_drops, notify_autobuy: tg.notify_autobuy });
      toast.success("Telegram saved");
      const { data } = await api.get("/telegram/config");
      setTg(data);
    } catch { toast.error("Save failed"); }
  };

  const testTg = async () => {
    try {
      const { data } = await api.post("/telegram/test");
      if (data.ok) toast.success("Test message sent — check your Telegram");
      else toast.error("Failed — check token/chat_id");
    } catch { toast.error("Test failed"); }
  };

  const loadPool = async () => {
    try {
      const { data } = await api.get("/vinted/cookies");
      setPool(data);
    } catch { /* ignore */ }
  };

  useEffect(() => {
    (async () => {
      try {
        const { data } = await api.get("/vinted/config");
        setCfg(data);
      } catch { /* ignore */ }
      loadPool();
      try {
        const { data } = await api.get("/telegram/config");
        setTg(data);
      } catch { /* ignore */ }
    })();
  }, []);

  const save = async () => {
    setSaving(true);
    try {
      await api.put("/vinted/config", { domain: cfg.domain, cookie: cfg.cookie, user_agent: cfg.user_agent });
      toast.success("Config saved");
    } catch { toast.error("Save failed"); }
    finally { setSaving(false); }
  };

  const test = async () => {
    setTesting(true);
    try {
      const { data } = await api.post("/vinted/test");
      if (data.ok) toast.success(`Connected to ${data.domain} · ${data.count} items returned`);
      else toast.error("Connection test failed. Check your cookie/domain.");
    } catch { toast.error("Test failed"); }
    finally { setTesting(false); }
  };

  const addCookie = async () => {
    if (!newLabel || !newCookie) return toast.error("Label and cookie required");
    try {
      await api.post("/vinted/cookies", { label: newLabel, cookie: newCookie, enabled: true });
      setNewLabel(""); setNewCookie("");
      toast.success("Cookie added to pool");
      loadPool();
    } catch { toast.error("Add failed"); }
  };

  const toggleCookie = async (id) => {
    try { await api.post(`/vinted/cookies/${id}/toggle`); loadPool(); } catch { toast.error("Toggle failed"); }
  };

  const deleteCookie = async (id) => {
    if (!window.confirm("Delete this cookie from the pool?")) return;
    try { await api.delete(`/vinted/cookies/${id}`); loadPool(); } catch { toast.error("Delete failed"); }
  };

  const activePoolSize = pool.filter(p => p.enabled).length;
  const speedup = 1 + activePoolSize;

  return (
    <div className="space-y-6 max-w-3xl" data-testid="settings-page">
      <div>
        <h1 className="font-head text-4xl font-black tracking-tighter">Settings</h1>
        <p className="font-mono text-xs uppercase tracking-widest text-gray-600 mt-2">
          // configure your vinted session for autobuy + cookie pool for staggered polling
        </p>
      </div>

      <div className="brut-card p-6 space-y-4">
        <h2 className="font-head text-2xl font-black tracking-tighter">// Primary Vinted Session (autobuy)</h2>
        <div className="brut-border bg-yellow-50 p-3 flex gap-2 font-mono text-xs">
          <AlertTriangle size={16} className="shrink-0" />
          <div>F12 → Network → click any vinted request → Headers → copy <code>Cookie</code> value. <strong>Autobuy uses this primary cookie.</strong></div>
        </div>
        <div>
          <label className="brut-label">Vinted Domain</label>
          <select data-testid="vinted-domain-select" className="brut-input" value={cfg.domain} onChange={(e) => setCfg({ ...cfg, domain: e.target.value })}>
            <option value="www.vinted.it">www.vinted.it</option>
            <option value="www.vinted.fr">www.vinted.fr</option>
            <option value="www.vinted.de">www.vinted.de</option>
            <option value="www.vinted.es">www.vinted.es</option>
            <option value="www.vinted.com">www.vinted.com</option>
            <option value="www.vinted.co.uk">www.vinted.co.uk</option>
            <option value="www.vinted.pl">www.vinted.pl</option>
            <option value="www.vinted.nl">www.vinted.nl</option>
          </select>
        </div>
        <div>
          <label className="brut-label">Primary Session Cookie</label>
          <textarea data-testid="vinted-cookie-input" className="brut-input min-h-[100px]" value={cfg.cookie} onChange={(e) => setCfg({ ...cfg, cookie: e.target.value })} placeholder="_vinted_fr_session=...; access_token_web=...;" />
        </div>
        <div>
          <label className="brut-label">User-Agent (optional)</label>
          <input data-testid="vinted-ua-input" className="brut-input" value={cfg.user_agent || ""} onChange={(e) => setCfg({ ...cfg, user_agent: e.target.value })} />
        </div>
        <div className="flex gap-3 items-center flex-wrap">
          <button onClick={save} disabled={saving} className="brut-btn" data-testid="settings-save-btn">{saving ? "Saving..." : "Save Config"}</button>
          <button onClick={test} disabled={testing} className="brut-btn brut-btn-secondary" data-testid="settings-test-btn">{testing ? "Testing..." : "Test Connection"}</button>
          {cfg.configured && <span className="font-mono text-xs uppercase tracking-widest flex items-center gap-1 text-[#00C853]"><Check size={14} /> Cookie configured</span>}
        </div>
      </div>

      <div className="brut-card p-6 space-y-4" data-testid="cookie-pool-section">
        <div className="flex items-center justify-between flex-wrap gap-2">
          <h2 className="font-head text-2xl font-black tracking-tighter">// Cookie Pool · Staggered Polling</h2>
          <span className="brut-border bg-[#002FA7] text-white font-mono text-[10px] font-black uppercase px-2 py-1 flex items-center gap-1">
            <Zap size={10} /> SPEEDUP ×{speedup}
          </span>
        </div>
        <div className="brut-border bg-blue-50 p-3 font-mono text-xs">
          Add cookies from <strong>different Vinted accounts</strong>. The worker rotates them and staggers polls — with N active cookies, effective discovery latency drops from <code>interval</code> to <code>interval / (1+N)</code>. Autobuy still uses the primary cookie above.
        </div>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
          <input className="brut-input" placeholder="Label (e.g. alt 1)" data-testid="cookie-label-input" value={newLabel} onChange={(e) => setNewLabel(e.target.value)} />
          <input className="brut-input md:col-span-2" placeholder="Cookie value" data-testid="cookie-value-input" value={newCookie} onChange={(e) => setNewCookie(e.target.value)} />
        </div>
        <button onClick={addCookie} className="brut-btn text-xs flex items-center gap-2" data-testid="cookie-add-btn"><Plus size={14} /> Add to pool</button>

        <div className="space-y-2">
          {pool.length === 0 ? (
            <div className="font-mono text-xs uppercase tracking-widest text-gray-500">// no extra cookies yet · pool size 1 (primary only)</div>
          ) : pool.map((c) => (
            <div key={c.id} className="brut-border bg-white p-3 flex items-center gap-3 flex-wrap" data-testid={`pool-row-${c.id}`}>
              <button onClick={() => toggleCookie(c.id)} className={`brut-border px-2 py-1 font-mono text-[10px] font-bold uppercase ${c.enabled ? "bg-[#00C853] text-black" : "bg-gray-200"}`} data-testid={`pool-toggle-${c.id}`}>
                {c.enabled ? "ON" : "OFF"}
              </button>
              <div className="flex-1 min-w-0">
                <div className="font-head font-bold text-sm">{c.label}</div>
                <div className="font-mono text-[10px] text-gray-500 truncate">{c.cookie_preview}</div>
              </div>
              <button onClick={() => deleteCookie(c.id)} className="brut-border bg-white p-1 hover:bg-[#FF3B30] hover:text-white" data-testid={`pool-delete-${c.id}`}><Trash2 size={14} /></button>
            </div>
          ))}
        </div>
      </div>
      <div className="brut-card p-6 space-y-4" data-testid="telegram-section">
        <h2 className="font-head text-2xl font-black tracking-tighter">// Telegram Notifications</h2>
        <div className="brut-border bg-blue-50 p-3 font-mono text-xs">
          1) Chatta con <strong>@BotFather</strong> su Telegram → <code>/newbot</code> → copia il <strong>token</strong>.<br/>
          2) Apri il tuo bot → invia un messaggio qualsiasi → vai su <code>https://api.telegram.org/bot&lt;TOKEN&gt;/getUpdates</code> → copia il <strong>chat_id</strong> dal risultato.
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <div>
            <label className="brut-label">Bot Token</label>
            <input data-testid="tg-token-input" className="brut-input" value={tg.bot_token} onChange={(e) => setTg({ ...tg, bot_token: e.target.value })} placeholder="123456:ABC-..." />
          </div>
          <div>
            <label className="brut-label">Chat ID</label>
            <input data-testid="tg-chatid-input" className="brut-input" value={tg.chat_id} onChange={(e) => setTg({ ...tg, chat_id: e.target.value })} placeholder="123456789" />
          </div>
        </div>
        <div className="flex gap-4 flex-wrap">
          <label className="flex items-center gap-2 font-mono text-xs uppercase">
            <input type="checkbox" data-testid="tg-notify-drops" checked={tg.notify_drops} onChange={(e) => setTg({ ...tg, notify_drops: e.target.checked })} />
            Notify new drops
          </label>
          <label className="flex items-center gap-2 font-mono text-xs uppercase">
            <input type="checkbox" data-testid="tg-notify-autobuy" checked={tg.notify_autobuy} onChange={(e) => setTg({ ...tg, notify_autobuy: e.target.checked })} />
            Notify autobuy
          </label>
        </div>
        <div className="flex gap-3">
          <button onClick={saveTg} className="brut-btn" data-testid="tg-save-btn">Save</button>
          <button onClick={testTg} className="brut-btn brut-btn-secondary" data-testid="tg-test-btn">Send test message</button>
          {tg.configured && <span className="font-mono text-xs uppercase tracking-widest flex items-center gap-1 text-[#00C853]"><Check size={14} /> Telegram connected</span>}
        </div>
      </div>
    </div>
  );
}
