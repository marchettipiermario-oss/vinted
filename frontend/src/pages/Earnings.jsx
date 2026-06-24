import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { toast } from "sonner";

export default function Earnings() {
  const [data, setData] = useState({ total_spent: 0, total_resale: 0, profit: 0, items: [] });
  const load = async () => { try { const r = await api.get("/earnings"); setData(r.data); } catch {} };
  useEffect(() => { load(); }, []);

  const save = async (id, resale, note) => {
    try { await api.post(`/autobuy/${id}/resale`, { resale_price: parseFloat(resale) || 0, note: note || "" }); toast.success("Saved"); load(); } catch { toast.error("Save failed"); }
  };

  return (
    <div className="space-y-6" data-testid="earnings-page">
      <h1 className="font-head text-4xl font-black tracking-tighter">// Earnings Tracker</h1>
      <div className="grid grid-cols-3 gap-4">
        <div className="brut-card p-4"><div className="brut-label">Spent</div><div className="font-mono text-2xl font-black">{data.total_spent}€</div></div>
        <div className="brut-card p-4"><div className="brut-label">Resale</div><div className="font-mono text-2xl font-black text-[#002FA7]">{data.total_resale}€</div></div>
        <div className="brut-card p-4"><div className="brut-label">Profit</div><div className={`font-mono text-2xl font-black ${data.profit >= 0 ? "text-[#00C853]" : "text-[#FF3B30]"}`}>{data.profit}€</div></div>
      </div>
      <div className="space-y-2">
        {data.items.length === 0 ? <div className="brut-card p-8 font-mono text-xs uppercase text-center">No autobuys yet</div> :
          data.items.map(it => (
            <div key={it.id} className="brut-card p-4 grid grid-cols-1 md:grid-cols-5 gap-3 items-center" data-testid={`earn-row-${it.id}`}>
              <div className="md:col-span-2"><div className="font-head font-bold">{it.title}</div><div className="font-mono text-[10px] text-gray-500">{it.ts}</div></div>
              <div className="font-mono text-sm">Paid: <b>{it.price}€</b></div>
              <input className="brut-input" placeholder="Resale price" defaultValue={it.resale_price || ""} onBlur={(e) => save(it.id, e.target.value, it.note)} data-testid={`earn-resale-${it.id}`} />
              <div className={`font-mono font-bold ${it.profit > 0 ? "text-[#00C853]" : it.profit < 0 ? "text-[#FF3B30]" : ""}`}>{it.profit != null ? `${it.profit}€` : "—"}</div>
            </div>
          ))}
      </div>
    </div>
  );
}
