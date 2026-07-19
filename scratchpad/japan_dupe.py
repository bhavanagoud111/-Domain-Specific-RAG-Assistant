import json, re
from difflib import SequenceMatcher
pts = json.load(open("scratchpad/corpus_dump.json"))
jp = [p["payload"] for p in pts if p["payload"]["country"]=="Japan"]
tour = sorted([p for p in jp if p["source_type"]=="tourism"], key=lambda x: x["chunk_index"])
sd   = sorted([p for p in jp if p["source_type"]=="state_dept"], key=lambda x: x["chunk_index"])

def norm(t): return re.sub(r"\s+", " ", t).strip().lower()

print(f"tourism={len(tour)} state_dept={len(sd)}")
print("\nBest state_dept match for each tourism chunk (similarity):")
covered = 0
for t in tour:
    best = max(sd, key=lambda s: SequenceMatcher(None, norm(t["text"]), norm(s["text"])).ratio())
    r = SequenceMatcher(None, norm(t["text"]), norm(best["text"])).ratio()
    covered += r >= 0.60
    print(f"  tour idx={t['chunk_index']:>2} -> sd idx={best['chunk_index']:>2}  sim={r:.2f}")
print(f"\ntourism chunks with a >=0.60-similar state_dept twin: {covered}/{len(tour)}")

# Is there ANY "what to visit" content in Japan's tourism chunks?
VISIT = re.compile(r"temple|shrine|museum|festival|itinerary|sightsee|attraction|must-see|things to do|garden|castle|onsen|Mount Fuji|Kyoto|neighbourhood|neighborhood", re.I)
print("\nJapan tourism chunks containing any 'what to visit' vocabulary:")
for t in tour:
    h = VISIT.findall(t["text"])
    if h: print(f"  idx={t['chunk_index']}: {set(h)}")
print("  (none)" if not any(VISIT.findall(t["text"]) for t in tour) else "")
