# Engineering Machine — experiment queue
# Format per Cherny: goal + pre-registered verifier, agent builds the harness.
# Slope rule per Dean: run S/M/L corpus scales, judge the TREND, not one point.
# Statuses: [ ] queued  [~] running  [x] done  [-] rejected (write why)
# Results ledger: RESULTS.jsonl (one line per completed experiment)
# Corpus: experiments/corpus/{log,json,code}_{S,M,L}.txt (real data, gitignored)

## E1 [ ] zstd + trained dictionary vs lzma (CORE_ROADMAP T1)
Hypothesis: zstd with a dictionary trained on log/JSON-domain samples beats
  lzma preset 9 on ratio for S/M inputs (dictionary shines on small inputs)
  and is >=10x faster.
Method: pip zstandard; train dict on held-out log+json samples (NOT the
  corpus files); compress corpus at 3 scales; compare compressed bytes and
  wall time vs lzma preset 9 and preset 3.
Verify (pre-registered): adopt into backlog if ratio within 3% of lzma on L
  AND better on S AND >=10x faster. Else reject with numbers.

## E2 [ ] Number-preprocessor (Denum-style) before lzma (T1)
Hypothesis: rewriting timestamps/floats/ids into delta-encoded streams before
  lzma improves log ratio >=8%.
Method: write minimal preproc (regex classes: ISO timestamps, floats, hex ids)
  + exact inverse; property-test inverse on corpus (byte-exact) THEN measure.
Verify: byte-exact inverse on all 9 corpus files AND >=8% ratio gain on logs
  at all 3 scales (slope matters: gain should not shrink as size grows).

## E3 [ ] bzip3 backend evaluation (T1)
Hypothesis: bzip3 beats lzma on code by >=5% at acceptable speed.
Method: pip bz3 (or subprocess bzip3); measure ratio+time, 3 scales, code+log.
Verify: >=5% on code_L else reject.

## E4 [x] lzma preset sweep + FAST_PRESET_THRESHOLD tuning
Hypothesis: current threshold (2MB) and preset choice are not optimal;
  preset 6 may be within 1% of 9 at ~2x speed on our real corpus.
Method: sweep presets {1,3,6,9 | extreme} x 9 corpus files; table.
Verify: recommendation with numbers; adopt if a preset is within 1% of
  preset-9 ratio and >=1.7x faster.
RESULT 2026-08-12: REJECT switch. preset 6 == preset 9 ratio exactly (8.580)
  on real corpus but only 1.33x faster — below criterion; current defaults
  already near-optimal. New finding: 9|EXTREME gives +2.4% ratio for 2.4x
  time (0.39s/800KB total — negligible vs API latency). Follow-up E4b queued.

## E4b [ ] Make 9e (PRESET_EXTREME) the default below FAST threshold
Hypothesis: +2.4% ratio for free (0.4s per MB is noise vs agent round-trips).
Method: benchmark 9e vs current default on full bench.py suite + verify no
  test regressions; check memory usage stays sane on 10MB inputs.
Verify: no test failures, compress time <1.5s/MB on M-series, ratio gain >=2%.

## E5 [ ] Alphabet scan for open tokenizers (Llama-3, Qwen2.5, Gemma)
Hypothesis: each open vocab has >=8k single-token space-words => >=13 bits/token
  carrier alphabets, unlocking "densely for local models" positioning.
Method: HF tokenizers (local download, no API); adapt tools/build_alphabet.py
  scan to HF vocab files; count single-token space-words per vocab.
Verify: table of counts + bits/token per tokenizer; ship alphabets if >=8k words.

## E6 [ ] claude2: continuous-CJK statistical carrier (T2) — NIGHT-SAFE RATE
Hypothesis: CJK carrier gives ~15 bits/token AVERAGE on Claude tokenizer with
  <=2% worst-case variance across payloads (guarantee-vs-average tradeoff).
Method: count_tokens probes, <=2 req/sec, <=2000 requests/night; measure
  tok/char distribution on 50 random payloads x 3 sizes.
Verify: mean bits/token >=14 AND p99 within 15% of mean => promote to
  prototype; else document and close.

## E7 [ ] Columnar JSON pre-pass (LogFold-style, T2)
Hypothesis: transposing arrays-of-objects before lzma gives >=1.5x extra on json_L.
Method: minimal transpose + exact inverse; property-test THEN measure.
Verify: byte-exact inverse AND >=1.5x on json_L.
