import json, re
pts = json.load(open("scratchpad/corpus_dump.json"))
jp = [p["payload"] for p in pts if p["payload"]["country"]=="Japan"]
print("Japan chunks by source_type:", {t: sum(1 for p in jp if p["source_type"]==t) for t in {p['source_type'] for p in jp}})
print("\nJapan state_dept URLs:", sorted({p["source_url"] for p in jp if p["source_type"]=="state_dept"}))
VISA = re.compile(r"visa|passport|entry requirement|90 days|blank page", re.I)
print("\n--- state_dept chunks mentioning visa/entry ---")
for p in sorted((p for p in jp if p["source_type"]=="state_dept"), key=lambda x: x["chunk_index"]):
    hits = VISA.findall(p["text"])
    if hits:
        print(f"[sd idx={p['chunk_index']}] hits={len(hits)} :: {p['text'][:300].replace(chr(10),' ')}")
        print()
