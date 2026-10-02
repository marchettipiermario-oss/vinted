import { useEffect, useState } from "react";
import { api, BACKEND_URL, formatApiError } from "@/lib/api";
import { toast } from "sonner";
import { Plus, Trash2, Upload, Send, Copy, ExternalLink, X, Check } from "lucide-react";

const PLATFORMS = [
  { key: "vinted", label: "Vinted", mode: "auto" },
  { key: "ebay", label: "eBay", mode: "auto" },
  { key: "subito", label: "Subito", mode: "assisted" },
  { key: "facebook", label: "Marketplace", mode: "assisted" },
];

const CONDITIONS = [
  ["new_with_tags", "Nuovo con cartellino"],
  ["new_without_tags", "Nuovo senza cartellino"],
  ["very_good", "Ottime condizioni"],
  ["good", "Buone condizioni"],
  ["satisfactory", "Discrete condizioni"],
];

const STATUS_STYLE = {
  published: ["LIVE", "bg-[#00C853] text-black"],
  manual_pending: ["DA FARE", "bg-yellow-300 text-black"],
  error: ["ERRORE", "bg-[#FF3B30] text-white"],
  ended: ["RIMOSSO", "bg-gray-300 text-black"],
  sold: ["VENDUTO", "bg-[#002FA7] text-white"],
  remove_manually: ["RIMUOVI!", "bg-orange-400 text-black"],
};

const EMPTY = {
  title: "", description: "", price: "", brand: "", size: "", condition: "very_good",
  quantity: 1, location: "", photos: [], price_overrides: {},
  ebay_category_id: "", vinted_catalog_id: "", vinted_brand_id: "", vinted_size_id: "",
  vinted_package_size_id: "", subito_category: "", facebook_category: "",
};

const abs = (url) => (url && url.startsWith("http") ? url : `${BACKEND_URL}${url}`);
const intOrNull = (v) => (v === "" || v == null ? null : parseInt(v, 10));

function Field({ label, children, className = "" }) {
  return (
    <div className={className}>
      <label className="brut-label">{label}</label>
      {children}
    </div>
  );
}

function ListingForm({ onCreated, onCancel }) {
  const [f, setF] = useState(EMPTY);
  const [previews, setPreviews] = useState([]);
  const [busy, setBusy] = useState(false);
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });
  const setOverride = (p) => (e) => setF({ ...f, price_overrides: { ...f.price_overrides, [p]: e.target.value } });

  const upload = async (e) => {
    const files = Array.from(e.target.files || []);
    if (!files.length) return;
    const fd = new FormData();
    files.forEach((file) => fd.append("files", file));
    try {
      const { data } = await api.post("/crosslist/photos", fd);
      setF((cur) => ({ ...cur, photos: [...cur.photos, ...data.map((p) => p.id)] }));
      setPreviews((cur) => [...cur, ...data]);
    } catch (err) {
      toast.error(formatApiError(err.response?.data?.detail));
    }
    e.target.value = "";
  };

  const removePhoto = (id) => {
    setF({ ...f, photos: f.photos.filter((p) => p !== id) });
    setPreviews(previews.filter((p) => p.id !== id));
  };

  const submit = async () => {
    if (!f.title || !f.price) return toast.error("Titolo e prezzo sono obbligatori");
    const overrides = Object.fromEntries(
      Object.entries(f.price_overrides).filter(([, v]) => v !== "").map(([k, v]) => [k, parseFloat(v)])
    );
    const payload = {
      ...f,
      price: parseFloat(f.price),
      quantity: parseInt(f.quantity, 10) || 1,
      price_overrides: overrides,
      vinted_catalog_id: intOrNull(f.vinted_catalog_id),
      vinted_brand_id: intOrNull(f.vinted_brand_id),
      vinted_size_id: intOrNull(f.vinted_size_id),
      vinted_package_size_id: intOrNull(f.vinted_package_size_id),
    };
    setBusy(true);
    try {
      await api.post("/crosslist/listings", payload);
      toast.success("Annuncio creato");
      onCreated();
    } catch (err) {
      toast.error(formatApiError(err.response?.data?.detail));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="brut-card p-6 space-y-4" data-testid="listing-form">
      <h2 className="font-head text-2xl font-black tracking-tighter">// Nuovo annuncio</h2>

      <div>
        <label className="brut-label">Foto</label>
        <div className="flex flex-wrap gap-2">
          {previews.map((p) => (
            <div key={p.id} className="relative w-24 h-24 brut-border bg-white">
              <img src={abs(p.url)} alt="" className="w-full h-full object-cover" />
              <button onClick={() => removePhoto(p.id)} className="absolute top-0 right-0 bg-white brut-border p-0.5"><X size={12} /></button>
            </div>
          ))}
          <label className="w-24 h-24 brut-border bg-white flex flex-col items-center justify-center cursor-pointer font-mono text-[10px] uppercase hover:bg-black hover:text-white">
            <Upload size={18} /> Aggiungi
            <input type="file" accept="image/jpeg,image/png,image/webp" multiple className="hidden" onChange={upload} data-testid="photo-input" />
          </label>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
        <Field label="Titolo" className="md:col-span-3">
          <input className="brut-input" value={f.title} onChange={set("title")} data-testid="listing-title" />
        </Field>
        <Field label="Prezzo €">
          <input className="brut-input" type="number" step="0.01" min="0" value={f.price} onChange={set("price")} data-testid="listing-price" />
        </Field>
      </div>
      <Field label="Descrizione">
        <textarea className="brut-input min-h-[110px]" value={f.description} onChange={set("description")} data-testid="listing-description" />
      </Field>
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        <Field label="Marca"><input className="brut-input" value={f.brand} onChange={set("brand")} /></Field>
        <Field label="Taglia"><input className="brut-input" value={f.size} onChange={set("size")} /></Field>
        <Field label="Condizioni">
          <select className="brut-input" value={f.condition} onChange={set("condition")}>
            {CONDITIONS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
        </Field>
        <Field label="Quantità"><input className="brut-input" type="number" min="1" value={f.quantity} onChange={set("quantity")} /></Field>
        <Field label="Città"><input className="brut-input" value={f.location} onChange={set("location")} placeholder="Milano" /></Field>
      </div>

      <details className="brut-border bg-[#F9FAFB] p-3">
        <summary className="font-mono text-xs font-bold uppercase tracking-widest cursor-pointer">Campi per piattaforma (categorie, prezzi diversi)</summary>
        <div className="space-y-4 mt-4">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            {PLATFORMS.map((p) => (
              <Field key={p.key} label={`Prezzo ${p.label}`}>
                <input className="brut-input" type="number" step="0.01" placeholder={f.price || "uguale"} value={f.price_overrides[p.key] || ""} onChange={setOverride(p.key)} />
              </Field>
            ))}
          </div>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <Field label="Vinted catalog_id *"><input className="brut-input" value={f.vinted_catalog_id} onChange={set("vinted_catalog_id")} placeholder="es. 1203" /></Field>
            <Field label="Vinted brand_id"><input className="brut-input" value={f.vinted_brand_id} onChange={set("vinted_brand_id")} /></Field>
            <Field label="Vinted size_id"><input className="brut-input" value={f.vinted_size_id} onChange={set("vinted_size_id")} /></Field>
            <Field label="Vinted pacco (1-3)"><input className="brut-input" value={f.vinted_package_size_id} onChange={set("vinted_package_size_id")} /></Field>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            <Field label="eBay categoryId"><input className="brut-input" value={f.ebay_category_id} onChange={set("ebay_category_id")} placeholder="default da Settings" /></Field>
            <Field label="Categoria Subito"><input className="brut-input" value={f.subito_category} onChange={set("subito_category")} placeholder="Abbigliamento e accessori" /></Field>
            <Field label="Categoria Marketplace"><input className="brut-input" value={f.facebook_category} onChange={set("facebook_category")} placeholder="Abbigliamento" /></Field>
          </div>
          <p className="font-mono text-[10px] text-gray-600">
            Gli ID Vinted si trovano nell'URL di una ricerca su vinted.it (es. <code>catalog[]=1203</code>, <code>brand_ids[]=10</code>).
          </p>
        </div>
      </details>

      <div className="flex gap-3">
        <button className="brut-btn" onClick={submit} disabled={busy} data-testid="listing-save">{busy ? "Salvataggio..." : "Salva annuncio"}</button>
        <button className="brut-btn brut-btn-secondary" onClick={onCancel}>Annulla</button>
      </div>
    </div>
  );
}

function CopyRow({ label, value, multiline }) {
  const copy = async () => {
    try { await navigator.clipboard.writeText(String(value ?? "")); toast.success(`${label} copiato`); }
    catch { toast.error("Copia non riuscita"); }
  };
  return (
    <div>
      <div className="flex items-center justify-between">
        <span className="brut-label">{label}</span>
        <button onClick={copy} className="font-mono text-[10px] uppercase flex items-center gap-1 hover:underline"><Copy size={12} /> copia</button>
      </div>
      <div className={`brut-border bg-white p-2 font-mono text-xs ${multiline ? "whitespace-pre-wrap max-h-40 overflow-auto" : "truncate"}`}>{value || "—"}</div>
    </div>
  );
}

function AssistPanel({ listing, platform, onClose, onDone }) {
  const [data, setData] = useState(null);
  const [url, setUrl] = useState("");
  const label = PLATFORMS.find((p) => p.key === platform)?.label;

  useEffect(() => {
    api.get(`/crosslist/listings/${listing.id}/assist/${platform}`)
      .then((r) => setData(r.data))
      .catch(() => toast.error("Caricamento non riuscito"));
  }, [listing.id, platform]);

  const markPublished = async () => {
    try {
      await api.post(`/crosslist/listings/${listing.id}/platforms/${platform}/mark`, { status: "published", url });
      toast.success(`${label}: segnato come pubblicato`);
      onDone();
    } catch { toast.error("Errore"); }
  };

  return (
    <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4" onClick={onClose}>
      <div className="brut-card bg-white p-6 space-y-3 w-full max-w-xl max-h-[90vh] overflow-auto" onClick={(e) => e.stopPropagation()} data-testid="assist-panel">
        <div className="flex items-center justify-between">
          <h3 className="font-head text-xl font-black tracking-tighter">Pubblica su {label}</h3>
          <button onClick={onClose}><X size={18} /></button>
        </div>
        <p className="font-mono text-[11px] text-gray-600">
          {label} non offre un'API pubblica per gli annunci: apri il modulo, incolla i campi e carica le foto. Poi incolla qui il link dell'annuncio.
        </p>
        {!data ? <div className="font-mono text-xs">Caricamento...</div> : (
          <>
            <a href={data.post_url} target="_blank" rel="noreferrer" className="brut-btn inline-flex items-center gap-2 text-xs"><ExternalLink size={14} /> Apri modulo {label}</a>
            <CopyRow label="Titolo" value={data.title} />
            <CopyRow label="Prezzo" value={data.price} />
            <CopyRow label="Descrizione" value={data.description} multiline />
            <div className="grid grid-cols-2 gap-3">
              <CopyRow label="Condizioni" value={data.condition} />
              <CopyRow label="Categoria" value={data.category} />
            </div>
            <CopyRow label="Città" value={data.location} />
            <div>
              <span className="brut-label">Foto (clic per scaricare)</span>
              <div className="flex flex-wrap gap-2">
                {data.photo_urls.map((u, i) => (
                  <a key={u} href={abs(u)} download={`foto-${i + 1}`} target="_blank" rel="noreferrer" className="w-16 h-16 brut-border block">
                    <img src={abs(u)} alt="" className="w-full h-full object-cover" />
                  </a>
                ))}
              </div>
            </div>
            <div className="flex gap-2 pt-2">
              <input className="brut-input" placeholder="Link annuncio pubblicato (opzionale)" value={url} onChange={(e) => setUrl(e.target.value)} />
              <button className="brut-btn brut-btn-success text-xs whitespace-nowrap flex items-center gap-1" onClick={markPublished} data-testid="assist-mark"><Check size={14} /> Pubblicato</button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function ListingCard({ listing, reload, openAssist }) {
  const [selected, setSelected] = useState(() => PLATFORMS.map((p) => p.key));
  const [busy, setBusy] = useState(false);
  const sold = listing.status === "sold";

  const toggle = (k) => setSelected(selected.includes(k) ? selected.filter((x) => x !== k) : [...selected, k]);

  const publish = async () => {
    if (!selected.length) return toast.error("Seleziona almeno una piattaforma");
    setBusy(true);
    try {
      const { data } = await api.post(`/crosslist/listings/${listing.id}/publish`, { platforms: selected });
      Object.entries(data.results).forEach(([p, r]) => {
        const label = PLATFORMS.find((x) => x.key === p)?.label;
        if (r.status === "published") toast.success(`${label}: pubblicato`);
        else if (r.status === "error") toast.error(`${label}: ${r.error}`);
      });
      reload();
    } catch (err) {
      toast.error(formatApiError(err.response?.data?.detail));
    } finally {
      setBusy(false);
    }
  };

  const markSold = async (e) => {
    const where = e.target.value;
    e.target.value = "";
    if (!where || !window.confirm("Segnare come venduto e rimuovere dalle altre piattaforme?")) return;
    try {
      const { data } = await api.post(`/crosslist/listings/${listing.id}/sold`, { sold_on: where });
      const manual = Object.entries(data.ended).filter(([, r]) => r.status === "remove_manually")
        .map(([p]) => PLATFORMS.find((x) => x.key === p)?.label || p);
      if (manual.length) toast.warning(`Rimuovi a mano da: ${manual.join(", ")}`);
      else toast.success("Venduto · rimosso dalle altre piattaforme");
      reload();
    } catch { toast.error("Errore"); }
  };

  const remove = async () => {
    if (!window.confirm("Eliminare questo annuncio dal bot? (non lo rimuove dalle piattaforme)")) return;
    try { await api.delete(`/crosslist/listings/${listing.id}`); reload(); } catch { toast.error("Errore"); }
  };

  return (
    <div className={`brut-card p-4 flex flex-col md:flex-row gap-4 ${sold ? "opacity-70" : ""}`} data-testid={`listing-${listing.id}`}>
      <div className="w-full md:w-28 h-28 brut-border bg-gray-100 shrink-0">
        {listing.photo_urls[0] && <img src={abs(listing.photo_urls[0])} alt="" className="w-full h-full object-cover" />}
      </div>
      <div className="flex-1 min-w-0 space-y-2">
        <div className="flex items-start gap-3 flex-wrap">
          <div className="font-head font-bold text-lg leading-tight flex-1 min-w-0">{listing.title}</div>
          <div className="font-mono font-black text-xl">{Number(listing.price).toFixed(2)}€</div>
        </div>
        <div className="font-mono text-[10px] uppercase text-gray-500">{listing.sku} {listing.brand && `· ${listing.brand}`} {listing.size && `· ${listing.size}`}{sold && ` · venduto su ${listing.sold_on}`}</div>
        <div className="flex flex-wrap gap-2">
          {PLATFORMS.map((p) => {
            const st = listing.platforms?.[p.key];
            const [txt, cls] = STATUS_STYLE[st?.status] || ["—", "bg-white text-black"];
            return (
              <div key={p.key} className="flex items-center brut-border font-mono text-[10px] font-bold uppercase" title={st?.error || ""}>
                {!sold && (
                  <input type="checkbox" className="mx-1" checked={selected.includes(p.key)} onChange={() => toggle(p.key)} data-testid={`pf-${listing.id}-${p.key}`} />
                )}
                <span className="px-2 py-1">{p.label}</span>
                {st?.url ? (
                  <a href={st.url} target="_blank" rel="noreferrer" className={`px-2 py-1 ${cls} flex items-center gap-1`}>{txt} <ExternalLink size={10} /></a>
                ) : (
                  <span className={`px-2 py-1 ${cls}`}>{txt}</span>
                )}
                {p.mode === "assisted" && st?.status === "manual_pending" && (
                  <button className="px-2 py-1 bg-black text-white" onClick={() => openAssist(listing, p.key)}>APRI</button>
                )}
              </div>
            );
          })}
        </div>
        {!sold && Object.entries(listing.platforms || {}).filter(([, s]) => s.error).map(([p, s]) => (
          <div key={p} className="font-mono text-[10px] text-[#FF3B30]">{p}: {s.error}</div>
        ))}
      </div>
      <div className="flex md:flex-col gap-2 shrink-0">
        {!sold && (
          <>
            <button className="brut-btn text-xs flex items-center gap-1" onClick={publish} disabled={busy} data-testid={`publish-${listing.id}`}>
              <Send size={14} /> {busy ? "..." : "Pubblica"}
            </button>
            <select className="brut-input text-xs" defaultValue="" onChange={markSold} data-testid={`sold-${listing.id}`}>
              <option value="" disabled>Venduto su…</option>
              {PLATFORMS.map((p) => <option key={p.key} value={p.key}>{p.label}</option>)}
              <option value="other">Altro</option>
            </select>
          </>
        )}
        <button className="brut-border bg-white p-2 hover:bg-[#FF3B30] hover:text-white self-start" onClick={remove}><Trash2 size={14} /></button>
      </div>
    </div>
  );
}

export default function Listings() {
  const [listings, setListings] = useState([]);
  const [showForm, setShowForm] = useState(false);
  const [assist, setAssist] = useState(null);

  const load = async () => {
    try { const { data } = await api.get("/crosslist/listings"); setListings(data); }
    catch { toast.error("Caricamento annunci non riuscito"); }
  };
  useEffect(() => { load(); }, []);

  const live = listings.filter((l) => l.status !== "sold").length;
  const todo = listings.reduce((n, l) => n + Object.values(l.platforms || {}).filter((s) => ["manual_pending", "remove_manually"].includes(s.status)).length, 0);

  return (
    <div className="space-y-6" data-testid="listings-page">
      <div className="flex items-end justify-between flex-wrap gap-4">
        <div>
          <h1 className="font-head text-4xl font-black tracking-tighter">// Crosslist</h1>
          <p className="font-mono text-xs uppercase tracking-widest text-gray-600 mt-2">
            un annuncio → vinted · ebay · subito · marketplace · {live} attivi · {todo} azioni manuali
          </p>
        </div>
        {!showForm && (
          <button className="brut-btn flex items-center gap-2" onClick={() => setShowForm(true)} data-testid="new-listing-btn"><Plus size={16} /> Nuovo annuncio</button>
        )}
      </div>

      {showForm && <ListingForm onCreated={() => { setShowForm(false); load(); }} onCancel={() => setShowForm(false)} />}

      <div className="space-y-3">
        {listings.length === 0 ? (
          <div className="brut-card p-8 font-mono text-xs uppercase text-center">Nessun annuncio · creane uno</div>
        ) : listings.map((l) => (
          <ListingCard key={l.id} listing={l} reload={load} openAssist={(listing, platform) => setAssist({ listing, platform })} />
        ))}
      </div>

      {assist && (
        <AssistPanel listing={assist.listing} platform={assist.platform} onClose={() => setAssist(null)} onDone={() => { setAssist(null); load(); }} />
      )}
    </div>
  );
}
