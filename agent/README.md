# Agente PC — Subito + Facebook Marketplace

Subito e Facebook Marketplace non hanno un'API pubblica per pubblicare annunci.
Questo agente gira **sul tuo computer**, usa un profilo Chrome dedicato in cui hai
fatto login una volta, e pubblica/rimuove gli annunci che metti in coda dal bot.

## Installazione (una volta)

Serve Python 3.10+.

```bash
cd agent
pip install -r requirements.txt
playwright install chromium        # usato se Google Chrome non è installato
```

1. Nel bot: **Settings → Agente PC → Genera token**.
2. `python crosslist_agent.py setup --server https://indirizzo-del-bot --token <TOKEN>`
3. `python crosslist_agent.py login` → si apre il browser dell'agente: accedi a Subito e
   Facebook, poi premi Invio nel terminale. I login restano salvati in `~/.vintedbot-agent/profile`.

## Uso

```bash
python crosslist_agent.py run
```

Lascialo acceso: ogni 10 secondi chiede al bot se ci sono annunci da pubblicare o
rimuovere (quando segni "Venduto su…"). Opzioni:

- `--human-timeout 600` — se il sito mostra un captcha, un campo nuovo o la pagina di
  login, l'agente mette una **barra gialla** in alto e aspetta fino a 10 minuti che
  completi tu quel passaggio; poi continua da solo. `0` = non aspettare, segna errore.
- `--once` — esegue i lavori in coda ed esce (utile con un'operazione pianificata).
- `--headless` — browser invisibile (sconsigliato: niente barra gialla e più captcha).

## Oppure: fai fare tutto a Claude Code

Invece di `run`, puoi far pubblicare gli annunci a Claude Code, che legge le pagine come
una persona e si adatta quando Subito o Facebook cambiano i moduli.

1. Fai `setup` come sopra (serve il token).
2. Apri Claude Code nella cartella del progetto con il tuo Chrome collegato:
   `claude --chrome` (estensione **Claude in Chrome** installata) oppure l'app desktop.
3. Scrivi `/pubblica-annunci` → Claude prende ogni annuncio in coda
   (`crosslist_agent.py claim`), lo pubblica nel tuo Chrome e comunica l'esito al bot
   (`crosslist_agent.py report`).
4. Per farlo in automatico: `/loop 15m /pubblica-annunci`.

Le regole che Claude segue (mai pagare, opzioni gratuite, si ferma su captcha e login)
sono in `.claude/skills/pubblica-annunci/SKILL.md`.

## Cosa fa e cosa non fa

- Compila titolo, descrizione, prezzo, categoria, condizioni, comune e carica le foto.
- Sulle pagine "dai visibilità al tuo annuncio" sceglie sempre l'opzione **gratuita**;
  se una pagina chiede un pagamento si ferma e lascia decidere a te.
- I siti cambiano spesso i loro moduli: i campi vengono cercati per etichetta (come li
  vedi tu), non per codice interno, quindi reggono a molti cambiamenti, ma non a tutti.
  Quando qualcosa non torna, interviene la barra gialla.
- L'automazione dei propri annunci non è prevista dai termini d'uso di Facebook e Subito:
  usa un ritmo normale (qualche annuncio al giorno), non centinaia.
