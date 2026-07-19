import json, re
from collections import defaultdict
pts = json.load(open("scratchpad/corpus_dump.json"))
TARGETS = {"Argentina", "Peru", "United Kingdom", "Vietnam", "Japan"}
STATE_PAT=[r"travel\.state\.gov",r"Travel Advisory \|",r"Smart Traveler Enrollment Program",r"\bSTEP\b",r"Reconsider [Tt]ravel",r"Exercise [Ii]ncreased [Cc]aution",r"Do Not Travel",r"Level [1-4]:",r"Bureau of Consular Affairs",r"U\.S\. Embassy",r"Country Summary"]
CDC_PAT=[r"wwwnc\.cdc\.gov",r"Centers for Disease Control",r"Travelers.{0,3} Health",r"CDC recommends",r"routine vaccines",r"Talk to your doctor about",r"before you travel",r"Clinician view",r"vaccine-preventable"]
S_RE=re.compile("|".join(STATE_PAT),re.I); C_RE=re.compile("|".join(CDC_PAT),re.I)
for p in pts:
    pl=p["payload"]
    if pl["country"] not in TARGETS or pl["source_type"]!="tourism": continue
    txt=pl.get("text","") or ""
    s=S_RE.findall(txt); c=C_RE.findall(txt)
    if len(s)>=2 or len(c)>=2 or "state.gov" in (pl.get("source_url") or "").lower():
        print("="*90)
        print(f"{pl['country']} | chunk_index={pl['chunk_index']} | url={pl.get('source_url')}")
        print(f"  state-hits={s[:5]}  cdc-hits={c[:5]}")
        print("  TEXT:", txt[:600].replace("\n"," "))
