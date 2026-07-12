"""Week 5 — is low-conf citation fabrication Japan-specific or systemic?  REPORT ONLY.

No re-scrape, no re-embed, no gate change. Read-only over the existing corpus and graph.

Method (isolates ONE variable — the generate prompt):
  1. Run the real graph (clean, current code) per country -> its FINAL retrieved chunk set.
  2. On THOSE SAME chunks, re-run generate under two prompts, 3 samples each:
       CLEAN   = current Week 5 generate prompt (no disclaimer)
       LOWCONF = Week 4 generate prompt WITH the "flag LOW confidence" disclaimer
  3. Attribution: for every resolved [n], take the sentence carrying it and ask an
     independent judge whether chunk n's text actually supports that sentence.
     Structural validity (marker -> real chunk) is already guaranteed by bounds-checking;
     this measures SUBSTANTIVE support, which is the thing actually in question.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import graph.wanderrag_graph as wg

OUT = Path(__file__).parent / "week5_attribution_results.json"

COUNTRIES = [
    # (label, query, week4_claimed_citations, week4_verdict)
    ("Italy",     "What should I visit in Italy?",                     4, "flagged"),
    ("Thailand",  "What should I visit in Thailand?",                  1, "flagged"),
    ("UAE",       "What should I visit in the United Arab Emirates?",  1, "flagged"),
    ("Brazil",    "What should I visit in Brazil?",                    1, "flagged"),
    ("Mexico",    "What should I visit in Mexico?",                    3, "passed"),
    ("Singapore", "What should I visit in Singapore?",                 4, "passed"),
    ("Norway",    "What should I visit in Norway?",                    2, "passed"),
    ("Japan",     "What should I visit in Japan?",                     4, "flagged"),  # control
    ("Canada",    "What should I visit in Canada?",                    0, "flagged"),  # control
]

N_SAMPLES = 3

BASE = ("Answer the traveler's question using ONLY the numbered sources below. "
        "Cite sources inline as [n] immediately after each claim, using only the "
        "numbers shown. Do not invent sources or facts not present in the context. ")
DISCLAIMER = ("Begin your answer with one sentence flagging that confidence is LOW because "
              "the retrieved sources may not fully cover the question. ")


def numbered(chunks: list[dict]) -> str:
    return "\n\n".join(
        f"[{i+1}] source_type={c['source_type']} | country={c['country']} | "
        f"url={c['source_url']}\n{c['text'][:800]}"
        for i, c in enumerate(chunks))


def gen(query: str, chunks: list[dict], lowconf: bool) -> str:
    prompt = (BASE + (DISCLAIMER if lowconf else "")
              + f"\n\nQuestion: {query!r}\n\nSources:\n{numbered(chunks)}")
    return wg._chat("wk5_attr_gen", wg.GEN_MODEL, [{"role": "user", "content": prompt}],
                    max_tokens=700, temperature=0.3)


def resolved(answer: str, chunks: list[dict]) -> list[int]:
    return sorted({int(n) for n in re.findall(r"\[(\d+)\]", answer)
                   if 1 <= int(n) <= len(chunks)})


def claim_for(answer: str, n: int) -> str:
    """The sentence carrying marker [n]."""
    sents = re.split(r"(?<=[.!?])\s+", answer.replace("\n", " "))
    hits = [s.strip() for s in sents if f"[{n}]" in s]
    return " ".join(hits)[:400] if hits else ""


def attribute(query: str, claim: str, chunk: dict) -> dict:
    """Does the cited chunk substantively support the claim it's attached to?"""
    prompt = (
        "A RAG answer attached citation [n] to a claim. Decide whether the SOURCE TEXT "
        "actually supports that specific claim. Be strict: 'the source is about the same "
        "country' is NOT support. If the source does not contain the information the claim "
        "asserts, it does NOT support it.\n\n"
        f"Traveler's question: {query!r}\n"
        f"Claim (with its citation): {claim!r}\n\n"
        f"SOURCE TEXT:\n{chunk['text'][:1200]}\n\n"
        'Respond as JSON: {"supports": true|false, "why": "<one short sentence>"}'
    )
    raw = wg._chat("wk5_attr_judge", wg.GEN_MODEL, [{"role": "user", "content": prompt}],
                   max_tokens=150, temperature=0.0, json_mode=True)
    p = wg._parse_json(raw)
    return {"supports": bool(p.get("supports", False)), "why": str(p.get("why", ""))[:160]}


def main() -> None:
    results = {}
    for label, query, wk4_cites, wk4_verdict in COUNTRIES:
        print(f"\n{'='*90}\n{label}\n{'='*90}")

        # 1. Real graph run (clean) -> final chunk set + the answer the pipeline ships.
        state = wg.run_query(query, run_id=f"wk5_attr_{label}")
        chunks = state.get("retrieved_chunks", [])
        clean_answer = state.get("final_answer", "")
        clean_cites = state.get("citations_resolved", 0)
        print(f"  graph(clean): retries={state.get('retry_count')} "
              f"citations_resolved={clean_cites} chunks={len(chunks)}")

        # 2. Same chunks, both prompts, N samples -> citation counts.
        clean_counts, low_counts = [], []
        low_answer, low_markers = "", []
        for i in range(N_SAMPLES):
            a = gen(query, chunks, lowconf=False)
            clean_counts.append(len(resolved(a, chunks)))
            b = gen(query, chunks, lowconf=True)
            m = resolved(b, chunks)
            low_counts.append(len(m))
            if i == 0:
                low_answer, low_markers = b, m
        print(f"  CLEAN  prompt citations x{N_SAMPLES}: {clean_counts}")
        print(f"  LOWCONF prompt citations x{N_SAMPLES}: {low_counts}  (n_chunks={len(chunks)})")

        # 3. Attribution on the shipped clean answer's citations.
        clean_attr = []
        for c in state.get("citations", []):
            n = int(c["marker"].strip("[]"))
            claim = claim_for(clean_answer, n)
            a = attribute(query, claim, chunks[n - 1])
            clean_attr.append({"marker": c["marker"], "source_type": c["source_type"],
                               "claim": claim, **a})
            print(f"    CLEAN  [{n}] supports={a['supports']:<5} {a['why']}")

        # 3b. Attribution on the LOWCONF sample's citations (the Week-4-style answer).
        low_attr = []
        for n in low_markers:
            claim = claim_for(low_answer, n)
            a = attribute(query, claim, chunks[n - 1])
            low_attr.append({"marker": f"[{n}]", "source_type": chunks[n-1]["source_type"],
                             "claim": claim, **a})
            print(f"    LOWCNF [{n}] supports={a['supports']:<5} {a['why']}")

        results[label] = {
            "query": query,
            "wk4_claimed_citations": wk4_cites,
            "wk4_verdict": wk4_verdict,
            "n_chunks": len(chunks),
            "clean_graph_citations": clean_cites,
            "clean_counts_samples": clean_counts,
            "lowconf_counts_samples": low_counts,
            "clean_supported": sum(1 for a in clean_attr if a["supports"]),
            "clean_total": len(clean_attr),
            "lowconf_supported": sum(1 for a in low_attr if a["supports"]),
            "lowconf_total": len(low_attr),
            "clean_attributions": clean_attr,
            "lowconf_attributions": low_attr,
            "clean_answer": clean_answer,
            "lowconf_answer": low_answer,
        }

    OUT.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\n\nwrote {OUT}")

    # ---- summary table ----
    print("\n" + "=" * 118)
    print(f"{'country':10} {'wk4':>4} {'clean':>6} {'clean samples':>16} {'lowconf samples':>17} "
          f"{'clean supported':>16} {'lowconf supported':>18}")
    print("=" * 118)
    for k, v in results.items():
        cs = "{}/{}".format(v["clean_supported"], v["clean_total"])
        ls = "{}/{}".format(v["lowconf_supported"], v["lowconf_total"])
        print(f"{k:10} {v['wk4_claimed_citations']:>4} {v['clean_graph_citations']:>6} "
              f"{str(v['clean_counts_samples']):>16} {str(v['lowconf_counts_samples']):>17} "
              f"{cs:>16} {ls:>18}")
    print(f"\nsession cost this experiment: {wg.session_cost()}")


if __name__ == "__main__":
    main()
