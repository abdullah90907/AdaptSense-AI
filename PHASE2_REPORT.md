# AdaptSense AI — Phase 2 report

## Changes

Reviewed Phase 1's code, tests, report and demo before editing. Its early-versus-late errors belong to different forecast leads, so increased error alone cannot distinguish horizon effects from period deterioration. Existing endpoints and response fields remain working; the legacy reliability object now identifies that limitation.

Added `POST /replays` and `GET /replays/{id}`. Chronological rolling origins use fixed-length historical contexts, equal lead mixes, complete nonoverlapping target blocks, and frozen cached Chronos-Bolt Tiny. The recent period follows the reference period. Later actuals may enter later origins' contexts, as they would operationally; no origin sees its own future targets. Requests with incomplete targets are rejected before inference. Expanded uploaded snapshots can support new completed-period comparisons.

Saved evidence includes request parameters, checkpoint revision, origin/context timestamps, per-target predictions/actuals/errors, interval coverage, and seasonal-naive comparisons. No new dependencies, models, training or downloads were needed. No LifelineTwin changes, frontend, accounts, commits or pushes.

## Reliability method

Compare mean absolute errors at the same leads across periods, averaging within each origin before estimating uncertainty. A circular moving-block bootstrap resamples three adjacent origins within each period (2,000 draws, seed 20261026); its 95% interval describes the recent-minus-reference MAE difference. Blocking retains short-range dependence and avoids treating each lead as an independent replicate.

Practical change threshold: max(20% reference MAE, 10% initial-context seasonal-difference scale, 1e-9). `deterioration_supported` requires the lower interval bound above this threshold **and** both recent halves to exceed reference MAE by that threshold. A material mean increase without that support is `possible_deterioration`; otherwise `no_deterioration_detected`. These are transparent engineering criteria, not calibrated statistical drift alarms. Baseline MAE/skill and per-lead errors support interpretation; they do not establish causes.

## Actual verification

Six tests passed (0.91 seconds), including all three Phase 1 tests. New checks cover identical lead-dependent errors across periods (no false deterioration), constant context length and exact chronological predictor inputs, nonoverlapping targets, seasonal-naive arithmetic, saved replay retrieval, sustained controlled deterioration, a transient spike with uncertainty, zero errors, invalid/incomplete requests, and atomic rejection of invalid model output. Controlled cases are rule tests, not measured model performance.

Genuine cached CPU inference: 40 origins, 56-day contexts, seven-day forecasts; 20 origins/140 actual days in each period. Existing sourced `fpp2::elecdaily` Victoria 2014 demand; provenance and original source units in README. The two periods exhaust the final 280 observations; no search for an alarming split was performed.

| Measurement | Reference: Mar 27–Aug 13 | Recent: Aug 14–Dec 31 |
|---|---:|---:|
| Model MAE | 10.1047 | 10.2822 |
| Model RMSE | 12.9301 | 13.5898 |
| Seasonal-naive MAE | 9.8613 | 10.2519 |
| Skill vs seasonal naive | -2.47% | -0.30% |
| q10–q90 coverage | 82.14% | 83.57% |

MAE increased **0.1775**, below the **2.0209** practical threshold. Bootstrap interval: **[-2.2431, 2.8935]**. Recent half MAEs: **8.9517 / 11.6126**. Result: **no_deterioration_detected**, which is not proof of unchanged distributions. The model did not beat seasonal naive in either period. No real deterioration or causal explanation is claimed. Runtime: **12.59 seconds** with cached weights and network disabled. Full result: `data/phase2-replay-result.json`, also persisted in SQLite. Independently recomputed saved MAEs and verified 280 unique target timestamps and all cutoff/target ordering. The original Phase 1 genuine-inference demo also passed offline with unchanged MAE/RMSE/coverage.

## Limits and investigation readiness

Ready as an evidence backend for a read-only investigation prototype: stable API, persisted replay IDs, explicit rule/uncertainty metadata, chronological provenance and inspectable numerical evidence. An investigation agent is not implemented. It would need to preserve these caveats and obtain external evidence before suggesting causes.

The bootstrap assumes approximate within-period stability and sufficiently short dependence; 12–32 origins per period give limited power. Three-origin blocks and practical thresholds are defaults, not validated alarm-rate settings; dependence across the period boundary is not modeled. Equal leads remove the specific horizon-mix confound, but seasonal regimes, weather and changes in demand scale remain possible explanations. Interval coverage is descriptive, not calibrated assurance. Repeated comparisons require additional sequential/multiple-testing design before unattended alerting. Complete-period replay is retrospective and does not issue partial-period or live-stream alerts. No automatic recalibration occurs. Only one public dataset and checkpoint were demonstrated; pretraining overlap cannot be excluded. Existing local-service security and data-validation limits remain.

Research motivation remains Prof. Zimeng Lyu's nonstationary forecasting work (references in README). This implementation does not implement ONE-NAS, neuroevolution or online architecture evolution. Phase 2 stops here.

