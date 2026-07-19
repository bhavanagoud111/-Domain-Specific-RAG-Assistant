# Week 6 — fixes

Branch `week6-fixes` off `week6`. Corpus stays **FROZEN at 2,319** throughout.
`processing/cleaner.py` deliberately untouched (fixing it needs re-scraping + re-embedding,
which would invalidate every measured number).

---

## PHASE 1 — ENVIRONMENT (no code changed)

### Diagnosis: 8 dangling symlinks, not 1

Docker Desktop is installed and healthy. The problem is purely that `/usr/local/bin` is full
of symlinks into `/Volumes/Docker/...` — the **install DMG**, which is no longer mounted.
This happens when Docker Desktop is run once from the mounted disk image before being copied
to `/Applications`; the installer writes symlinks pointing at the DMG path.

| symlink in `/usr/local/bin` | state | in app bundle? |
|---|---|---|
| `docker` | BROKEN | ✅ present |
| `docker-compose` | BROKEN | ❌ not present (see note) |
| `docker-credential-desktop` | BROKEN | ✅ present |
| `docker-credential-osxkeychain` | BROKEN | ✅ present |
| `cagent` | BROKEN | ✅ present |
| `hub-tool` | BROKEN | ✅ present |
| `kubectl` | BROKEN | ✅ present |
| `kubectl.docker` | BROKEN | ✅ present |

**The real binary lives at `/Applications/Docker.app/Contents/Resources/bin/docker`** and is
executable. Verified directly:

```
$ /Applications/Docker.app/Contents/Resources/bin/docker --version
Docker version 29.2.1, build a5c7197

$ /Applications/Docker.app/Contents/Resources/bin/docker compose version
Docker Compose version v5.0.2
```

**Note on `docker-compose`:** the standalone v1 shim is genuinely absent from the bundle,
and it does not matter. Compose v2 ships as a CLI *plugin* invoked as the `docker compose`
subcommand, which already resolves correctly through the bundled `docker` binary (verified
above). Nothing in this project calls `docker-compose` with a hyphen — `README.md` and
`docker-compose.yml` both use `docker compose`.

### Recommended fix — PATH, no sudo (preferred)

This fixes **all eight** at once, survives Docker Desktop upgrades, and needs no admin
rights:

```bash
echo 'export PATH="/Applications/Docker.app/Contents/Resources/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc
```

The bundle bin directory is currently referenced in **no** shell profile
(`~/.zshrc`, `~/.zprofile`, `~/.bash_profile` all checked), so this is a clean addition.

### Alternative — repoint the symlink (needs sudo, fixes only `docker`)

```bash
sudo ln -sf /Applications/Docker.app/Contents/Resources/bin/docker /usr/local/bin/docker
```

`/usr/local/bin/docker` is owned by `root:wheel`, hence the `sudo`. This leaves the other
seven symlinks broken — fine for this project, but the PATH approach is strictly better.

*Both commands are for you to run; I have not modified anything outside the repo.*

### Verification — all three checks pass

| check | result |
|---|---|
| `docker ps` | `wanderrag-qdrant` · `qdrant/qdrant:latest` · **Up 2 hours** · `0.0.0.0:6333-6334->6333-6334/tcp` |
| `docker compose version` | **v5.0.2** |
| `docker compose ps` (in repo) | service `qdrant`, created 4 weeks ago, **Up 2 hours** |
| `curl .../collections/wanderrag_chunks` | **`points_count = 2319`**, `status = green`, `dim = 3072` |

**The frozen corpus is intact and the container is healthy.** Nothing was reinstalled,
restarted, or re-ingested.

### Risk note

The container has been up 2 hours against a 4-week-old creation date, so it *has* been
restarted at some point — meaning the volume (`qdrant_storage`) is persisting correctly and
a restart is survivable. That materially lowers the risk I flagged earlier: the corpus is on
a named Docker volume, not only in a running container's memory. Once the PATH fix is
applied, `docker compose up -d` can bring it back if it ever stops.

---

## PHASE 2 — UI FIXES (committed `8256883`)

### 2a. Live corpus count

`app.py` hardcoded `"50 countries, 2,220 chunks"`, which went stale the moment Japan's
source was replaced. Replaced with `_corpus_stats()`, which reads `points_count` live from
Qdrant at startup — now renders **2,319**. Falls back to `—` rather than raising, so the UI
still starts if Qdrant is down (a wrong number is worse than no number).

### 2b. `scrape_date` rendered (proposal Risk 3)

Carried `retrieve_node → generate_node → citation dict` and rendered in `_render_sources`:

```
- [1]  Tourism board · Japan  →  en.wikivoyage.org   scraped 2026-07-19   score 0.675
- [2]  US State Dept · Italy  →  travel.state.gov    scraped 2026-06-28   score 0.55
```

**Confirmed metadata-only, by inspection rather than assertion:**

* the `generate` prompt is built from `source_type`, `country`, `url`, `text` only — so
  `scrape_date` **never enters the LLM input**;
* `grep scrape_date` finds exactly **three** reads in the codebase: the two metadata carries
  and the UI render;
* retrieval, ranking, country filter, `TOP_K`, the gate and `MAX_RETRIES` are untouched;
* the gate keys on `len(citations)` — adding a key to each dict cannot change it;
* asserted that the string `scrape_date` never appears in any answer text.

Three-query re-check — **all gate verdicts identical to the Week 6 baseline**:

| query | citations | gate | baseline |
|---|---|---|---|
| Japan what-to-visit | 4 | pass | 5, pass |
| Canada what-to-visit | 0 | fail + `low_confidence` | 0, fail |
| Italy what-to-visit | 6 | pass | 6, pass |

Japan returned 4 markers rather than 5 — `temperature=0.3` variance in how many markers
gpt-4o emits. The **gate verdict** is what is being held constant, and it is unchanged.

---

## PHASE 3 — REWRITER FIX + FULL RE-EVAL

### 3a. The change (2 lines of logic, 0 removed)

```python
    if original not in subs:
        subs = subs + [original]
```

Deliberately **additive**: the rewriter's source-oriented sub-queries are kept, so the
candidate pool can only widen. `TOP_K`, the country filter, chunking, the gate and
`MAX_RETRIES` are all unchanged. Kept on retries too, since a retry means the previous pass
resolved 0 citations — precisely when the literal question is most worth trying.

Smoke test confirmed it lands: Singapore's sub-queries became
`['Singapore tourism attractions', 'Singapore travel advisories', 'Singapore CDC health
notices', 'What should I visit in Singapore?']`.

### 3b. Corpus

**FROZEN at 2,319 throughout.** No re-scrape, no re-embed. `eval_set.json` byte-identical
(sha256 `80fbd1020e62cb29`), same 91 questions / 24 countries, same blinded
`anthropic/claude-sonnet-4.5` judge, same 3× sampling for thin + unanswerable.

### 3c. BEFORE / AFTER — **precision did not improve**

| scope | Qs | precision before → after | faithfulness | gate | country |
|---|---:|---|---|---|---|
| **ALL** | 91 | **44.2% → 44.2% (−0.0)** | 87.0% → 85.7% (−1.3) | 97.1% → 97.8% (+0.7) | 100% → 100% |
| rich | 39 | 45.1% → 46.0% (+0.9) | 86.7% → 85.6% (−1.1) | 94.9% → 97.4% (+2.6) | 100% → 100% |
| mid | 27 | 48.8% → 49.7% (+0.9) | 90.6% → 85.8% (−4.9) | 100% → 100% | 100% → 100% |
| thin | 20 | 47.4% → 44.2% (−3.2) | 82.6% → 85.9% (+3.3) | 96.7% → 95.0% (−1.7) | 100% → 100% |
| visa | 17 | 22.3% → 26.1% (+3.8) | 84.4% → 81.0% (−3.4) | 88.2% → 94.1% (+5.9) | 100% → 100% |
| health | 23 | 53.7% → 51.1% (−2.6) | 90.5% → 87.4% (−3.1) | 100% → 100% | 100% → 100% |
| safety | 23 | 62.9% → 63.8% (+0.9) | 90.8% → 89.8% (−1.0) | 100% → 100% | 100% → 100% |
| what_to_visit | 23 | 41.9% → 40.5% (−1.3) | 81.3% → 83.0% (+1.7) | 97.1% → 95.7% (−1.4) | 100% → 100% |
| unanswerable | 5 | 0.0% → 0.0% | n/a | 100% → 100% | 100% → 100% |

**The fix produced no measurable precision improvement.** Overall movement is −0.0pp.

### The deltas are sampling noise, not a treatment effect

Per-question movement is large in *both* directions and nets to zero:

| statistic | value |
|---|---|
| improved / regressed / unchanged | 26 / 30 / 30 |
| mean Δ | **−0.04 pp** |
| median Δ | **+0.00 pp** |
| mean **absolute** Δ | **12.62 pp** |
| stdev of Δ | 20.54 pp |

The decisive evidence is that churn scales inversely with sampling depth:

| | n | mean Δ | mean absolute Δ |
|---|---:|---:|---:|
| **1× sampled** (rich + mid) | 66 | +0.91 pp | **14.87 pp** |
| **3× sampled** (thin) | 20 | −3.16 pp | **5.21 pp** |

Averaging three runs cuts the churn by roughly 3×. That is the signature of **random
run-to-run variance at `temperature=0.3`**, not of a treatment effect — a real effect would
persist under averaging, not shrink toward it. The headline movers illustrate this: Mexico
*visa* gained **+66.7pp** (0.000 → 0.667) while Mexico *what-to-visit* lost **−73.2pp**
(0.857 → 0.125) in the same run, on the same country, from the same corpus.

**Methodological consequence for the report:** the Week 6 eval design (1× sampling for
rich/mid) has a per-question noise floor of roughly ±15pp. It is adequate for *aggregate*
claims over 91 questions but **cannot resolve a per-question intervention of this size**.
Any future retrieval change must be evaluated with repeated sampling across all tiers, not
just thin.

### Why the fix underdelivered — the diagnosis was right, the remedy was incomplete

The 6.2× figure came from querying with the raw question **alone**. The fix *appends* it to
the existing sub-queries, and `retrieve_node` still merges **by raw cosine score**. A
page-furniture chunk scoring 0.761 against `"Singapore travel advisories"` therefore still
outranks genuine tourism content at 0.576–0.681, even though the good candidates are now in
the pool. Adding a candidate set does not help when the *ranking* is what is broken.
This was predicted in the code comment before the run, and the smoke test showed it
directly: post-fix Singapore still retrieved 5 `state_dept` chunks.

**The binding constraint is the merge, not the query text.** The correct next step is rank
fusion — Reciprocal Rank Fusion over the per-sub-query result lists, so one lexically
inflated header cannot dominate a score-sorted pool. Not implemented (out of scope here,
and it would need another full re-eval to validate).

### 3d. Flips and the refusal check

| | before | after |
|---|---|---|
| gate flips | **1 / 25** (UAE what-to-visit, `[False, True, False]`) | **0 / 25** |

The UAE flip disappeared, but with n=25 and a single flip either way this is not
distinguishable from noise and should **not** be reported as a stability improvement.

**Unanswerable refusal check — ALL 5 STILL REFUSE, 3/3 runs each:**

| question | before | after |
|---|---|---|
| Japan 7-day rail pass price | `[F,F,F]` | `[F,F,F]` |
| Norway rainfall 2019 | `[F,F,F]` | `[F,F,F]` |
| Brazil visa cost USD | `[F,F,F]` | `[F,F,F]` |
| Louvre Tuesday hours | `[F,F,F]` | `[F,F,F]` |
| Chicago→Singapore airlines | `[F,F,F]` | `[F,F,F]` |

**The fix did not break refusal behaviour.** This was the stop condition; it did not trigger.

### 3e. Cost and runtime of the re-run

| | |
|---|---|
| wall clock | **~51 min** (16:03 → 16:54:46) |
| graph runs | 141 (91 questions) |
| logged graph calls | 1,264 |
| **logged graph cost** | **$1.0385** |
| per-run median / p90 / max | $0.0059 / $0.0133 / $0.0149 |
| throughput | ~20.3 s per run |

As in Week 6, the `claude-sonnet-4.5` judge calls bypass the cost logger, so $1.0385 is
logged graph spend only, not the all-in cost of the re-run.

---

## VERDICT

| phase | outcome |
|---|---|
| 1 — environment | **Fixed (diagnosis + command supplied).** 8 dangling symlinks, Docker itself healthy. Corpus verified intact at 2,319 on a persistent named volume. |
| 2a — live corpus count | **Shipped.** Header can no longer go stale. |
| 2b — scrape_date | **Shipped.** Proposal Risk 3 satisfied; proven metadata-only. |
| 3 — rewriter fix | **Shipped, but it did not work.** Precision 44.2% → 44.2%. Refusal behaviour preserved; no regression. The diagnosis (rewriter retrieves page furniture) still stands and is independently evidenced, but appending the raw question does not fix it because the score-sorted **merge** is the binding constraint. |

The honest headline for the report: **a well-evidenced diagnosis produced a fix that
measurably did not help, and the evaluation was sensitive enough to say so.** That is a
better outcome than shipping it on the strength of the 6.2× ablation and assuming it worked.
