"""Invio notifiche su Discord, Telegram e WhatsApp."""
from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

log = logging.getLogger(__name__)


def format_message(post: dict, rule_name: str, group_name: str) -> str:
    price = post.get("price")
    price_txt = f"{price:.2f} €".replace(".", ",") if price is not None else "non indicato"
    text = (post.get("text") or "").strip()
    if len(text) > 350:
        text = text[:350].rstrip() + "…"
    lines = [
        f"🔎 Nuovo post per «{rule_name}»",
        f"Gruppo: {group_name or '—'}",
    ]
    if post.get("author"):
        lines.append(f"Autore: {post['author']}")
    lines.append(f"Prezzo: {price_txt}")
    lines += ["", text]
    if post.get("url"):
        lines += ["", post["url"]]
    return "\n".join(lines)


async def send_discord(client: httpx.AsyncClient, webhook_url: str, message: str) -> None:
    # Discord accetta al massimo 2000 caratteri nel campo content.
    resp = await client.post(webhook_url, json={"content": message[:1990]})
    resp.raise_for_status()


async def send_telegram(client: httpx.AsyncClient, token: str, chat_id: str, message: str) -> None:
    resp = await client.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": message[:4000]},
    )
    resp.raise_for_status()


async def send_whatsapp(client: httpx.AsyncClient, phone: str, apikey: str, message: str) -> None:
    # CallMeBot: servizio gratuito per inviare messaggi WhatsApp al proprio numero.
    resp = await client.get(
        "https://api.callmebot.com/whatsapp.php",
        params={"phone": phone, "text": message[:1500], "apikey": apikey},
    )
    resp.raise_for_status()


def enabled_channels(settings: dict[str, Any]) -> list[str]:
    channels = []
    if settings.get("discord_webhook_url"):
        channels.append("discord")
    if settings.get("telegram_bot_token") and settings.get("telegram_chat_id"):
        channels.append("telegram")
    if settings.get("whatsapp_phone") and settings.get("whatsapp_apikey"):
        channels.append("whatsapp")
    return channels


async def notify_all(settings: dict[str, Any], message: str,
                     client: Optional[httpx.AsyncClient] = None) -> dict[str, Optional[str]]:
    """Invia su tutti i canali configurati. Restituisce {canale: errore o None}."""
    results: dict[str, Optional[str]] = {}
    own_client = client is None
    client = client or httpx.AsyncClient(timeout=20)
    try:
        for channel in enabled_channels(settings):
            try:
                if channel == "discord":
                    await send_discord(client, settings["discord_webhook_url"], message)
                elif channel == "telegram":
                    await send_telegram(client, settings["telegram_bot_token"],
                                        settings["telegram_chat_id"], message)
                elif channel == "whatsapp":
                    await send_whatsapp(client, settings["whatsapp_phone"],
                                        settings["whatsapp_apikey"], message)
                results[channel] = None
            except Exception as exc:  # un canale che fallisce non blocca gli altri
                log.warning("Notifica %s fallita: %s", channel, exc)
                results[channel] = _safe_error(exc)
    finally:
        if own_client:
            await client.aclose()
    return results


def _safe_error(exc: Exception) -> str:
    # Non riportare l'URL completo: contiene token e webhook.
    if isinstance(exc, httpx.HTTPStatusError):
        return f"HTTP {exc.response.status_code}"
    return type(exc).__name__
