#!/bin/bash
# Starts LCA Wrench on this computer and opens it in the browser. Closing this window (or Ctrl+C) stops it.
cd "$(dirname "$0")"
# edition.env (only in other editions, e.g. LCA Wrench Extended): own name and port, so it runs next to LCA Wrench
NAME="LCA Wrench"; ID=""; DEFAULT_PORT=8787
if [ -f edition.env ]; then
  while IFS='=' read -r k v || [ -n "$k" ]; do
    v="${v%$'\r'}"
    case "$k" in NAME) NAME="$v" ;; ID) ID="$v" ;; PORT) DEFAULT_PORT="$v" ;; esac
  done < edition.env
fi
PORT="${PORT:-$DEFAULT_PORT}"
URL="http://127.0.0.1:$PORT"
PY=.venv/bin/python

if [ ! -x "$PY" ]; then
  echo "Run ./install.sh first."
  [ -t 0 ] && read -n 1 -s -r -p "Press any key"
  exit 1
fi
# is something already listening on the port? (Python, as lsof and ss are not everywhere)
listening() { "$PY" -c "import socket,sys; s=socket.socket(); s.settimeout(0.5); sys.exit(s.connect_ex(('127.0.0.1', $PORT)))"; }
browser() { xdg-open "$URL" >/dev/null 2>&1 || echo "Open $URL in your browser."; }
if listening; then
  echo "$NAME is already running: $URL"
  browser
  exit 0
fi

echo "$NAME: $URL"
echo "Keep this window open. Closing it (or Ctrl+C) stops $NAME."
echo "The first time a large project (ecoinvent) is opened, preparing it takes a minute or two."
export PYTHONWARNINGS="ignore::UserWarning:bw2calc,ignore::UserWarning:bw2calc.lca"
# Errors also go to lca-wrench.log (this folder): send this file if something goes wrong.
export LCA_WRENCH_LOG="$PWD/lca-wrench.log"
echo "If something goes wrong, send the file lca-wrench.log from this folder."
# opens the browser once the server answers (a fixed wait was too short on slow computers)
( for _ in $(seq 240); do listening && break; sleep 0.5; done; browser ) &
exec "$PY" -m uvicorn lca_wrench.api:app --host 127.0.0.1 --port "$PORT" --log-level warning
