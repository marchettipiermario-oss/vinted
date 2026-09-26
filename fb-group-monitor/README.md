# Monitor gruppi Facebook

App web che gira sul tuo Mac, controlla a rotazione i gruppi Facebook di cui fai parte
e ti avvisa su **Discord**, **Telegram** e **WhatsApp** quando compare un post che
contiene le parole chiave che ti interessano, entro il prezzo che hai scelto.

Legge i gruppi con un browser Chrome automatizzato, usando il **tuo** account Facebook:
il login lo fai tu a mano una volta, nella finestra che si apre.

## ⚠️ Prima di usarla

- Facebook vieta nelle sue condizioni la lettura automatica dei contenuti. Il rischio
  concreto è che l'account venga **limitato o sospeso**. Se puoi, usa un account secondario.
- Le impostazioni predefinite sono prudenti: pochi gruppi per ciclo, pause casuali,
  orari di attività, un tetto di pagine al giorno. Se Facebook chiede una verifica
  di sicurezza, il monitor **si ferma da solo** e ti avvisa.
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
2. **Gruppi**: incolla i link dei gruppi (`https://www.facebook.com/groups/...`).
   Con «Aggiungi molti gruppi insieme» puoi incollarne uno per riga.
3. **Regole**: per esempio *Parole chiave* `nike, air max`, *Da escludere* `cerco, bambino`,
   *Prezzo massimo* `50`. Una regola può valere per tutti i gruppi o solo per alcuni.
4. **Impostazioni**: inserisci i canali di notifica e premi «Invia notifica di prova».
5. **Stato → «Avvia monitor»**.

La **prima lettura** di ogni gruppo salva i post già presenti senza notificarli:
li trovi in «Post trovati» con la nota *prima lettura*. Da lì in poi ricevi solo i post nuovi.

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

## Ritmo dei controlli con molti gruppi

In «Impostazioni» vedi una stima di ogni quanto viene ricontrollato ciascun gruppo.
Con 30 gruppi e i valori predefiniti (4 gruppi per ciclo, 10 minuti tra i cicli)
ogni gruppo viene riletto circa ogni 2 ore. Si può accelerare aumentando i gruppi per
ciclo o riducendo i minuti, ma cresce il rischio di blocco. Conviene disattivare i gruppi
meno utili piuttosto che forzare il ritmo.

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

I test non si collegano a Facebook: usano una pagina di prova (`tests/fixtures/group_feed.html`)
che riproduce gli attributi usati dal feed dei gruppi.

| File | Contenuto |
|---|---|
| `app/main.py` | API e server web |
| `app/monitor.py` | ciclo di controllo, rotazione, limiti, blocco in caso di verifica |
| `app/browser.py` | Chrome automatizzato con profilo persistente |
| `app/extractor.py` | lettura dei post dalla pagina del gruppo |
| `app/filters.py` | parole chiave, esclusioni, prezzo |
| `app/notifiers.py` | Discord, Telegram, WhatsApp |
| `app/db.py` | archivio SQLite in `data/monitor.db` |
| `app/static/` | interfaccia web |
