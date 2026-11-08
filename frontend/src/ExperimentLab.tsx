import { useEffect, useState } from 'react';
import { ArrowRight, FlaskConical, LoaderCircle, Play, RotateCcw } from 'lucide-react';
import { fullTimestamp, type InputSeries } from './workflow';
import { request } from './workflowApi';
import { date, fmt } from './data';
import { eligibleCutoffs, errorText, experimentPath, fetchComparison, fetchHistory, fetchStatus, isActive, labels,
  type Comparison, type Dataset, type Experiment, type ExperimentStatus, type LabSettings, type Policy } from './labApi';
import ExperimentResults from './ExperimentResults';

const defaults: LabSettings = { context: 56, horizon: 7, season: 7, origins: 36, lookback: 6, evolution: true };
const stateLabel = { queued: 'Queued', running: 'Running', completed: 'Completed', failed: 'Failed', interrupted: 'Interrupted' };

export default function ExperimentLab({ datasets, nextDataset, loadMoreDatasets, initialSeries, onImport, onRefresh }: {
  datasets: Dataset[]; nextDataset: number | null; loadMoreDatasets: () => void; initialSeries: string;
  onImport: () => void; onRefresh: () => void;
}) {
  const [seriesId, setSeriesId] = useState(initialSeries);
  const [series, setSeries] = useState<InputSeries | null>(null);
  const [settings, setSettings] = useState(defaults);
  const [cutoffOverride, setCutoffOverride] = useState<number | null>(null);
  const [id, setId] = useState(() => new URLSearchParams(location.search).get('experiment') ?? '');
  const [status, setStatus] = useState<ExperimentStatus | null>(null);
  const [run, setRun] = useState<Experiment | null>(null);
  const [comparison, setComparison] = useState<Comparison | null>(null);
  const [against, setAgainst] = useState(() => new URLSearchParams(location.search).get('against') ?? '');
  const [history, setHistory] = useState<ExperimentStatus[]>([]);
  const [peers, setPeers] = useState<ExperimentStatus[]>([]);
  const [before, setBefore] = useState<number | null>(null);
  const [seriesError, setSeriesError] = useState('');
  const [runError, setRunError] = useState('');
  const [historyError, setHistoryError] = useState('');
  const [historyLoaded, setHistoryLoaded] = useState(false);
  const [compareError, setCompareError] = useState('');
  const [posting, setPosting] = useState(false);
  const [comparing, setComparing] = useState(false);
  const [retry, setRetry] = useState(0);
  const bounds = series && eligibleCutoffs(series.readings.length, settings);
  const cutoff = cutoffOverride ?? bounds?.last ?? -1;
  const validCutoff = !!bounds && Number.isInteger(cutoff) && cutoff >= bounds.first && cutoff <= bounds.last;

  async function loadHistory(cursor?: number) {
    try {
      const page = await fetchHistory(undefined, cursor);
      setHistory(previous => cursor ? [...previous, ...page.items.filter(row => !previous.some(old => old.id === row.id))] : page.items);
      setBefore(page.next_before);
      setHistoryError('');
    } catch (error) { setHistoryError(errorText(error)); }
    finally { setHistoryLoaded(true); }
  }

  useEffect(() => { void loadHistory(); }, []);
  useEffect(() => { if (initialSeries) setSeriesId(initialSeries); }, [initialSeries]);
  useEffect(() => {
    if (!seriesId && datasets.length) {
      const victoria = datasets.find(row => row.name.includes('Victoria') && row.name.includes('fpp2') && row.observations === 365);
      setSeriesId(victoria?.id ?? datasets[0].id);
    }
  }, [datasets, seriesId]);
  useEffect(() => {
    let cancelled = false;
    setSeries(null);
    setSeriesError('');
    setCutoffOverride(null);
    if (seriesId) request<InputSeries>(`/series/${encodeURIComponent(seriesId)}`).then(value => {
      if (!cancelled) setSeries({ ...value, id: seriesId });
    }).catch(error => { if (!cancelled) setSeriesError(errorText(error)); });
    return () => { cancelled = true; };
  }, [seriesId]);
  useEffect(() => {
    if (!id) return;
    let cancelled = false;
    let timer: number | undefined;
    async function poll() {
      try {
        const next = await fetchStatus(id);
        if (cancelled) return;
        setStatus(next);
        if (isActive(next)) {
          timer = window.setTimeout(() => void poll(), 850);
          return;
        }
        void loadHistory();
        onRefresh();
        const [detail, result, candidates] = await Promise.all([
          request<Experiment>(experimentPath(id)),
          next.state === 'completed' ? fetchComparison(id) : null,
          next.state === 'completed' ? fetchHistory(next.series_id).catch(() => null) : null,
        ]);
        if (!cancelled) {
          setRun(detail);
          setComparison(result);
          setPeers(candidates?.items.filter(row => row.id !== id && row.state === 'completed') ?? []);
          const bookmarked = new URLSearchParams(location.search).get('against');
          if (result && bookmarked) {
            try {
              const paired = await fetchComparison(id, bookmarked);
              if (!cancelled) setComparison(paired);
            } catch (error) {
              if (!cancelled) setCompareError(errorText(error));
            }
          }
        }
      } catch (error) {
        if (!cancelled) setRunError(errorText(error));
      }
    }
    void poll();
    return () => { cancelled = true; window.clearTimeout(timer); };
  }, [id, retry, onRefresh]);

  function openRun(key: string) {
    if (key === id) return;
    setId(key);
    setStatus(null);
    setRun(null);
    setComparison(null);
    setPeers([]);
    setAgainst('');
    setRunError('');
    setCompareError('');
    const url = new URL(location.href);
    url.searchParams.set('experiment', key);
    url.searchParams.delete('against');
    historyState(url);
  }
  async function launch() {
    if (!series || !validCutoff || posting) return;
    setPosting(true);
    setRunError('');
    try {
      const accepted = await request<{ id: string }>('/adaptive-experiments?background=true', {
        series_id: series.id, first_cutoff: series.readings[cutoff].timestamp, context_length: settings.context,
        horizon: settings.horizon, seasonal_period: settings.season, origins: settings.origins,
        lookback_origins: settings.lookback, ...(settings.evolution ? { evolution: {} } : {}),
      });
      openRun(accepted.id);
      void loadHistory();
    } catch (error) {
      setRunError(errorText(error));
      void loadHistory();
    } finally { setPosting(false); }
  }

  async function compare() {
    setComparing(true);
    setCompareError('');
    setComparison(previous => previous ? { ...previous, against: undefined } : previous);
    try {
      const paired = await fetchComparison(id, against.trim() || undefined);
      setComparison(paired);
      const url = new URL(location.href);
      if (paired.against) url.searchParams.set('against', paired.against.id);
      historyState(url);
    }
    catch (error) { setCompareError(errorText(error)); }
    finally { setComparing(false); }
  }
  const busy = posting || !!(id && !runError && (!status || isActive(status)));
  const terminalError = status?.state === 'failed' || status?.state === 'interrupted';
  const fields = [
    { key: 'horizon', label: 'Forecast steps', min: 1, max: 64 },
    { key: 'season', label: 'Season length (steps)', min: 1, max: Math.max(1, settings.context - 1) },
    { key: 'origins', label: 'Forecast blocks', min: 5, max: 64 },
    { key: 'context', label: 'Context readings', min: 32, max: 2048 },
    { key: 'lookback', label: 'Decision window (blocks)', min: 3, max: Math.max(3, Math.min(32, settings.origins - 1)) },
  ] as const;

  return <main className="content page-enter">
    <section className="page-heading"><div><div className="eyebrow"><span/> SEQUENTIAL EVALUATION</div><h1>Experiment Lab</h1>
      <p>Replay observations in order, compare models on the same targets, and measure each switch.</p></div></section>
    <div className="lab-setup">
      <section className="panel lab-panel"><div className="panel-heading"><div><div className="small-kicker">01 / CONFIGURE</div><h2>New experiment</h2></div><FlaskConical size={20}/></div>
        <form className="lab-form" onSubmit={event => { event.preventDefault(); void launch(); }}>
          <label>Dataset<select value={seriesId} onChange={event => setSeriesId(event.target.value)} disabled={busy}>
            <option value="" disabled>Choose saved readings</option>
            {seriesId && !datasets.some(row => row.id === seriesId) && <option value={seriesId}>{series?.name ?? 'Selected dataset'}</option>}
            {datasets.map(row => <option value={row.id} key={row.id}>{row.name} · {row.observations} readings</option>)}
          </select></label>
          <div className="lab-actions"><button type="button" className="text-button" onClick={onImport}>Import a dataset <ArrowRight size={13}/></button>
            {nextDataset && <button type="button" className="text-button" onClick={loadMoreDatasets}>More datasets</button>}</div>
          {seriesError && <p className="workflow-error" role="alert">{seriesError}</p>}
          {seriesId && !series && !seriesError && <p className="lab-muted" role="status">Loading readings…</p>}
          {series && <p className="lab-muted">{series.readings.length.toLocaleString()} readings · {series.unit}</p>}
          <label className="lab-toggle"><input type="checkbox" checked={settings.evolution} disabled={busy} onChange={event => {
            setSettings({ ...settings, evolution: event.target.checked }); setCutoffOverride(null);
          }}/><span><strong>Include evolved RNN</strong><small>Search before replay, then keep the selected architecture fixed.</small></span></label>
          <div className="lab-fields">{fields.slice(0, 3).map(field => <label key={field.key}>{field.label}
            <input type="number" required min={field.min} max={field.max} value={settings[field.key]} disabled={busy}
              onChange={event => { setSettings({ ...settings, [field.key]: Number(event.target.value) }); setCutoffOverride(null); }}/>
          </label>)}</div>
          <details className="lab-details"><summary>Advanced settings</summary><div className="lab-fields">{fields.slice(3).map(field => <label key={field.key}>{field.label}
            <input type="number" required min={field.min} max={field.max} value={settings[field.key]} disabled={busy}
              onChange={event => { setSettings({ ...settings, [field.key]: Number(event.target.value) }); setCutoffOverride(null); }}/>
          </label>)}</div>
            {bounds && bounds.first <= bounds.last && <label>Cutoff reading (1-based)<input type="number" required min={bounds.first + 1}
              max={bounds.last + 1} value={cutoff + 1} disabled={busy} onChange={event => setCutoffOverride(Number(event.target.value) - 1)}/></label>}
          </details>
          {series && <p className="lab-muted">{validCutoff ? `First cutoff: ${fullTimestamp(series.readings[cutoff].timestamp)}. ${settings.lookback} blocks for warm-up.`
            : bounds && bounds.first > bounds.last ? `This setup needs at least ${bounds.required} readings. Reduce the horizon or blocks, or choose a longer series.`
              : 'Check the experiment settings and cutoff.'}</p>}
          <button className="primary-button" disabled={busy || !validCutoff} type="submit"><Play size={15}/>{posting ? 'Submitting…' : 'Run experiment'}</button>
        </form>
      </section>
      <section className="panel lab-panel"><div className="panel-heading"><div><div className="small-kicker">02 / REOPEN</div><h2>Experiment history</h2></div>
        <button className="icon-button" aria-label="Refresh experiment history" onClick={() => void loadHistory()}><RotateCcw size={17}/></button></div>
        {historyError && <p className="workflow-error" role="alert">{historyError}</p>}
        {history.length ? <ul className="workspace-list history-list">{history.map(row => <li key={row.id}>
          <div><strong>{datasets.find(item => item.id === row.series_id)?.name ?? 'Saved experiment'}</strong>
            <small>{date(row.created_at, true)} · {row.evolution_enabled ? '3 candidates' : '2 candidates'} · {row.id.slice(0, 8)}</small></div>
          <button className="text-button" disabled={posting || comparing || row.id === id} onClick={() => openRun(row.id)}>{stateLabel[row.state]} <ArrowRight size={13}/></button>
        </li>)}</ul> : <p className="lab-muted">{historyLoaded ? 'Runs appear here after submission.' : 'Loading experiment history…'}</p>}
        {before && <button className="text-button" onClick={() => void loadHistory(before)}>Load older runs <ArrowRight size={13}/></button>}
      </section>
    </div>
    {runError && <div className="workflow-error" role="alert">{runError}{id && <button className="text-button" onClick={() => { setRunError(''); setRetry(n => n + 1); }}>Refresh selected run</button>}
      {history.find(isActive) && <button className="text-button" onClick={() => openRun(history.find(isActive)!.id)}>Open active run</button>}</div>}
    {status && <section className="panel lab-panel run-status" aria-label="Selected experiment">
      <div className="panel-heading"><div><div className="small-kicker">SELECTED RUN · {status.id.slice(0, 8)}</div><h2>{stateLabel[status.state]}</h2></div>
        {isActive(status) && <LoaderCircle className="spin" size={20}/>}</div>
      <div role="status"><span>{status.progress.scored_origins} of {status.progress.total_origins} blocks scored</span>
        <progress aria-label="Blocks scored" value={status.progress.scored_origins} max={status.progress.total_origins}/></div>
      {isActive(status) && <p className="lab-muted">Progress updates as blocks are scored. You can reopen this run from history.</p>}
      {terminalError && <p className="lab-muted">{status.state === 'interrupted' ? 'The backend restarted before this run completed.' : 'The backend could not finish this run.'} Saved evidence is shown below when available.</p>}
    </section>}
    {run && (comparison || run.origins.length > 0) && <ExperimentResults key={run.id} run={run} comparison={comparison}/>}
    {comparison && <section className="panel lab-panel cross-run"><div className="panel-heading"><div><div className="small-kicker">MATCHED TARGETS</div><h2>Compare another run</h2></div></div>
      <p className="lab-muted">Runs must share the dataset, horizon, and evaluated timestamps. Choose from recent runs or paste an experiment ID.</p>
      <form className="lab-form" onSubmit={event => { event.preventDefault(); void compare(); }}>
        <label>Other experiment<input list="experiment-peers" value={against} onChange={event => setAgainst(event.target.value)} placeholder="Experiment ID" required/></label>
        <datalist id="experiment-peers">{peers.map(row => <option key={row.id} value={row.id}>{date(row.created_at, true)} · {row.evolution_enabled ? '3 candidates' : '2 candidates'}</option>)}</datalist>
        <button className="secondary-button" disabled={comparing || !against.trim()} type="submit">{comparing ? 'Comparing…' : 'Compare runs'}</button>
      </form>
      {compareError && <p className="workflow-error" role="alert">{compareError}</p>}
      {comparison.against && <div className="table-scroll"><table><caption>MAE difference, selected run minus {comparison.against.id.slice(0, 8)}. Positive means higher error.</caption>
        <thead><tr><th>Model or policy</th><th>Selected MAE</th><th>Other MAE</th><th>Difference</th></tr></thead>
        <tbody>{(Object.entries(comparison.against.mae_delta_this_minus_other) as [Policy, number][]).map(([model, delta]) => <tr key={model}>
          <th scope="row">{labels[model]}</th><td>{fmt(comparison.summary.metrics[model]!.mae, 3)}</td>
          <td>{fmt(comparison.against!.summary.metrics[model]!.mae, 3)}</td><td>{delta > 0 ? '+' : ''}{fmt(delta, 3)}</td>
        </tr>)}</tbody></table></div>}
    </section>}
  </main>;
}

function historyState(url: URL) {
  url.searchParams.delete('forecast');
  url.searchParams.delete('actuals');
  window.history.replaceState(null, '', url);
}
