# Phase 5 frontend

The React workspace now links saved datasets, imports, forecasts, and sequential experiments. Overview shows recent forecasts and experiment results alongside the saved Victoria reliability replay. Forecasting can use a saved series and historical cutoff, score later saved actuals on request, or accept separately supplied actuals. A validated import can be saved directly to Experiment Lab.

Experiment Lab configures the replay, optionally includes the evolved RNN, and follows scored blocks through the background status endpoint. History reopens saved runs and shows failures and interruptions. Comparison displays matched-target MAE and RMSE, evolutionary validation versus replay scores, and the measured effects of switches. The next-block recommendation is displayed separately. Users can inspect individual block predictions and actuals, or compare compatible experiments.

The production build and **23 frontend tests passed**. In the in-app browser, the production frontend used the local FastAPI server and cached Chronos weights. Verification covered a Victoria CSV import into the lab, a saved-dataset forecast with 32 evaluated actuals, real runs with and without the evolved RNN, background progress, reopening by URL, inspecting decisions, and comparing the two runs. At widths of 538 and 1280 pixels, the lab used one and two columns respectively, with no document-level horizontal overflow.

The historical forecast displayed MAE **11.83** and RMSE **14.13** in source units. The experiment comparison covered 210 matched targets. Seasonal naive had the lowest fixed MAE at **9.821**. Adaptive MAE was **10.135** with two candidates and **10.182** with three. The local records are `bfb46939-0e13-45fa-8f25-b4672b6333aa` and `921c2034-0619-43df-9aef-8d8f66b9b779`.

The dedicated reliability explorer uses the saved Victoria replay. Dataset-specific performance and switch outcomes are available in Experiment Lab. The backend admits one adaptive run at a time and provides no cancellation or resumption. Busy, failure, and interruption handling follows the existing API contract. The live browser runs followed the successful path.
