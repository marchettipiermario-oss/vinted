#!/bin/bash
# Doppio clic su macOS per avviare il monitor. Al primo avvio installa tutto (qualche minuto).
set -e
cd "$(dirname "$0")"

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 non trovato. Installalo da https://www.python.org/downloads/ e riprova."
  read -r -p "Premi Invio per chiudere..."
  exit 1
fi

if [ ! -d .venv ]; then
  echo "Primo avvio: preparo l'ambiente..."
  python3 -m venv .venv
  .venv/bin/pip install --upgrade pip >/dev/null
  .venv/bin/pip install -r requirements.txt
  # Chromium di riserva, usato solo se Google Chrome non è installato.
  .venv/bin/python -m playwright install chromium
fi

.venv/bin/python -m app
