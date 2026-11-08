# Phase 2 adaptive forecasting

`POST /adaptive-experiments` runs a sequential historical simulation from a saved series. `GET /adaptive-experiments/{id}` retrieves its SQLite record. Each origin commits Chronos-Bolt Tiny quantiles, seasonal-naive points, and the model choice before the simulator reveals the next block of actuals. Both forecasts use the same context cutoff, lead times, and targets. The existing forecast, evaluation, and reliability replay APIs still work.

The default policy starts with Chronos and waits for six scored blocks. It then switches only when the challenger lowers recent MAE by at least 5% and wins a strict majority of those blocks. A switch applies to the next unseen block. The experiment tracks the immediate MAE change versus retaining the incumbent and compares the adaptive policy with both fixed models over the same post-warm-up blocks.

## Victoria verification

Cached CPU inference ran 40 weekly origins with a 56-day context on the 2014 Victoria electricity-demand data. The first six origins supplied warm-up evidence. The comparison covers the remaining 34 origins and 238 targets. The experiment took about 10.5 seconds and was retrieved unchanged through the GET endpoint.

| Policy | MAE | RMSE |
| --- | ---: | ---: |
| Fixed Chronos | 9.876 | 12.804 |
| Fixed weekly seasonal naive | **9.740** | **12.702** |
| Adaptive | 9.859 | 12.791 |

Errors are in the dataset's source GW units. The policy selected seasonal naive on 24 evaluated blocks and Chronos on 10. At the June 25 cutoff it switched to seasonal naive and next-block MAE worsened by 0.214 versus retaining Chronos. At the December 10 cutoff it switched back and next-block MAE improved by 3.578 versus retaining seasonal naive. Overall, adaptive MAE was 0.017 lower than fixed Chronos and 0.119 higher than fixed seasonal naive. The small difference versus Chronos is descriptive.

**47 backend tests passed.** New tests verify prediction commits before scoring, chronological context, matched targets, policy reversal, outcome metrics, retrieval, and partial evidence on inference failure. The real run used a separate database at `.tmp/adaptive-victoria-verified.db`, experiment `92035b01-bb8e-410f-9392-51b533e0cf3c`. Reproduce from the project root with `python -m scripts.adaptive_demo` and `HF_HUB_OFFLINE=1`.

## Limits

This is retrospective, uses two point-forecast candidates, and evaluates a heuristic on one dataset. Both candidates are run on every origin so their forecasts can be compared, which means model switching does not reduce inference cost here. Execution is synchronous. An interrupted process can leave a partial record in the running state. Chronos intervals are stored as model quantiles, and the adaptive comparison scores point forecasts. Live ingest, probability calibration, and training are outside this phase. Before using the policy for real decisions, evaluate it on later periods and other series with the settings fixed in advance.
