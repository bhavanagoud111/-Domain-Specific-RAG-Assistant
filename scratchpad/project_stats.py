"""A2-A5, B7, B8 — project-wide stats. READ-ONLY."""
import json, subprocess, csv, io
from collections import Counter, defaultdict
from pathlib import Path

# ---- A3. source mix ----
print("=== A3. TOURISM SOURCE MIX ===")
raw = Path("tourism_sources.csv").read_text(encoding="utf-8").splitlines()
rows = list(csv.DictReader(io.StringIO("\n".join(
    l for l in raw if l.strip() and not l.lstrip().startswith("#")))))
mix = Counter()
for r in rows:
    tag = (r.get("source_tag") or "").strip()
    url = (r.get("url") or "").lower()
    if "wikivoyage" in url: mix["wikivoyage_fallback"] += 1
    elif "state.gov" in url or "cdc.gov" in url: mix["state_dept_substitute"] += 1
    else: mix["official_board"] += 1
print(f"  CSV rows: {len(rows)}")
for k, v in sorted(mix.items(), key=lambda kv: -kv[1]): print(f"    {k:<24}{v}")
print(f"  wikivoyage countries: {sorted(r['country'] for r in rows if 'wikivoyage' in r['url'].lower())}")
subs = [r['country'] for r in rows if 'state.gov' in r['url'].lower() or 'cdc.gov' in r['url'].lower()]
print(f"  remaining substitutes: {subs or 'NONE'}")

# ---- A4. git ----
print("\n=== A4. GIT ===")
def sh(c): return subprocess.run(c, shell=True, capture_output=True, text=True).stdout.strip()
for b in ["main", "week4-investigation", "week5", "week6"]:
    n = sh(f"git rev-list --count {b} 2>/dev/null")
    print(f"  commits on {b:<22}{n or 'n/a'}")
print(f"  total tracked files : {sh('git ls-files | wc -l')}")
print(f"  remotes             : {sh('git remote -v') or 'NONE (never pushed)'}")
print(f"  unpushed branches   : {sh('git branch -vv') }")
print(f"  working tree clean? : {'yes' if not sh('git status --porcelain') else 'NO -- uncommitted changes'}")

# ---- A5. LOC by subsystem ----
print("\n=== A5. CODEBASE SIZE ===")
SUBS = {"scraping":"scraping","processing":"processing","embedding":"embedding",
        "graph":"graph","evaluation":"evaluation","storage":"storage","config":"config"}
tot_f = tot_l = 0
print(f"  {'subsystem':<16}{'modules':>9}{'LOC':>8}")
for name, d in SUBS.items():
    files = sorted(Path(d).glob("*.py")) if Path(d).exists() else []
    loc = sum(len(f.read_text(encoding='utf-8', errors='replace').splitlines()) for f in files)
    tot_f += len(files); tot_l += loc
    print(f"  {name:<16}{len(files):>9}{loc:>8}")
for f in ["app.py", "query.py", "run_pipeline.py"]:
    if Path(f).exists():
        l = len(Path(f).read_text(encoding='utf-8').splitlines())
        label = {"app.py":"UI (app.py)","query.py":"CLI (query.py)","run_pipeline.py":"orchestrator"}[f]
        tot_f += 1; tot_l += l
        print(f"  {label:<16}{1:>9}{l:>8}")
print(f"  {'TOTAL':<16}{tot_f:>9}{tot_l:>8}")

# ---- B8. retry distribution over the eval ----
print("\n=== B8. RETRY DISTRIBUTION (91-question eval, 141 runs) ===")
ev = json.load(open("evaluation/eval_results.json"))
rc = Counter(); rc_by_tier = defaultdict(Counter)
runs = 0
for r in ev["results"]:
    for run in r.get("runs", []):
        rc[run.get("retries", 0)] += 1; runs += 1
        rc_by_tier[r["corpus_tier"]][run.get("retries", 0)] += 1
print(f"  {'retries':<10}{'runs':>7}{'pct':>8}")
for k in sorted(rc): print(f"  {k:<10}{rc[k]:>7}{100*rc[k]/runs:>7.1f}%")
print(f"  {'TOTAL':<10}{runs:>7}")
print("\n  by tier:")
for t in ["rich","mid","thin","n/a"]:
    if rc_by_tier.get(t):
        c = rc_by_tier[t]; n = sum(c.values())
        print(f"    {t:<6} " + "  ".join(f"{k}retry={c[k]}({100*c[k]/n:.0f}%)" for k in sorted(c)))

# ---- B7. cost per query from logged graph calls ----
print("\n=== B7. COST PER QUERY (logged eval runs, run_id eval_*) ===")
import statistics
g = json.load(open("logs/week3_cost_log.json"))
by_run = defaultdict(float)
for e in g:
    rid = e.get("run_id") or ""
    if rid.startswith("eval_"): by_run[rid] += e.get("cost_usd") or 0.0
v = sorted(by_run.values())
if v:
    print(f"  eval runs with logged cost: {len(v)}")
    print(f"    median  ${statistics.median(v):.4f}")
    print(f"    mean    ${statistics.mean(v):.4f}")
    print(f"    p90     ${v[int(0.9*len(v))-1]:.4f}")
    print(f"    max     ${max(v):.4f}")
    print(f"    min     ${min(v):.4f}")
