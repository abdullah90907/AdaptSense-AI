import type { Provenance } from './workflow';
import { request } from './workflowApi';

export type Dataset = {
  id: string; name: string; unit: string; observations: number;
  first_timestamp: string; last_timestamp: string; provenance: Provenance | null;
};
export type CatalogPage<T> = { items: T[]; next_before: number | null };
export type ForecastEntry = { id: string; series_id: string; unit: string; cutoff: string; horizon: number; model: string };
export type ReplayEntry = { id: string; series_id: string; status: string; unit: string };
export type Model = 'chronos' | 'seasonal_naive' | 'evolved_rnn';
export type Policy = Model | 'adaptive';
type Metrics = { mae: number; rmse: number };
export type ExperimentSummary = {
  scored_origins: number; scored_targets: number; metrics: Partial<Record<Policy, Metrics>>;
  selected_origins: Partial<Record<Model, number>>;
  switch_outcomes: { count: number; improved: number; worsened: number; tied: number; mean_mae_gain_vs_retaining: number | null };
};
export type ExperimentStatus = {
  id: string; series_id: string; created_at: string; state: 'queued' | 'running' | 'completed' | 'failed' | 'interrupted';
  evolution_enabled: boolean; progress: { scored_origins: number; total_origins: number };
  error: string | null; summary: ExperimentSummary | null;
};
type Decision = {
  previous_model: Model; selected_model: Model; reason: 'warming_up' | 'retain' | 'switch';
  evidence_cutoffs: string[]; challenger_model?: Model; challenger_relative_gain?: number | null;
  challenger_block_wins?: number; recent_mae?: Partial<Record<Model, number>>;
};
export type ExperimentOrigin = {
  cutoff: string; decision: Decision;
  predictions: { timestamp: string; lead: number; chronos: number; seasonal_naive: number; evolved_rnn?: number; q10: number; q90: number }[];
  outcome?: { actuals: number[]; mae: Partial<Record<Model, number>>; gain_vs_retaining: number };
};
export type Experiment = {
  id: string; unit: string; origins: ExperimentOrigin[];
  models: { evolved_rnn?: { id: string; genome: { width: number; stride: number; topology: string }; seed: number; search_trace: unknown[] } };
};
export type Comparison = {
  id: string; unit: string; summary: ExperimentSummary;
  evaluation: { first_target: string; last_target: string };
  lowest_observed_fixed_mae_models: Model[];
  mae_above_best_fixed: Partial<Record<Policy, number>>;
  decision_settings: { lookback_origins: number; minimum_relative_gain: number };
  next_origin_recommendation: Decision;
  evolution_evidence?: { validation_mae: number; validation_seasonal_naive_mae: number; evaluation_mae: number; evaluation_seasonal_naive_mae: number };
  against?: { id: string; mae_delta_this_minus_other: Partial<Record<Policy, number>>; summary: ExperimentSummary };
};
export type LabSettings = { context: number; horizon: number; season: number; origins: number; lookback: number; evolution: boolean };
export const labels: Record<Policy, string> = {
  chronos: 'Chronos-Bolt Tiny', seasonal_naive: 'Seasonal naive', evolved_rnn: 'Evolved RNN', adaptive: 'Adaptive policy',
};
export const isActive = (status: ExperimentStatus) => status.state === 'queued' || status.state === 'running';
export const errorText = (error: unknown) => error instanceof Error ? error.message : 'The request could not be completed.';
export const experimentPath = (id: string) => `/adaptive-experiments/${encodeURIComponent(id)}`;
export const fetchStatus = (id: string) => request<ExperimentStatus>(`${experimentPath(id)}/status`);
export const fetchComparison = (id: string, against?: string) =>
  request<Comparison>(`${experimentPath(id)}/comparison${against ? `?against=${encodeURIComponent(against)}` : ''}`);
export const fetchHistory = (seriesId?: string, before?: number) => {
  const params = new URLSearchParams();
  if (seriesId) params.set('series_id', seriesId);
  if (before) params.set('before', String(before));
  return request<CatalogPage<ExperimentStatus>>(`/adaptive-experiments?${params}`);
};
export const fetchDatasets = (before?: number) =>
  request<CatalogPage<Dataset>>(`/series?limit=50${before ? `&before=${before}` : ''}`);

export function eligibleCutoffs(count: number, settings: LabSettings) {
  const { context, horizon, season, origins, lookback, evolution } = settings;
  const bounded = (n: number, low: number, high: number) => Number.isInteger(n) && n >= low && n <= high;
  if (!bounded(context, 32, 2048) || !bounded(horizon, 1, 64) || !bounded(season, 1, context - 1)
      || !bounded(origins, 5, 64) || !bounded(lookback, 3, Math.min(32, origins - 1))) return null;
  const first = context - 1 + (evolution ? 5 * horizon + 15 : 0);
  const last = count - 1 - origins * horizon;
  return { first, last, required: first + 1 + origins * horizon };
}
