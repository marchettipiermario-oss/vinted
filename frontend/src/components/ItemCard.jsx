import { ExternalLink, ShoppingCart, Heart } from "lucide-react";
import { api } from "@/lib/api";
import { toast } from "sonner";
import { useState } from "react";

export default function ItemCard({ item }) {
  const [buying, setBuying] = useState(false);

  const buy = async () => {
    setBuying(true);
    try {
      const { data } = await api.post("/buy", { item_id: item.id });
      if (data.success) {
        toast.success("Transaction created");
        if (data.checkout_url) window.open(data.checkout_url, "_blank");
      } else {
        toast.error(data.message || "Buy failed");
      }
    } catch (e) {
      toast.error("Buy request failed");
    } finally {
      setBuying(false);
    }
  };

  return (
    <div className="brut-card flex flex-col" data-testid={`item-card-${item.id}`}>
      <div className="border-b-2 border-black bg-gray-100 aspect-square overflow-hidden relative">
        {item.photo ? (
          <img src={item.photo} alt={item.title} className="w-full h-full object-cover" loading="lazy" />
        ) : (
          <div className="flex items-center justify-center h-full font-mono text-xs">NO IMAGE</div>
        )}
        {item.is_new && (
          <div className="absolute top-2 left-2 bg-[#FF3B30] text-white text-[10px] font-black uppercase px-2 py-1 brut-border font-mono" data-testid="item-new-badge">
            ★ NEW
          </div>
        )}
        <div className="absolute bottom-2 right-2 bg-black text-white text-[10px] font-mono px-2 py-1 brut-border font-bold">
          {item.price != null ? `${item.price.toFixed(2)} ${item.currency}` : "—"}
        </div>
      </div>
      <div className="p-3 flex-1 flex flex-col gap-2">
        <div className="font-head font-bold text-sm leading-tight line-clamp-2" title={item.title}>{item.title}</div>
        <div className="flex items-center justify-between font-mono text-[10px] uppercase text-gray-600">
          <span>{item.brand || "—"}</span>
          <span>{item.size || "—"}</span>
        </div>
        {item.seller && (
          <div className="font-mono text-[10px] uppercase text-gray-500 flex items-center gap-1">
            <Heart size={10} /> {item.favourite_count} · @{item.seller}
          </div>
        )}
        <div className="mt-auto flex gap-2 pt-2">
          {item.url && (
            <a
              href={item.url.startsWith("http") ? item.url : `https://www.vinted.it${item.url}`}
              target="_blank"
              rel="noreferrer"
              data-testid={`item-view-${item.id}`}
              className="flex-1 brut-btn brut-btn-secondary text-[10px] flex items-center justify-center gap-1 py-2"
            >
              <ExternalLink size={12} /> View
            </a>
          )}
          <button
            data-testid={`item-buy-${item.id}`}
            onClick={buy}
            disabled={buying}
            className="flex-1 brut-btn brut-btn-destructive text-[10px] flex items-center justify-center gap-1 py-2"
          >
            <ShoppingCart size={12} /> {buying ? "..." : "Buy"}
          </button>
        </div>
      </div>
    </div>
  );
}
