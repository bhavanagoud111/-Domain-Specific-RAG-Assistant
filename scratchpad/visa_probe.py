"""Why did the reference writer call Japan/Mexico/Israel/Italy visa questions INSUFFICIENT?"""
import json, re
from evaluation.build_eval_set import retrieve, TYPE_SOURCE

VISA = re.compile(r"visa|entry requirement|90 days|blank page|passport must be valid", re.I)
for c in ["Japan", "Mexico", "Israel", "Italy"]:
    q = f"Do I need a visa to visit {c} as a US citizen?"
    chunks = retrieve(q, c, TYPE_SOURCE["visa"])
    print("="*95)
    print(f"{c}: retrieved {len(chunks)} chunks")
    for i, ch in enumerate(chunks, 1):
        hits = len(VISA.findall(ch["text"]))
        print(f"  [{i}] {ch['source_type']:<11} score={ch['score']:.3f} visa-hits={hits:<3} :: {ch['text'][:150].replace(chr(10),' ')}")
