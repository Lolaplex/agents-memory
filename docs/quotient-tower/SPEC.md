# Quotient Tower — Design Spec (v0.1.3)

**Working name:** quotient-tower
**Home:** `Lolaplex/agents-memory` (new backend module) — fleet component of the agents-* org
**Status:** DRAFT — for deconstruction into lolaplex-board tasks
**Intent:** any local agent (or human) can pick a task and burn tokens toward convergence without needing this conversation's context.

**Changelog:** v0.1.3 — L3 grounded on `Lolaplex/agents-store` (minted ULID + `datom` log); tower as projection; typed decision records replace `DECISIONS.md`; Q1/Q6 resolved per agents-store and Koru lineage discipline.

---

## 0. Abstract

A fixed-budget, cross-session memory for a frozen LLM backbone. The raw interaction log lives
append-only on disk (ground truth, never destroyed). A sidecar module maintains a hierarchical,
fractal index over that log — a tower of learned quotients — inside a fixed token/entry budget.
The backbone reads through a sparse reader + gate; writes flow through verified merge kernels.
The compression policy is trained supervised: teacher = retrieval from the raw log, student =
retrieval from the tower. Distortion is therefore exactly measurable, never vibes.

The design refuses one decision that all existing in-model memories make: it never throws away
ground truth. Everything downstream — safe eviction, verified merges, confluence of
re-specialization — depends on that axiom.

## 0.5 Repository map & cross-org dependencies

| Concern | Repository | Org | Notes |
|---|---|---|---|
| Ground-truth substrate | `agents-store` | Lolaplex | Minted ULID identity (`ids.mint()`); append-only `datom` log enforced by triggers; as-of-transaction reads (`Store.view(..., tx=)` / `v_current`); single deny-by-default write path via `Store.transact()` with every refusal logged in `refusal`; PROV `lineage` edges; adapters register through `Registry` / entry-point groups with `mediator` rows stamped `exact` or `contained`. |
| Tower home | `agents-memory` | Lolaplex | Exists: local markdown memory & cross-agent context engine (MCP, Python). Tower = new backend module, not a new repo. |
| Task board | `lolaplex-board` | Lolaplex | Private. Agent-centric project board (PHP, htmx, SQLite, DID). Spec deconstructs into tasks here. |
| Trace query source | `agents-traces` | Lolaplex | JSONL observability/tracing (MCP + CLI). E0 query set is extracted from this. |
| Docs-RAG reference | `agents-docs` | Lolaplex | Local markdown RAG (MCP + BM25). Sibling retrieval component; compare readers. |
| Harness integration | `agents-harness` | Lolaplex | Declarative flow runner + job kernel. T3.3 adapter target. |
| Execution boundary | `agents-terminal` / `kopium` | Lolaplex / korulang | Policy-bound terminal vs. safety-via-type-system interpreter. Agent execution reference. |
| Merge-kernel expression (cipher / cypher-lang) | TBD — confirm repo location | — | Compression-as-normalization rewrite rules. Location not asserted in this spec revision. |
| Merge-kernel proofs | `isar-proofs` | Cypoe (personal) | Lean 4. Invariant Layer = operational quotient, terminal object in the category of closed computational dialects. Confluence + unique normal forms live here. |
| Merge-kernel evidence | `koru` | korulang (CROSS-ORG) | "The event continuation language" (Zig). Proof-carrying obligations/receipts are a korulang deliverable consumed here as an external dependency — NOT a Lolaplex fleet component. |
| Lineage-discipline precedent | `koru-membrane` | korulang (CROSS-ORG) | Shared memory corpus — OKF concept store. Coordination point for shared corpus, not the lineage-discipline reference (see Q6: Koru commit gates + typed verbs). |

**Cross-org rule:** Lolaplex fleet tasks may *consume* korulang/Cypoe artifacts but must not
*modify* them in fleet tasks; upstream changes are separate tasks in their home repos.

## 1. Axioms

- **A1 — Ground truth is external and append-only.** The disk log is the only source of truth.
  The tower is a derived index, always fully rebuildable from the log.
- **A2 — Fixed budget.** The tower's resident budget (tokens or entries) is an architectural
  constant, chosen at deploy time. Compression is forced, not optional.
- **A3 — Frozen backbone as ABI.** The LLM host (e.g. pinned Qwen3-1.7B) is frozen; its
  tokenizer + embedding space are the versioned ABI. Sidecar is swappable; ABI bump = recompile.
  Long-term softening: the isar-proofs host-invariant realization pipeline, if it extends to
  embedding-level realizations, could weaken the backbone-binding — treat as research upside,
  not a dependency.
- **A4 — Supervised compression.** Merge/evict policies are trained against the raw-log teacher.
  No compression decision is trusted without measurable distortion evidence.
- **A5 — Mechanical and semantic parts are separated.** Merge kernels (mechanical, verified,
  declare preserved invariants) vs. equivalence criteria in latent geometry (semantic, learned).
  Writes pass through the mechanical part; reads traverse the semantic part.
- **A6 — Confluence.** The tower's maintenance operations (merge, promote, demote, rebuild)
  must be confluent: incremental maintenance and full rebuild from the log agree up to
  declared equivalence. Path-dependent drift is a defect.

## 2. Glossary (pin these; agents must not rename)

- **Log (L3):** `agents-store` append-only `datom` fact log (ground truth). Unbounded. Never edited in place; tower and markdown are projections.
- **Tower (L2):** fixed-budget hierarchical index over the log. Levels are quotient maps
  π_n : L_{n-1} -> L_n. Coarse at the root, raw-pointing at the leaves.
- **Context window (L1):** backbone working set. What the model "sees" this step.
- **Reader:** sparse lookup over the tower (ANN / product-key), one or more heads.
- **Gate:** learned decision of what enters L1 this step (and traversal-vs-pool, see E2).
- **Merge kernel (mechanical part):** verified rewrite operator with a declared invariant set
  I(π). Guarantees: lossless w.r.t. I(π), bounded loss elsewhere (quantified).
- **Nap:** re-quotient pass over the tower (rebuild levels, re-cluster, re-summarize).
  Scheduled or drift-triggered. Confluence-checked (E4).
- **Wake digest:** bounded constant-size view assembled from the tower at session start
  (OptMem's `wake`, mechanized).
- **Teacher:** retrieval answers computed with full-log access through the same backbone.
- **Distortion:** gap between student (tower) and teacher (log) answers, on trace queries.
- **Trace query set:** agents-traces replayed as retrieval queries. Defines what is
  load-bearing. Filter out non-declarative content (e.g. `<think />` blocks) before use.

## 3. Architecture

```
 ┌──────────────────────────── session ────────────────────────────┐
 │  L1 context  ←─ Gate ←─ Reader ──┐                               │
 │      ▲ backbone (frozen, ABI)     │ tower queries                 │
 └──────┼────────────────────────────┼───────────────────────────────┘
        │ activations / logits        ▼
        │                  ┌───────────────────────┐
   write path ────────────▶  L2 TOWER (fixed budget)│
   (merge kernels,         │  level n   (quotient)  │
    verified)              │  level n-1 (quotient)  │
        │                  │  ...                  │
        ▼                  │  leaves → ptrs into L3 │
 ┌──────────────┐          └──────────┬────────────┘
 │ L3 LOG (disk)│◀────── append-only ──┘  (rebuild: nap)
 │ append-only  │
 └──────────────┘
```

Components to build:

- **C1 log-store (not built anew):** L3 is `agents-store`'s `datom` log, consumed through its
  registration contract (`Registry.register_wrapper` / `register_capability`, entry-point groups
  `agents_store.wrappers` and `agents_store.capabilities`). The tower lives in `agents-memory` as
  a **projection** over that substrate — not a second log. Rationale: a second log would duplicate
  the artifact; MORe forbids duplication. **T0.1 prerequisites** (gaps to close in `agents-store`
  before the tower can bind L3): (1) every table append-only, not only `datom`; (2) `certificate`
  and `provenance` rows pinned to the repro-script commit hash and the enclosing `tx`; (3) typed
  move/retire events (not ad-hoc attrs); (4) a separate `severs` lineage kind distinct from
  `evolve` / `wasRevisionOf`.
- **C2 tower-store:** persistent hierarchical index; each node = summary payload (text or
  latent) + child pointers. Fixed budget enforced at insertion.
- **C3 reader:** ANN (FAISS/HNSW) or product-key lookup over multiscale node embeddings.
- **C4 gate:** small learned module over reader scores; decides L1 admission.
- **C5 merge kernels:** operators `merge`, `promote`, `evict`, `demote`, `rebuild`, each
  declaring I(π). Layer mapping (see Q4): expression in cypher-lang (cipher rewrite rules),
  confluence and invariant-preservation proofs in Cypoe/isar-proofs, runtime commits as koru
  (korulang) proof-carrying obligations. Propose-verify: kernels propose, verification against
  L3 commits.
- **C6 policy:** learned merge-worthiness criterion in latent space (semantic part).
- **C7 trainer:** teacher-student loop; queries from trace set; distortion from teacher diff.
- **C8 nap daemon:** drift monitor + scheduled re-quotient + confluence audit.

## 4. Interfaces & ABI

- **ABI-v1 = pinned backbone checkpoint hash.** Any pinned Qwen3 dense model (0.6B/1.7B/4B/8B
  have uniform GQA anatomy; 16Q/8KV small, 32Q/8KV at 4B/8B). Pin explicitly — the 2507 refresh
  moved the family; an unpinned ABI is an unpinned experiment.
- **Reader ABI:** (query embedding, budget) -> ranked node list with level metadata.
- **Write ABI:** (record id, payload) -> ack; tower maintenance is internal to C5/C6.
- **Distortion ABI:** (query, student_answer, teacher_answer) -> score. Swappable metric;
  start with exact-match + embedding-distance hybrid.

## 5. Design experiments

Each experiment: hypothesis, method, decision rule, branches with the tasks they unlock.
Run order E0 → E1/E2 parallel → E3/E4 → E5 → E6 → E7. Budget: each E ≤ 3 days agent-time.

### E0 — Oracle calibration (do this first, everything depends on it)
- **Hypothesis:** flat ANN retrieval at budget B underperforms full-log teacher on trace queries
  by a wide, measurable margin. (If not, the whole thesis is weak.)
- **Method:** replay N=1k trace queries from agents-traces through (a) full-log teacher,
  (b) flat top-k ANN. Record distortion. Establish the baseline gap G0.
- **Metrics:** answer agreement, recall@budget, token spend per query.
- **Decision rule:** G0 < 10% → STOP, thesis weak, memory not needed at this scale; G0 >= 10% → proceed.
- **Unlocks:** all later experiments inherit the oracle + query set as shared infra.

### E1 — Schedule vs. learned policy
- **Hypothesis:** a learned merge policy beats a fixed geometric schedule (merge every k blocks)
  at constant budget.
- **Method:** implement both; identical budget B; identical reader; compare distortion on held-out trace queries.
- **Decision rule:** learned wins by >= 5% relative → branch A; within noise → branch B.
- **Branch A (learned):** invest in C6/C7 training infra; tasks: Gumbel/straight-through merge
  training, curriculum over trace replay.
- **Branch B (schedule):** mechanize the schedule in C5 kernels only; drop C6 to a priority
  heuristic; spec shrinks; focus shifts to verification and drift (E7).

### E2 — Traversal vs. collapsed pool
- **Hypothesis (contrarian):** one-shot multiscale pool beats coarse-to-fine drill-down
  (RAPTOR's own finding), unless relevance is concentrated.
- **Method:** same tower, two readers: (a) lazy drill-down (zoom on high gate score),
  (b) flattened multiscale pool + ANN, single shot.
- **Branch A (pool):** reader stays simple; no traversal state; gate is a scorer only.
- **Branch B (drill-down):** implement zoom protocol with bounded expansion factor; gate gains
  a traversal mode; add latency budget task.

### E3 — Merge supervision granularity
- **Hypothesis:** propose-verify (kernels propose, raw-log verification commits) is feasible at
  interactive rates; otherwise fall back to straight-through gradients.
- **Method:** measure verification latency per merge against L3; measure policy quality under
  both regimes.
- **Branch A (propose-verify, fast enough):** eviction/merge commits become koru proof-carrying
  obligations (korulang/koru, cross-org); receipts (hash-check now, zkVM later) per merge decision.
- **Branch B (too slow):** approximate commit + periodic audit daemon (sample merges, verify
  post-hoc, roll back violating ones via rebuild from L3).

### E4 — Nap confluence
- **Hypothesis:** incremental tower maintenance and full rebuild agree (up to declared
  equivalence) — i.e. the maintenance rewrite system is confluent.
- **Method:** maintain tower incrementally over a synthetic + real trace stream; at checkpoints,
  rebuild from L3; diff towers at each level under the declared equivalence.
- **Proof target:** discharge confluence/invariant preservation in Cypoe/isar-proofs
  (Lean 4; ISAR.lean carries rewrite-rule syntax, confluence proofs for ITerm, unique normal
  forms for the ISKTerm fragment); E4's runtime diff is the executable shadow of that proof.
- **Branch A (confluent):** incremental maintenance ships; nap scheduled sparsely.
- **Branch B (divergent):** maintenance is approximated; nap becomes mandatory periodic rebuild;
  spec the rebuild cost budget and the staleness window.

### E5 — Payload representation: text vs. latent
- **Hypothesis:** latent payloads (KV vectors / embeddings) achieve better rate-distortion than
  text summaries, but text is verifiable.
- **Method:** run tower twice, text payloads vs. latent payloads, same budget, same reader
  class; measure distortion AND verifiability (can a kernel prove what a node preserved?).
  Third arm if Q4-open resolves toward ISAR chunks: phi-lang chunk payloads, merges as
  cipher-native rewrite rules, at the cost of an encoding bridge at the ABI boundary.
- **Branch A (text):** summaries are inspectable, quotable, kernel-verifiable; rate is worse;
  accept token overhead.
- **Branch B (latent):** better rate; loses mechanical verification of the semantic part
  (A5 weakened) → hybrid: latent payloads + text digests for verification only.
- **Default prior:** text first (verifiability is the differentiator of this design).

### E6 — Competitor: serialized recurrent state (single-user local case)
- **Hypothesis:** for a single local agent, LMCache-style cross-session delta-state carryover on
  a hybrid backbone (Qwen3-Next family / Qwen3-Coder-Next) is a cheaper baseline that may
  suffice, making the tower's value multi-session/collaborative only.
- **Method:** serialize GDN state at session end, rehydrate next session; compare against
  tower + teacher on the same sessions. Metric: cross-session recall + entanglement cost
  (can it say WHERE it knows something from? can it evict one thing?).
- **Branch A (state suffices):** re-scope tower to distributed/multi-agent memory where
  provenance and selective eviction are non-negotiable; single-user mode ships state carryover.
- **Branch B (tower wins):** single-user case also justifies the tower; state carryover becomes
  an optional L1.5 cache layer, never source of truth (A1).

### E7 — Drift and nap timing
- **Hypothesis:** latent geometry drift on a rolling trace stream is detectable early enough to
  trigger nap before distortion crosses threshold.
- **Method:** rolling 2-sample tests on node embedding distributions; correlate with measured
  distortion; find the trigger point.
- **Branch A (detectable):** nap daemon = monitor + trigger; drift alarms are part of C8.
- **Branch B (not detectable in time):** fixed-interval mandatory nap; accept staleness window
  as a spec'd constant.

## 6. Branch map (decision tree)

```
E0: gap?          no ──▶ STOP / re-scope
    │ yes
E1: policy?       learned ──▶ C6/C7 heavy path ──┐
    │ schedule ──▶ C5-only path (spec shrinks) ──┤
E2: reader?       pool ──▶ simple reader ─────────┤
    │ drilldown ──▶ zoom protocol ────────────────┤
E3: verify rate?  fast ──▶ koru proof-carrying merges ┤
    │ slow ──▶ audit daemon ──────────────────────┤
E4: confluent?    yes ──▶ incremental maintenance ┤
    │ no ──▶ periodic rebuild budget ─────────────┤
E5: payload?      text ──▶ verifiable tower ───────┤
    │ latent ──▶ hybrid digests ──────────────────┤
E6: local case?   state suffices ──▶ multi-session scope
    │ tower wins ──▶ + L1.5 state cache (optional) ┤
E7: drift seen?   yes ──▶ trigger-based nap ────────┤
    │ no ──▶ fixed-interval nap ──────────────▶ INTEGRATION (P3)
```

## 7. Task decomposition (board-ready — Lolaplex/lolaplex-board)

**P0 — Infrastructure (blocking, ~1 week)**
- T0.1 L3 bind (C1): wire tower ingest to `agents-store` `datom` via the registration contract;
  do **not** implement a parallel log. DoD: 10k `transact` appends through a registered wrapper,
  as-of reads match `v_current`, tower rebuild from log is deterministic. Blocked until agents-store
  T0.1 prerequisites (C1 list) land.
- T0.2 trace query set: extract declarative queries from agents-traces; `<think />` filtered;
  train/holdout split frozen with a hash. DoD: 1k queries, schema validated.
- T0.3 teacher runner: full-log retrieval through pinned backbone. DoD: batch, reproducible, cached.
- T0.4 ABI pin: checkpoint hash, tokenizer, embedding extraction scripts. DoD: regenerates identical embeddings.

**P1 — Oracles (E0, ~3 days)**
- T1.1 flat ANN baseline at budget B. DoD: distortion numbers + repro script.
- T1.2 G0 report: go/no-go with numbers. DoD: `decision` record in `agents-store` (see §8).

**P2 — Experiments (E1–E7, each board-tracked)**
- One task per experiment: implementation, run, report. DoD: numbers + repro script + typed
  `decision` record (and `verification` when applicable) in `agents-store`. No experiment ships
  conclusions without its repro script committed. Legacy ADR/fragment markdown decision files are
  flimsy — migrate into store records; any surviving markdown is a generated view only.

**P3 — Integration (after branch map resolves, ~2 weeks)**
- T3.1 nap daemon per E4/E7 branch.
- T3.2 wake digest: bounded session-start view. DoD: constant size, deterministic given tower.
- T3.3 agents-memory adapter: expose reader/gate as a tool in agents-harness.
- T3.4 receipts (stretch, cross-org): merge decisions as koru proof-carrying obligations
  (korulang/koru); confluence certificate for the maintenance rewrite system discharged in
  Cypoe/isar-proofs.

## 8. Agent execution protocol (how to burn tokens toward convergence)

- **Definition of done for every task:** code + repro script + numbers + typed decision record in
  `agents-store`. Evidence, not narrative.
- **Decision records (replace `DECISIONS.md`):** store kinds `decision`, `verification`,
  `inclusion`, `supersession`, `overrule`, `move` — each minted entity with its own ID, author,
  timestamp, version pin to the repro-script commit hash, and supersession link when revised. Any
  markdown summary is a generated projection, never authoritative. A single unnumbered markdown
  document rots as it grows; that rot is exactly the problem the tower addresses.
- **Convergence criterion (global, board gate):** at fixed budget B, tower retrieval matches teacher
  answers on >= 90% of hold-out trace queries using <= 25% of the teacher's token spend (re-calibrated
  after E0). Shipping requires a passing `verification` record on the board — not a line in
  `DECISIONS.md`.
- **Anti-drift:** no agent renames glossary terms; no task touches L3 semantics (append-only);
  ABI bumps are a single designated task type; cross-org repos are read-only from fleet tasks.
- **Isolation:** every experiment runs against the same frozen query set and teacher cache;
  results are comparable across agents and runs.
- **Small model first:** all policy training fits on 0.6B/1.7B hosts; scale validation at 4B/8B
  is its own task after E1.

## 9. Risks & non-goals

- **Non-goal:** in-weights memory, fine-tuning the backbone, multi-tenant serving concerns (until E6 says otherwise).
- **Risk: query-set overfitting.** Trace replay is the training signal AND the eval — holdout
  split must be temporal (train on older traces, eval on newer), or results are circular.
- **Risk: budget too tight early.** If B forces catastrophic loss, the policy learns to ignore
  the tower (classic learned-memory collapse). Start generous, shrink on a schedule.
- **Risk: ABI churn** (Qwen family iterates fast). Mitigated by T0.4 pinning; treat 2507-style
  refreshes as ABI bumps, not silent upgrades.
- **Risk: cross-org drift.** korulang/koru and Cypoe/isar-proofs evolve on their own roadmaps;
  fleet tasks consume tagged releases, never trunk.

## 10. Open questions register

- Q1: **Closed (v0.1.3).** `agents-store` minted ULIDs (`ids.mint()`) are the record identity;
  position-as-identity (OptMem-style) is not needed for L3.
- Q2: Should the tower span multiple agents (shared) before single-agent convergence is proven? (Default: no.)
- Q3: Does the gate need a "don't retrieve" mode (skip tower entirely) to avoid reader dilution in L1?
- Q4 (merge-kernel layer mapping — three distinct roles, do not conflate):
  - Q4a Expression: merge kernels written as cypher-lang rewrite rules over phi-lang/ISAR-chunk
    payloads. In cipher, compression IS confluent normalization — a merge is the native
    operation of the chunk algebra. Repo location TBD — confirm before tasks reference it.
  - Q4b Proofs: confluence of maintenance rewrites (E4) and invariant preservation per kernel
    are discharged in Cypoe/isar-proofs (Lean 4: rewrite-rule syntax, confluence proofs for
    ITerm, unique normal forms for the ISKTerm fragment). Koru is NOT the proof tooling
    here; it is the evidence layer.
  - Q4c Evidence: propose-verify commits (E3 branch A) are koru proof-carrying obligations
    (korulang/koru — cross-org), with receipts (hash-check now, zkVM later) per merge
    decision (T3.4).
- Q4-open: payload encoding as ISAR chunks (phi-lang terms) vs. plain text summaries — interacts
  with E5: chunk payloads make merges cipher-native but cost an encoding bridge at the ABI
  boundary; plain text keeps the bridge trivial but merges lose the chunk algebra.
- Q5: Minimum viable nap: what fraction of levels need re-quotient on drift, empirically?
- Q6: **Closed (v0.1.3).** Adopt **Koru** lineage discipline (commit gates, typed lineage verbs) for
  tower maintenance and board workflow — not `koru-membrane` as the reference: membrane hook copies
  have drifted from canonical `koru/hooks`, and only `koru-libs` is drift-checked. L3 lineage
  remains `agents-store` PROV edges + future `severs` kind; Koru governs how fleet tasks commit.

## 11. References

- OptMem (Taelin): append-only log, on-the-spot compression, wake digest, forget-rebuild.
- RAPTOR (Sarthy et al., ICLR 2024): recursive tree retrieval; collapsed-pool vs traversal finding.
- Memorizing Transformers (Wu et al., ICLR 2022): kNN memory, learned gate, non-differentiable store.
- Rate-Distortion Optimization for Transformer Inference (arXiv 2601.22002): R-D framing for transformer compression.
- Qwen3 Technical Report / Qwen3-Next blog: dense ladder, GQA anatomy, GDN+attention 3:1 hybrid.
- LMCache hybrid-model docs: recurrent-state serialization as opaque pages.
- How Linear Attention Remembers (arXiv 2609.33093): delta-state entanglement, lossy non-inspectable writes.
- Internal: Lolaplex/agents-memory (MCP markdown memory), agents-store (minted ID + datom log),
  agents-traces (JSONL), agents-docs (BM25 RAG), agents-harness, lolaplex-board;
  Cypoe/isar-proofs (Lean 4, Invariant Layer);
  korulang/koru (event continuation language), koru-membrane (OKF concept store, git-log
  lineage), kopium (type-system safety boundary); cipher (cypher-lang, compression-as-normalization).
