import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { toast } from "sonner";
import { Check, AlertTriangle } from "lucide-react";

export default function Settings() {
  const [cfg, setCfg] = useState({ domain: "www.vinted.it", cookie: "", user_agent: "", configured: false });
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        const { data } = await api.get("/vinted/config");
        setCfg(data);
      } catch { /* ignore */ }
    })();
  }, []);

  const save = async () => {
    setSaving(true);
    try {
      await api.put("/vinted/config", { domain: cfg.domain, cookie: cfg.cookie, user_agent: cfg.user_agent });
      toast.success("Config saved");
    } catch {
      toast.error("Save failed");
    } finally {
      setSaving(false);
    }
  };

  const test = async () => {
    setTesting(true);
    try {
      const { data } = await api.post("/vinted/test");
      if (data.ok) toast.success(`Connected to ${data.domain} · ${data.count} items returned`);
      else toast.error("Connection test failed. Check your cookie/domain.");
    } catch {
      toast.error("Test failed");
    } finally {
      setTesting(false);
    }
  };

  return (
    <div className="space-y-6 max-w-3xl" data-testid="settings-page">
      <div>
        <h1 className="font-head text-4xl font-black tracking-tighter">Settings</h1>
        <p className="font-mono text-xs uppercase tracking-widest text-gray-600 mt-2">
          // configure your vinted session for autobuy
        </p>
      </div>

      <div className="brut-card p-6 space-y-4">
        <h2 className="font-head text-2xl font-black tracking-tighter">// Vinted Session</h2>

        <div className="brut-border bg-yellow-50 p-3 flex gap-2 font-mono text-xs">
          <AlertTriangle size={16} className="shrink-0" />
          <div>
            <strong>How to get your cookie:</strong> Open Vinted in your browser (logged in), press F12 → Network tab → click any request to vinted → Headers → copy the <code>Cookie</code> header value and paste it below. Searches work without it but <strong>autobuy requires it</strong>.
          </div>
        </div>

        <div>
          <label className="brut-label">Vinted Domain</label>
          <select
            data-testid="vinted-domain-select"
            className="brut-input"
            value={cfg.domain}
            onChange={(e) => setCfg({ ...cfg, domain: e.target.value })}
          >
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
          <label className="brut-label">Session Cookie</label>
          <textarea
            data-testid="vinted-cookie-input"
            className="brut-input min-h-[120px]"
            value={cfg.cookie}
            onChange={(e) => setCfg({ ...cfg, cookie: e.target.value })}
            placeholder="_vinted_fr_session=...; access_token_web=...; ..."
          />
        </div>

        <div>
          <label className="brut-label">User-Agent (optional)</label>
          <input
            data-testid="vinted-ua-input"
            className="brut-input"
            value={cfg.user_agent || ""}
            onChange={(e) => setCfg({ ...cfg, user_agent: e.target.value })}
            placeholder="Mozilla/5.0 ..."
          />
        </div>

        <div className="flex gap-3 items-center flex-wrap">
          <button onClick={save} disabled={saving} className="brut-btn" data-testid="settings-save-btn">
            {saving ? "Saving..." : "Save Config"}
          </button>
          <button onClick={test} disabled={testing} className="brut-btn brut-btn-secondary" data-testid="settings-test-btn">
            {testing ? "Testing..." : "Test Connection"}
          </button>
          {cfg.configured && (
            <span className="font-mono text-xs uppercase tracking-widest flex items-center gap-1 text-[#00C853]">
              <Check size={14} /> Cookie configured
            </span>
          )}
        </div>
      </div>
    </div>
  );
}
