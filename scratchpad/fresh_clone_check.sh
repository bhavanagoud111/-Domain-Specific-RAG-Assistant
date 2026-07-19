#!/usr/bin/env bash
# Phase 5 — prove the prototype runs from a FRESH CLONE with no manual fixes.
#
# Clones the repo at HEAD into a temp dir, builds a brand-new venv, installs from
# requirements.txt, and imports/launches the real entry points. Deliberately does NOT
# reuse the working venv, the working directory, or the developer's .env.
#
# Qdrant is shared (it is a running service, not per-clone) -- the point of the check is
# that the *code and deps* install clean, not that Docker gets reinstalled.
#
#   bash scratchpad/fresh_clone_check.sh
set -uo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"
CLONE="$TMP/wanderrag"
PASS=0; FAIL=0
step() { printf '\n=== %s ===\n' "$1"; }
ok()   { echo "  PASS: $1"; PASS=$((PASS+1)); }
bad()  { echo "  FAIL: $1"; FAIL=$((FAIL+1)); }

step "1. clone HEAD into $CLONE"
git clone -q "$REPO" "$CLONE" && ok "cloned" || { bad "clone failed"; exit 1; }
cd "$CLONE"
echo "  HEAD: $(git log --oneline -1)"

step "2. .env must NOT come across in the clone"
if [ -f .env ]; then bad ".env present in a fresh clone -- it is being tracked!"; else ok ".env absent (correctly gitignored)"; fi

step "3. fresh venv + pip install -r requirements.txt"
python3 -m venv .venv >/dev/null 2>&1 || { bad "venv creation failed"; exit 1; }
if ./.venv/bin/pip install -q -r requirements.txt 2>"$TMP/pip.err"; then
  ok "pip install clean"
else
  bad "pip install failed"; tail -20 "$TMP/pip.err"
fi

step "4. imports resolve from the clone (no hidden deps)"
for mod in "config.settings" "storage.qdrant_setup" "processing.chunker" \
           "embedding.embed_and_load" "graph.wanderrag_graph" "app"; do
  if PYTHONPATH=. ./.venv/bin/python -c "import $mod" 2>"$TMP/imp.err"; then
    ok "import $mod"
  else
    bad "import $mod"; head -5 "$TMP/imp.err"
  fi
done

step "5. Qdrant reachable + frozen corpus intact"
PYTHONPATH=. ./.venv/bin/python - <<'PY'
from config import settings
from storage.qdrant_setup import get_client
n = get_client().count(collection_name=settings.QDRANT_COLLECTION, exact=True).count
print(f"  points_count = {n}")
assert n == 2319, f"EXPECTED FROZEN 2319, GOT {n}"
print("  PASS: frozen corpus intact")
PY
[ $? -eq 0 ] && PASS=$((PASS+1)) || { bad "corpus check"; }

step "6. end-to-end query through the real graph (needs a key)"
cp "$REPO/.env" .env 2>/dev/null && echo "  (copied developer .env in to exercise the live path)"
PYTHONPATH=. ./.venv/bin/python - <<'PY' 2>&1 | grep -vE "NotOpenSSL|warnings.warn|LangChain|jsonplus"
from graph.wanderrag_graph import run_query
st = run_query("What should I visit in Japan?", run_id="freshclone")
n = st.get("citations_resolved", 0)
print(f"  Japan what-to-visit -> citations={n} low_conf={bool(st.get('low_confidence'))}")
assert n > 0, "Japan resolved 0 citations in a fresh clone"
print("  PASS: end-to-end query grounded")
PY

step "7. UI imports and builds its Blocks (no launch)"
PYTHONPATH=. ./.venv/bin/python -c "
import app; assert app.demo is not None; print('  PASS: gradio app object built')
" 2>&1 | grep -vE "NotOpenSSL|warnings.warn" | tail -2

printf '\n=== RESULT: %s passed, %s failed ===\n' "$PASS" "$FAIL"
echo "clone left at: $CLONE   (rm -rf $TMP when done)"
