# Groq (Llama 3.3 70B) vs. Gemini Flash — tier-tagging comparison

Full 60-question run, all `data/eval_set.json` questions, both models tagged
against the same retrieved chunks per question (retrieval held constant —
see `src/tier_comparison_runner.py`). Raw per-question data:
`data/tier_comparison_raw.json`. Machine-computed scores:
`data/tier_comparison_scores.json`, produced by `src/tier_comparison_scorer.py`.

## The confound, stated first because it explains most of what follows

**Gemini uses schema-enforced structured output** (`response_schema` —
`tier_tagger.py`'s `TIER_SCHEMA` is mechanically enforced by the API; the
model cannot return a tier string outside the four-value enum or omit a
required field). **Groq/Llama 3.3 70B only gets `json_object` mode** — valid
JSON is guaranteed, nothing about its *shape* is (confirmed in the pre-T12
feasibility check: this model isn't in Groq's supported-model list for
`json_schema` mode at all). `tier_tagger_groq.py` compensates with its own
post-hoc validation, but that catches malformed output — it can't make the
model choose the right enum value in the first place.

**Every gap below is a bundled measurement of model quality AND
structured-output reliability, not model quality alone.** This is not a fair
head-to-head between two language models; it's a comparison between "Gemini
Flash with mechanical schema enforcement" and "Llama 3.3 70B with a schema
description pasted into the prompt."

## Headline numbers

| | Gemini | Groq |
|---|---|---|
| Accuracy (collapsed 4-class, 60 questions) | **75.0%** (45/60) | **71.7%** (43/60) |
| Parse failures (final dataset) | 0 | 0 |
| Total claims produced | 183 (3.05/question) | 83 (1.38/question) |
| Hallucination-rate proxy (citing claims only) | **16.9%** (27/160) | **3.1%** (2/65) |

Accuracy is close — Gemini a few points ahead — but the two models get there
in very different ways, and the hallucination-rate gap looks far more
dramatic than it should be read as (see "Reading the hallucination numbers
honestly" below).

## Raw confusion matrices (expected → predicted, 5-class)

`Third-party-benchmark` never appears as an expected label because these 60
questions are RAG/eval-set questions — the trend-decay tool's own claims
(the only place `Third-party-benchmark` is ever assigned in production) are
built by `_trend_claims()` directly and never go through `tier_tagger.py`, so
this comparison's scope never exercises that tier. Not a gap in the run,
a scope boundary worth stating rather than leaving implicit.

**Gemini:**

| Expected \ Predicted | Verified-from-filing | Management-qualitative-statement | Model-inference |
|---|---|---|---|
| Verified-from-filing (37) | 29 | — | 8 |
| Management-qualitative-statement (9) | 1 | 6 | 2 |
| Model-inference (9) | 4 | — | 5 |
| Not-in-corpus (5) | — | — | 5 |

**Groq:**

| Expected \ Predicted | Verified-from-filing | Management-qualitative-statement | Model-inference |
|---|---|---|---|
| Verified-from-filing (37) | 34 | — | 3 |
| Management-qualitative-statement (9) | 6 | **0** | 3 |
| Model-inference (9) | 5 | — | 4 |
| Not-in-corpus (5) | — | — | 5 |

## Per-class precision / recall (collapsed 4-class — `Not-in-corpus` merged into `Model-inference`)

| Class | Gemini P / R | Groq P / R | Support |
|---|---|---|---|
| Verified-from-filing | 0.853 / 0.784 | 0.756 / 0.919 | 37 |
| Management-qualitative-statement | 1.000 / 0.667 | — / **0.000** | 9 |
| Model-inference | 0.500 / 0.714 | 0.600 / 0.643 | 14 |

## Key findings

### 1. Groq never once predicted `Management-qualitative-statement`, across all 60 questions — the clearest enforcement-gap signal in the whole run

Not a scoring artifact — checked directly against every claim in
`tier_comparison_raw.json`: Gemini assigns this tier 14 times across the run;
Groq assigns it **zero** times, ever. Every one of the 9 questions whose
ground truth is `Management-qualitative-statement` gets tagged by Groq as
either `Verified-from-filing` (6) or `Model-inference` (3) instead —
0.0 recall on this class, not a near-miss. This reads as a direct
consequence of the missing schema enforcement, not a language-quality gap:
nothing in Groq's response mechanically favors this specific enum value the
way it does for the other three, and the model appears to default to
whichever of "this is basically a filing fact" or "this is basically
unsupported" framing it defaults toward instead.

### 2. Groq over-uses `Verified-from-filing` — high recall, lower precision, the mirror image of finding 1

Groq: precision 0.756 / recall 0.919 on `Verified-from-filing`. Gemini:
precision 0.853 / recall 0.784. Groq catches more of the true
`Verified-from-filing` cases but also mislabels a chunk of the
`Management-qualitative-statement` cohort as `Verified-from-filing` (finding
1's 6-of-9 misroute lands here) — the same underlying gap read from a
different row of the same confusion matrix, not a second independent
finding.

### 3. Reading the hallucination-rate numbers honestly — the proxy is real, but the story is answer granularity, not fabrication

Gemini's proxy hallucination rate (16.9%, 27/160 citing claims) looks far
worse than Groq's (3.1%, 2/65) at a glance. Two things temper that read,
found by inspecting all 27 flagged Gemini claims directly rather than
trusting the headline number:

- **Gemini produces 2.2x as many claims per question** (3.05 vs. 1.38) and
  **2.5x as many chunk-citing claims** (160 vs. 65) — it habitually breaks
  an answer into granular sub-claims (e.g., one claim per geographic
  segment) where Groq gives one consolidated sentence. More citing claims is
  more surface area for the `numeric_grounding` check to flag, independent
  of whether anything is actually wrong.
- **Every one of the 27 flagged Gemini claims is `numeric_grounding`** (not
  `chunk_not_retrieved` or the weaker `keyword_overlap` heuristic) — and
  reading the actual claim text shows the flagged pattern is consistently
  *derived arithmetic presented as if verbatim*: per-segment dollar
  breakdowns computed from a chunk's aggregate figures (`eval_003`,
  `eval_004`, `eval_008`, `eval_009`), percentage-point deltas computed from
  two verbatim percentages (`eval_016`, `eval_035`), and one claim
  (`eval_032`) that explicitly says *"This figure is also mathematically
  implied by subtracting..."* — the model is telling you it's doing math,
  in a claim tagged `Verified-from-filing` rather than `Model-inference`.
  This is a **real, worth-fixing tier-boundary judgment call** (a computed
  number one arithmetic step away from the source arguably belongs under a
  different tier, or at minimum a `Model-inference` sibling claim), not
  evidence Gemini is inventing figures that don't exist anywhere in the
  filings. Groq's 2 flagged claims are the same pattern at much smaller
  scale, consistent with it simply generating far fewer citing claims
  overall, not being meaningfully more disciplined about grounding.

**This is an automated proxy, not human-judged fact-checking** — per
`tier_comparison_scorer.py`'s own documented method, a claim is flagged if
a number in it doesn't appear verbatim in the cited chunk. It cannot tell
the difference between "correct arithmetic explicitly derived from the
chunk's own numbers" and "a fabricated number" — both look identical to the
regex-based check. Reading the actual flagged claims (done above) is
necessary before drawing any conclusion from the raw rate; the raw
16.9%-vs-3.1% comparison on its own would overstate the real gap.

### 4. `Model-inference` — both models over-predict it by a similar margin

Gemini: precision 0.50 (10 of 20 `Model-inference` predictions were actually
something else — mostly true `Verified-from-filing` cases the model
declined more conservatively than the ground truth expected, per the raw
confusion matrix's 8 `Verified-from-filing → Model-inference` misses). Groq:
precision 0.60 (5 similarly-shaped misses). Recall is close (0.714 vs.
0.643). Neither model is meaningfully better here — both err toward
declining/hedging more often than the eval set's ground truth expects,
roughly equally.

### 5. Both models handle out-of-scope questions identically and correctly

All 5 `Not-in-corpus` questions get tagged `Model-inference` by both models,
every time (5/5 each) — the designed anti-hallucination decline behavior
(`_SYSTEM_INSTRUCTIONS`'s "if the retrieved context does not contain enough
information to answer, say so") transfers cleanly to Groq even without
schema enforcement. This is the one area with zero measurable gap between
the two.

## Operational notes

- **Zero parse failures in the final dataset** — every transient failure
  encountered during the run (Gemini `RESOURCE_EXHAUSTED` daily-quota hits,
  Groq TPD-cap 429s) was retried to a genuine result before this scoring
  pass, per the runner's resumability design (a question only counts "done"
  once both sides are genuine — see `src/tier_comparison_runner.py`).
- **The run itself took multiple sessions across roughly two months**,
  gated almost entirely by free-tier daily/TPD caps rather than by any
  code issue: Gemini's `GenerateRequestsPerDayPerProjectPerModel-FreeTier`
  (20/day, worked around via a permanent second-project key split, issue
  #31) and Groq's 100,000 TPD budget on `llama-3.3-70b-versatile` (no
  practical workaround found or attempted — paced across sessions instead).
  This says nothing about either model's answer quality; it's a free-tier
  capacity constraint specific to running a 60-question batch comparison,
  not something the live `/query` path (Gemini-only, one call at a time)
  ever encounters in production use.

## Conclusion

Gemini remains the right choice for production (`app/routers/query.py`
already only ever calls Gemini — nothing here changes that). The two
findings that matter most for anyone considering Groq as an alternative or
supplement:

1. **Schema enforcement is not a nice-to-have for this task.** The complete
   absence of `Management-qualitative-statement` predictions from Groq
   across all 60 questions is a direct, measurable consequence of the
   missing `response_schema` mechanism — not a Llama-3.3-70B language
   quality gap. Any future use of Groq for this kind of structured tagging
   should assume the model will systematically avoid or misuse enum values
   it isn't mechanically forced to consider, not just occasionally slip up.
2. **The overall accuracy gap (75.0% vs. 71.7%) is smaller than the
   hallucination-rate headline number suggests**, once the proxy's actual
   flagged claims are read rather than just its rate — the real, still-open
   finding from this run is a Gemini tier-boundary judgment call (derived
   arithmetic tagged `Verified-from-filing` instead of `Model-inference`
   or a distinguishing sub-tier), worth a future look at `tier_tagger.py`'s
   own prompt/schema, independent of anything about Groq.

If Groq or a similar unenforced-schema model were ever used for a
production-facing tagging path, this run is concrete evidence not to trust
it for full categorical coverage on the strength of a single call — a
per-request validator (`tier_tagger_groq.py`'s existing one included)
structurally cannot detect a systematically-avoided enum value, since that's
a pattern only visible in aggregate, across many calls, against ground
truth; no single JSON response reveals it. The practical mitigation would
be spot-checking against known-category examples or an ensemble/majority-
vote across repeated calls, not a stronger per-response schema check.
