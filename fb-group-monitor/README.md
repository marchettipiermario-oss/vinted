# Monitor gruppi Facebook

App web che gira sul tuo Mac, tiene d'occhio i gruppi Facebook di cui fai parte
e ti avvisa su **Discord**, **Telegram** e **WhatsApp**, di solito **entro un minuto**,
quando compare un post con le parole chiave che ti interessano, entro il prezzo che hai scelto.

## Come fa a essere veloce

Aprire 20+ gruppi uno per uno ogni minuto significherebbe migliaia di pagine al giorno:
Facebook bloccherebbe l'account in fretta. L'app usa invece **le notifiche di Facebook**:

1. Su ogni gruppo imposti le notifiche su **Tutti i post**.
2. L'app ricarica **una sola pagina**, facebook.com/notifications, ogni ~40 secondi.
3. Per ogni notifica di un post nuovo apre **solo quel post**, legge testo e prezzo,
   applica le regole e ti manda il messaggio.
4. Se Facebook raggruppa le notifiche («Luca e altre 5 persone hanno pubblicato in…»),
   apre subito quel gruppo e legge i post più recenti.

Una **scansione a rotazione** dei gruppi resta attiva come rete di sicurezza, per i post
di cui Facebook non manda la notifica.

Legge i gruppi con un browser Chrome automatizzato, usando il **tuo** account Facebook:
il login lo fai tu a mano una volta, nella finestra che si apre.

## ⚠️ Prima di usarla

- Facebook vieta nelle sue condizioni la lettura automatica dei contenuti. Il rischio
  concreto è che l'account venga **limitato o sospeso**. Se puoi, usa un account secondario.
- La modalità veloce carica poche pagine (le notifiche e i soli post nuovi), con pause
  casuali e un tetto di pagine al giorno. Se Facebook chiede una verifica di sicurezza,
  il monitor **si ferma da solo** e ti avvisa.
- Deve girare sul tuo computer, non su un server: un login da un datacenter fa
  scattare subito i controlli di Facebook.

## Installazione (macOS)

Serve **Python 3.10 o più recente** (<https://www.python.org/downloads/>) e, consigliato,
**Google Chrome**.

1. Scarica il progetto:
   ```bash
   git clone https://github.com/marchettipiermario-oss/vinted.git
   cd vinted/fb-group-monitor
   ```
2. Fai doppio clic su **`avvia.command`**. Se macOS lo blocca: tasto destro → Apri → Apri.
   In alternativa, da Terminale: `./avvia.command`.

Al primo avvio installa le dipendenze (qualche minuto). Poi apre l'interfaccia
su <http://127.0.0.1:8000>.

Avvio manuale, se preferisci:
```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m playwright install chromium   # solo se non hai Chrome
.venv/bin/python -m app
```

## Primo utilizzo

1. **Stato → «Apri Facebook per il login»**: si apre Chrome, accedi al tuo account.
   Il login resta salvato in `data/browser-profile`.
2. **Su Facebook**, per ogni gruppo: apri il gruppo → icona della campanella (o «…» →
   Gestisci notifiche) → **Tutti i post**. È questo che rende l'app immediata.
3. **Gruppi** (facoltativo): i gruppi da cui arrivano notifiche vengono aggiunti da soli.
   Aggiungi a mano, e lascia con «Scansione» attiva, i gruppi che vuoi ricontrollare anche
   a rotazione. Con «Aggiungi molti gruppi insieme» puoi incollarne uno per riga.
4. **Regole**: per esempio *Parole chiave* `nike, air max`, *Da escludere* `cerco, bambino`,
   *Prezzo massimo* `50`. Una regola può valere per tutti i gruppi o solo per alcuni.
5. **Impostazioni**: inserisci i canali di notifica e premi «Invia notifica di prova».
6. **Stato → «Avvia monitor»**.

Al primo avvio le notifiche già presenti, e la prima lettura di ogni gruppo, vengono
memorizzate senza notificarle. Da lì in poi ricevi solo i post nuovi.

Lascia aperta la finestra del Terminale e quella di Chrome (puoi ridurla a icona).
Se il Mac va in stop il monitor si ferma: `caffeinate -i ./avvia.command` lo tiene sveglio.

## Come funzionano i filtri

- **Parole chiave**: separate da virgola, basta che ne compaia **una**. Maiuscole e accenti
  non contano. Una frase come `air max` deve comparire intera.
- **Parole da escludere**: se ne compare anche solo una, il post viene scartato
  (utile per `cerco`, `scambio`, `rotto`).
- **Prezzo**: riconosce `45€`, `€ 45`, `45 euro`, `12,50 €`, `1.200 €`, `prezzo: 80`.
  Se il post non indica un prezzo passa comunque, a meno che tu non spunti
  «Scarta i post senza prezzo».

## Notifiche

| Canale | Cosa serve |
|---|---|
| Discord | Canale → Modifica canale → Integrazioni → Webhook → Nuovo webhook → Copia URL |
| Telegram | Crea un bot con **@BotFather** (ti dà il token), scrivigli un messaggio, poi ricava il tuo chat ID con **@userinfobot** |
| WhatsApp | Usa [CallMeBot](https://www.callmebot.com/blog/free-api-whatsapp-messages/), gratuito: invia «I allow callmebot to send me messages» al numero indicato sul sito e ricevi la API key. Manda messaggi solo al tuo numero |

Per WhatsApp verso più persone o con più volume serve un servizio a pagamento
(Twilio o WhatsApp Business Cloud API): si può aggiungere in `app/notifiers.py`.

## Velocità e rischio

| Impostazione | Predefinito | Effetto |
|---|---|---|
| Controlla le notifiche ogni | 40 s | Ritardo massimo tra la notifica di Facebook e il tuo avviso (più ~10 s per aprire il post). Minimo 15 s |
| Apri il post | sì | Legge testo completo e prezzo. Se lo togli filtra solo sull'anteprima della notifica: qualche secondo più veloce, ma meno preciso |
| Scansione a rotazione | 5 gruppi ogni 15 min | Rete di sicurezza. Puoi spingerla fino a pause di 3 s e giri ogni minuto, ma è il modo più rapido per farsi limitare l'account |
| Limite pagine al giorno | 1500 | Gruppi e post aperti; la pagina notifiche non conta |

In «Impostazioni» trovi una stima dei tempi con i valori scelti.

Limiti da conoscere:
- La velocità dipende da Facebook: di solito la notifica arriva in pochi secondi,
  ma con gruppi molto attivi Facebook può raggrupparle o ritardarle. In quel caso interviene
  la lettura del gruppo o la scansione a rotazione.
- Facebook a volte riporta da solo le notifiche di un gruppo a «In evidenza». Se da un
  gruppo smettono di arrivare avvisi, ricontrolla la campanella.

## Se qualcosa non va

- **«Feed non trovato: sei iscritto al gruppo?»**: apri il gruppo nella finestra di
  Chrome e controlla di esserne membro.
- **Il monitor si è messo in pausa da solo**: Facebook ha chiesto una verifica o la sessione
  è scaduta. Premi «Apri Facebook per il login», risolvi nella finestra, poi «Avvia monitor».
- **Nessun post trovato ma i gruppi sono «ok»**: Facebook può aver cambiato la struttura
  della pagina. La logica di lettura è tutta in `app/extractor.py`.

## Sviluppo

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest
```

I test non si collegano a Facebook: usano pagine di prova (`tests/fixtures/`) che riproducono
gli attributi usati da feed dei gruppi, pagina notifiche e singolo post.

| File | Contenuto |
|---|---|
| `app/main.py` | API e server web |
| `app/monitor.py` | scheduler: notifiche, rotazione, limiti, blocco in caso di verifica |
| `app/browser.py` | Chrome automatizzato con profilo persistente |
| `app/extractor.py` | lettura di feed dei gruppi, pagina notifiche e singoli post |
| `app/filters.py` | parole chiave, esclusioni, prezzo |
| `app/notifiers.py` | Discord, Telegram, WhatsApp |
| `app/db.py` | archivio SQLite in `data/monitor.db` |
| `app/static/` | interfaccia web |
