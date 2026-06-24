import { useState } from "react";

const DEFAULT = {
  name: "",
  keyword: "",
  brand_ids: "",
  catalog_ids: "",
  size_ids: "",
  color_ids: "",
  status_ids: "",
  price_from: "",
  price_to: "",
  currency: "EUR",
  order: "newest_first",
  autobuy: false,
  max_autobuy_price: "",
};

export default function SearchForm({ initial = {}, onSubmit, onCancel, submitLabel = "Save Search" }) {
  const [form, setForm] = useState({ ...DEFAULT, ...initial });
  const upd = (k, v) => setForm((f) => ({ ...f, [k]: v }));

  const submit = (e) => {
    e.preventDefault();
    const payload = {
      ...form,
      price_from: form.price_from === "" ? null : Number(form.price_from),
      price_to: form.price_to === "" ? null : Number(form.price_to),
      max_autobuy_price: form.max_autobuy_price === "" ? null : Number(form.max_autobuy_price),
    };
    onSubmit(payload);
  };

  const field = (key, label, props = {}) => (
    <div>
      <label className="brut-label">{label}</label>
      <input
        data-testid={`form-${key}`}
        className="brut-input"
        value={form[key] ?? ""}
        onChange={(e) => upd(key, e.target.value)}
        {...props}
      />
    </div>
  );

  return (
    <form onSubmit={submit} className="brut-card p-6 space-y-4" data-testid="search-form">
      <h2 className="font-head text-2xl font-black tracking-tighter">// New Hunt</h2>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {field("name", "Search Name *", { required: true, placeholder: "e.g. Nike AF1 Under 30€" })}
        {field("keyword", "Keyword", { placeholder: "nike air force 1" })}
        {field("brand_ids", "Brand IDs (comma sep)", { placeholder: "53,304" })}
        {field("catalog_ids", "Catalog IDs", { placeholder: "1452" })}
        {field("size_ids", "Size IDs", { placeholder: "207,208" })}
        {field("color_ids", "Color IDs", { placeholder: "" })}
        {field("status_ids", "Condition IDs", { placeholder: "6,1,2" })}
        <div className="grid grid-cols-2 gap-2">
          {field("price_from", "Price From", { type: "number", step: "0.01" })}
          {field("price_to", "Price To", { type: "number", step: "0.01" })}
        </div>
        <div>
          <label className="brut-label">Currency</label>
          <select className="brut-input" data-testid="form-currency" value={form.currency} onChange={(e) => upd("currency", e.target.value)}>
            <option>EUR</option><option>USD</option><option>GBP</option><option>PLN</option>
          </select>
        </div>
        <div>
          <label className="brut-label">Order</label>
          <select className="brut-input" data-testid="form-order" value={form.order} onChange={(e) => upd("order", e.target.value)}>
            <option value="newest_first">Newest first</option>
            <option value="price_low_to_high">Price ↑</option>
            <option value="price_high_to_low">Price ↓</option>
            <option value="relevance">Relevance</option>
          </select>
        </div>
      </div>

      <div className="brut-border bg-black text-white p-4 space-y-3">
        <div className="flex items-center justify-between">
          <div>
            <div className="font-head text-lg font-black tracking-tight">⚠ AUTOBUY MODE</div>
            <div className="font-mono text-xs opacity-80">Automatically attempt purchase when a matching item appears.</div>
          </div>
          <button
            type="button"
            data-testid="form-autobuy-toggle"
            onClick={() => upd("autobuy", !form.autobuy)}
            className={`brut-border px-4 py-2 font-mono text-xs font-bold uppercase tracking-widest ${form.autobuy ? "bg-[#00C853] text-black" : "bg-white text-black"}`}
          >
            {form.autobuy ? "ARMED" : "DISARMED"}
          </button>
        </div>
        {form.autobuy && (
          <div>
            <label className="brut-label text-white">Max Auto-Buy Price (€) — leave empty for unlimited</label>
            <input
              data-testid="form-max-autobuy-price"
              className="brut-input"
              type="number"
              step="0.01"
              value={form.max_autobuy_price}
              onChange={(e) => upd("max_autobuy_price", e.target.value)}
              placeholder="25.00"
            />
          </div>
        )}
      </div>

      <div className="flex gap-3">
        <button type="submit" className="brut-btn" data-testid="form-submit-btn">{submitLabel}</button>
        {onCancel && <button type="button" onClick={onCancel} className="brut-btn brut-btn-secondary" data-testid="form-cancel-btn">Cancel</button>}
      </div>
    </form>
  );
}
