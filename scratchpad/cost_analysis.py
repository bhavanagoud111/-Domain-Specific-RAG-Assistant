"""Whole-project OpenRouter spend, reconciled across every cost log. READ-ONLY."""
import json
from collections import defaultdict

RATE = 0.13 / 1_000_000  # text-embedding-3-large USD/token

# ---- 1. ingestion embeddings (embed_cost_log.json) ----
emb = json.load(open("logs/embed_cost_log.json"))
emb_by_date = defaultdict(lambda: {"tokens": 0, "chunks": 0, "batches": 0})
for e in emb:
    d = e["timestamp"][:10]
    emb_by_date[d]["tokens"] += e["batch_tokens"]
    emb_by_date[d]["chunks"] += e["batch_chunks"]
    emb_by_date[d]["batches"] += 1

print("=== A1a. INGESTION EMBEDDINGS (logs/embed_cost_log.json) ===")
print(f"{'date':<13}{'batches':>9}{'chunks':>9}{'tokens':>11}{'cost_usd':>11}")
tot_t = 0
for d in sorted(emb_by_date):
    v = emb_by_date[d]
    tot_t += v["tokens"]
    print(f"{d:<13}{v['batches']:>9}{v['chunks']:>9}{v['tokens']:>11,}{v['tokens']*RATE:>11.4f}")
print(f"{'TOTAL':<13}{'':>9}{'':>9}{tot_t:>11,}{tot_t*RATE:>11.4f}")
ingestion_cost = tot_t * RATE

# ---- 2. graph calls (week3_cost_log.json) ----
g = json.load(open("logs/week3_cost_log.json"))
by_date = defaultdict(lambda: {"cost": 0.0, "calls": 0, "tok": 0})
by_model = defaultdict(lambda: {"cost": 0.0, "calls": 0})
by_node = defaultdict(lambda: {"cost": 0.0, "calls": 0})
by_run = defaultdict(float)
for e in g:
    d = e["timestamp"][:10]
    c = e.get("cost_usd") or 0.0
    by_date[d]["cost"] += c; by_date[d]["calls"] += 1
    by_date[d]["tok"] += e.get("total_tokens") or 0
    by_model[e["model"]]["cost"] += c; by_model[e["model"]]["calls"] += 1
    by_node[e["node"]]["cost"] += c; by_node[e["node"]]["calls"] += 1
    by_run[e.get("run_id") or "?"] += c

print("\n=== A1b. GRAPH CALLS (logs/week3_cost_log.json) ===")
print(f"{'date':<13}{'calls':>8}{'tokens':>11}{'cost_usd':>11}")
graph_cost = 0.0
for d in sorted(by_date):
    v = by_date[d]; graph_cost += v["cost"]
    print(f"{d:<13}{v['calls']:>8}{v['tok']:>11,}{v['cost']:>11.4f}")
print(f"{'TOTAL':<13}{sum(v['calls'] for v in by_date.values()):>8}"
      f"{sum(v['tok'] for v in by_date.values()):>11,}{graph_cost:>11.4f}")

print("\n  by model:")
for m, v in sorted(by_model.items(), key=lambda kv: -kv[1]["cost"]):
    print(f"    {m:<34}{v['calls']:>7} calls  ${v['cost']:.4f}")
print("  by node:")
for n, v in sorted(by_node.items(), key=lambda kv: -kv[1]["cost"]):
    print(f"    {n:<34}{v['calls']:>7} calls  ${v['cost']:.4f}")

print(f"\n=== TOTALS ===")
print(f"  ingestion embeddings : ${ingestion_cost:.4f}")
print(f"  graph (chat+embed)   : ${graph_cost:.4f}")
print(f"  LOGGED GRAND TOTAL   : ${ingestion_cost + graph_cost:.4f}")

json.dump({"ingestion": ingestion_cost, "graph": graph_cost,
           "by_date_graph": {d: v["cost"] for d, v in by_date.items()},
           "by_date_embed": {d: v["tokens"]*RATE for d, v in emb_by_date.items()},
           "by_run": dict(by_run)},
          open("scratchpad/cost_summary.json", "w"), indent=2)
