# Phase 3 evolutionary forecasting

Adding `"evolution": {}` to `POST /adaptive-experiments` runs a bounded, seeded search over compact recurrent reservoirs. The search keeps high-performing parents and mutates hidden width, observation stride, or recurrent topology. Each reservoir uses fixed recurrent weights and a ridge-trained readout that predicts multi-step corrections to seasonal naive. Fitting and chronological validation both end before replay. The winner stays frozen while its input history advances. The existing policy can choose it based on previously scored blocks.

The same GET endpoint retrieves the experiment, including the fitted readout, normalization, search trace, model choices, predictions and actuals. Two-model requests retain their previous behavior. No new dependencies were needed.

## Research decision

I inspected the EXAMM-Extended multithreaded C++ entry point. It generates candidate genomes, trains them with stochastic backpropagation on training and validation inputs, and reinserts them into the search population. The README describes a coal example and recommends Linux or WSL for the CMake toolchain. The example file itself could not be fetched, and I found no verified license grant for the extension. I used an independent NumPy implementation without copying, building, or distributing upstream code. ONE-NAS informed the sequential evaluation context. This experiment evolves reservoir architectures offline and uses no online architecture or weight updates. [EXAMM-Extended runner](https://raw.githubusercontent.com/zimenglyu/EXAMM-Extended/main/multithreaded/examm_mt.cxx) · [EXAMM-Extended README](https://github.com/zimenglyu/EXAMM-Extended#readme) · [ONE-NAS paper](https://arxiv.org/abs/2302.10347)

## Victoria CPU verification

The run evaluated 16 architectures. The winner used 16 ring-connected recurrent units, stride 1 and 119 fitted coefficients. On the four pre-replay validation blocks, its MAE was 9.030 versus 9.199 for the best initial architecture and 9.869 for weekly seasonal naive. This validation was used for selection.

Cached Chronos-Bolt Tiny and both alternatives then forecast at 36 matching weekly origins. The comparison below covers 210 daily targets after six warm-up origins. Errors use the source GW units.

| Forecast or policy | MAE | RMSE |
| --- | ---: | ---: |
| Fixed Chronos | 10.154 | 13.143 |
| Fixed weekly seasonal naive | **9.821** | **12.933** |
| Fixed evolved RNN | 12.148 | 15.995 |
| Adaptive, three candidates | 10.182 | 13.247 |
| Adaptive, two candidates on the same targets | 10.135 | 13.128 |

The last row recomputes the existing two-candidate policy from the same stored forecasts. Adding the evolved candidate increased adaptive MAE by 0.047. The policy selected it on five evaluated blocks and switched to it twice, improving the following block once and worsening it once versus retaining the incumbent. The validation advantage did not carry over to replay.

The experiment took 10.7 seconds and was retrieved unchanged from SQLite. The verification database is `.tmp/evolution-victoria-verified.db`, experiment `37641f85-1700-4668-9f72-f1e1e39462f8`. Reproduce with `python -m scripts.adaptive_demo --evolution` and `HF_HUB_OFFLINE=1`.

**50 backend tests passed.** New tests check architecture mutation, deterministic selection, rejection of insufficient history, matched-target metrics, adaptive selection and invariance of the fitted model and first forecast to changes in unrevealed values.

One series, one seed and four validation blocks provide limited evidence. The models share test conditions but have different training regimes. The evolved model produces point forecasts. Before expanding the search, compare it with a fixed reservoir and a regularized lag regression across more predeclared splits and seeds to see whether evolution adds value.
