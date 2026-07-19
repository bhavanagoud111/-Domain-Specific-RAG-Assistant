"""Dump the full Qdrant corpus payloads to a local JSON for offline audit (read-only)."""
import json, requests

URL = "http://localhost:6333/collections/wanderrag_chunks/points/scroll"
pts, offset = [], None
while True:
    body = {"limit": 500, "with_payload": True, "with_vector": False}
    if offset is not None:
        body["offset"] = offset
    r = requests.post(URL, json=body, timeout=60).json()["result"]
    pts.extend(r["points"])
    offset = r.get("next_page_offset")
    if offset is None:
        break
print("points dumped:", len(pts))
json.dump(pts, open("scratchpad/corpus_dump.json", "w"))
