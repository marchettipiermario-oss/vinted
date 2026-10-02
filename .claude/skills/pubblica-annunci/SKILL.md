---
name: pubblica-annunci
description: Pubblica (o rimuove) su Subito e Facebook Marketplace gli annunci messi in coda dal VINTED.BOT, usando il browser Chrome dell'utente. Usala quando l'utente chiede di pubblicare gli annunci in coda, di svuotare la coda del crosslist, o lancia /pubblica-annunci (anche dentro /loop).
---

# Pubblica annunci in coda (Subito + Marketplace)

Il bot mette in coda gli annunci da pubblicare o rimuovere su Subito e Facebook
Marketplace. Tu fai la parte del browser: prendi un lavoro, lo esegui nel Chrome
dell'utente (dove è già loggato), comunichi l'esito al bot. Ripeti finché la coda è vuota.

## Prerequisiti (controlla una volta)

- `agent/crosslist_agent.py` configurato: deve esistere `~/.vintedbot-agent/config.json`.
  Se manca, chiedi all'utente il token da **Settings → Agente PC** del bot e l'indirizzo del
  bot, poi esegui `python agent/crosslist_agent.py setup --server <URL> --token <TOKEN>`.
  Dipendenze: `pip install -r agent/requirements.txt`.
- Un browser che puoi comandare: **Claude in Chrome** (strumenti `mcp__claude-in-chrome__*`,
  leggi prima la skill `chrome-browser`) oppure computer use. Se non hai nessuno dei due,
  fermati e spiega all'utente che deve avviare Claude Code con Chrome collegato
  (`claude --chrome`, oppure l'app desktop con l'estensione Claude in Chrome).

## Ciclo

1. Prendi il prossimo lavoro:
   ```bash
   python agent/crosslist_agent.py claim
   ```
   Stampa JSON. Se `job` è `null`, la coda è vuota: riassumi cosa hai fatto e fermati.
   Il lavoro è già segnato "in corso" nel bot: da qui in poi devi **sempre** chiuderlo con
   `report`, anche se fallisce.

2. Esegui il lavoro (`job.platform` = `subito` o `facebook`, `job.action` = `publish` o `delete`)
   seguendo le sezioni sotto. Dati in `job.listing`: `title`, `description`, `price`,
   `condition`, `condition_key`, `category`, `location`, `brand`, `size`, e per la pubblicazione
   `photo_files` (percorsi locali delle foto, già scaricate).

3. Comunica l'esito:
   ```bash
   python agent/crosslist_agent.py report <job.id> --ok --url "<link dell'annuncio o pagina finale>"
   python agent/crosslist_agent.py report <job.id> --error "<motivo breve>"
   ```

4. Torna al punto 1.

## Subito — pubblicare

1. Apri https://www.subito.it/ in una nuova scheda e premi **Inserisci annuncio**.
   Se chiede il login, fermati: chiedi all'utente di accedere e poi continua.
2. Scegli la categoria: usa `listing.category` se c'è, altrimenti quella più adatta al titolo
   (es. abbigliamento → "Abbigliamento e accessori").
3. Carica tutte le foto di `photo_files`.
4. Compila titolo, descrizione, prezzo (numero intero, senza €), condizioni (`condition`),
   comune (`location`; scegli il suggerimento corretto dell'elenco), e gli altri campi
   obbligatori deducendoli dai dati (taglia, marca…). Non inventare dati di contatto.
5. Prosegui fino alla pubblicazione. Nelle pagine "dai visibilità / promuovi" scegli **sempre
   l'opzione gratuita** ("Pubblica gratis", "Continua senza", "No grazie").
6. Successo = pagina di conferma ("annuncio inserito", "in revisione"…). Riporta come `--url`
   il link dell'annuncio se visibile, altrimenti l'URL della pagina di conferma.

## Facebook Marketplace — pubblicare

1. Apri https://www.facebook.com/marketplace/create/item. Login richiesto → chiedi all'utente.
2. Carica le foto, poi titolo, prezzo (intero), categoria (`listing.category` o la più adatta),
   condizione (`new_*` → "Nuovo"; `very_good` → "Usato - Come nuovo"; `good` → "Usato - Buone
   condizioni"; `satisfactory` → "Usato - Discrete condizioni"), descrizione, luogo (`location`).
3. **Avanti** → **Pubblica**. Non selezionare gruppi né opzioni di "boost" a pagamento.
4. Successo = la pagina lascia `/marketplace/create`. Riporta il link dell'annuncio se lo trovi
   (in `/marketplace/you/selling`), altrimenti `https://www.facebook.com/marketplace/you/selling`.

## Rimuovere (action = delete)

L'articolo è stato venduto altrove. Apri `job.url`; se non porta all'annuncio, cercalo per titolo
in "I miei annunci" (Subito) o `/marketplace/you/selling` (Facebook). Usa **Elimina** (su Subito,
se chiede il motivo, "venduto altrove"; su Facebook preferisci "Elimina annuncio" a "Segna come
venduto"). Conferma e riporta `--ok`.

## Caricare le foto

Con Claude in Chrome usa lo strumento di upload file se disponibile sul campo `input[type=file]`.
Se non puoi impostare i file, e hai computer use, usa la finestra "Apri file" del sistema con i
percorsi di `photo_files`. Se nessuna delle due strade funziona, fermati e chiedi all'utente di
trascinare le foto (dì in quale cartella sono), poi continua.

## Regole

- **Non pagare mai nulla** e non inserire dati di carte. Se l'unico modo per pubblicare è pagare,
  `report --error "richiede pagamento"`.
- **Captcha, verifica in due passaggi, avvisi dell'account**: non tentare di aggirarli. Chiedi
  all'utente di risolverli; se non risponde, `report --error`.
- Pubblica solo i dati del lavoro: non cambiare prezzo o descrizione di tua iniziativa (puoi solo
  adattare la descrizione se il sito impone un limite di lunghezza).
- Un annuncio alla volta, a ritmo normale. Se un sito segnala troppe pubblicazioni o limita
  l'account, fermati e avvisa l'utente.
- Alla fine elenca: pubblicati (con link), rimossi, falliti (con motivo).

## Automatico ogni tanto

L'utente può tenere Claude Code aperto con `/loop 15m /pubblica-annunci`.
