import { useState } from 'react';
import { ArrowRight, GitBranch, TrendingDown } from 'lucide-react';
import { DemandChart } from './Charts';
import { date, fmt } from './data';
import { labels, type Comparison, type Experiment, type Model, type Policy } from './labApi';
import { fullTimestamp } from './workflow';

const modelOrder: Model[] = ['chronos', 'seasonal_naive', 'evolved_rnn'];
const signed = (value: number) => `${value > 0 ? '+' : ''}${fmt(value, 3)}`;

export default function ExperimentResults({ run, comparison }: { run: Experiment; comparison: Comparison | null }) {
  const [index, setIndex] = useState(() => Math.max(0, run.origins.length - 1));
  const [model, setModel] = useState<Model | 'selected'>('selected');
  const [active, setActive] = useState(0);
  const origin = run.origins[index];
  const shownModel = model === 'selected' ? origin?.decision.selected_model ?? 'chronos' : model;
  const chart = origin?.predictions.map((p, i) => ({
    timestamp: p.timestamp, actual: origin.outcome?.actuals[i], point: p[shownModel],
    q10: shownModel === 'chronos' ? p.q10 : undefined, q90: shownModel === 'chronos' ? p.q90 : undefined,
    baseline: shownModel !== 'seasonal_naive' ? p.seasonal_naive : undefined,
  })) ?? [];
  const rows = Object.entries(comparison?.summary.metrics ?? {}) as [Policy, { mae: number; rmse: number }][];
  const maximum = Math.max(1e-9, ...rows.map(([, row]) => row.mae));
  const recommendation = comparison?.next_origin_recommendation;
  const outcomes = comparison?.summary.switch_outcomes;
  const evidence = comparison?.evolution_evidence;
  const genome = run.models.evolved_rnn;
  const switches = run.origins.map((block, i) => ({ block, i })).filter(({ block }) => block.decision.reason === 'switch' && block.outcome);
  return <>
    {comparison && <div className="lab-results">
      <section className="panel lab-panel"><div className="panel-heading"><div><div className="small-kicker">OBSERVED PERFORMANCE</div><h2>Model comparison</h2></div><TrendingDown size={20}/></div>
        <p className="lab-muted">{comparison.summary.scored_targets} matched targets · {date(comparison.evaluation.first_target, true)} – {date(comparison.evaluation.last_target, true)} · {comparison.unit}</p>
        <div className="table-scroll"><table className="lab-metrics"><caption>Lower MAE and RMSE are better.</caption><thead><tr><th>Model or policy</th><th>MAE</th><th>RMSE</th></tr></thead>
          <tbody>{rows.map(([key, row]) => <tr key={key}><th scope="row">{labels[key]}{comparison.lowest_observed_fixed_mae_models.includes(key as Model) && <small>Lowest fixed MAE</small>}
            <div className="lab-metric-track" aria-hidden="true"><span className={`model-${key}`} style={{ width: `${row.mae / maximum * 100}%` }}/></div></th>
            <td>{fmt(row.mae, 3)}</td><td>{fmt(row.rmse, 3)}</td></tr>)}</tbody></table></div>
        {evidence && genome && <div className="lab-evidence"><strong>Validation versus later replay</strong>
          <p>{genome.search_trace.length} architectures evaluated · {genome.genome.width} recurrent units · {genome.genome.topology} topology.</p>
          <div className="table-scroll"><table className="validation-table"><thead><tr><th>Window</th><th>Evolved MAE</th><th>Seasonal MAE</th></tr></thead>
            <tbody><tr><th scope="row">Validation</th><td>{fmt(evidence.validation_mae, 3)}</td><td>{fmt(evidence.validation_seasonal_naive_mae, 3)}</td></tr>
            <tr><th scope="row">Later replay</th><td>{fmt(evidence.evaluation_mae, 3)}</td><td>{fmt(evidence.evaluation_seasonal_naive_mae, 3)}</td></tr></tbody></table></div>
          <p>Validation selected the architecture. Later replay tests how it held up on subsequent targets.</p></div>}
      </section>
      <section className="panel lab-panel"><div className="panel-heading"><div><div className="small-kicker">UNSCORED NEXT ORIGIN</div><h2>Adaptation recommendation</h2></div><GitBranch size={20}/></div>
        {recommendation && <><div className="lab-recommendation"><small>{recommendation.reason === 'switch' ? 'Switch to' : 'Retain'}</small><strong>{labels[recommendation.selected_model]}</strong></div>
          <p className="lab-muted">Based on the last {recommendation.evidence_cutoffs.length} scored blocks. The rule requires at least {fmt(comparison.decision_settings.minimum_relative_gain * 100, 0)}% relative MAE improvement and a majority of block wins.</p>
          {recommendation.recent_mae && <dl className="lab-recent">{Object.entries(recommendation.recent_mae).map(([key, value]) =>
            <div key={key}><dt>{labels[key as Model]}</dt><dd>{fmt(value, 3)} MAE</dd></div>)}</dl>}
          <p className="lab-muted">This is a recommendation for a hypothetical next block. The model comparison uses the full evaluation window.</p></>}
        {outcomes && <div className="lab-evidence"><strong>Measured switch outcomes</strong><p>{outcomes.count} switches · {outcomes.improved} improved · {outcomes.worsened} worsened · {outcomes.tied} tied.</p>
          {outcomes.mean_mae_gain_vs_retaining !== null && <p>Mean next-block MAE gain versus retaining the incumbent: {signed(outcomes.mean_mae_gain_vs_retaining)} {comparison.unit}.</p>}</div>}
      </section>
    </div>}
    {switches.length > 0 && <section className="panel lab-panel lab-switches">
      <div className="panel-heading"><div><div className="small-kicker">OBSERVED NEXT-BLOCK OUTCOMES</div><h2>What happened after each switch?</h2></div></div>
      <p className="lab-muted">Each row compares the chosen model with retaining the previous model on that same block.</p>
      <div className="table-scroll"><table><thead><tr><th>Cutoff · UTC</th><th>From → to</th><th>Outcome · {run.unit}</th></tr></thead>
        <tbody>{switches.map(({ block, i }) => {
          const gain = block.outcome!.gain_vs_retaining;
          const effect = gain === 0 ? 'Tied' : `MAE ${gain > 0 ? 'fell' : 'rose'} by ${fmt(Math.abs(gain), 3)}`;
          return <tr key={block.cutoff}><th scope="row"><a href="#experiment-block" className="text-button" onClick={() => { setIndex(i); setActive(0); }}>{fullTimestamp(block.cutoff)} <ArrowRight size={13}/></a></th>
            <td>{labels[block.decision.previous_model]} → {labels[block.decision.selected_model]}</td><td>{effect}</td></tr>;
        })}</tbody></table></div>
    </section>}
    {origin && <section id="experiment-block" className="panel lab-panel lab-block"><div className="panel-heading"><div><div className="small-kicker">PERFORMANCE OVER TIME</div><h2>Inspect a forecast block</h2></div></div>
      <div className="lab-fields block-select"><label>Forecast origin<select value={index} onChange={event => { setIndex(Number(event.target.value)); setActive(0); }}>
        {run.origins.map((item, i) => <option key={item.cutoff} value={i}>{i + 1} · {fullTimestamp(item.cutoff)}</option>)}
      </select></label><label>Chart model<select value={model} onChange={event => setModel(event.target.value as Model | 'selected')}>
        <option value="selected">Policy choice</option>{modelOrder.filter(key => key !== 'evolved_rnn' || genome).map(key => <option key={key} value={key}>{labels[key]}</option>)}
      </select></label></div>
      <p className="lab-muted">{labels[shownModel]} forecast · {run.unit}. {origin.outcome ? 'Actuals are overlaid where recorded.' : 'This block was saved before scoring.'} {shownModel === 'chronos' ? 'Shading shows q10–q90 model estimates.' : ''}</p>
      <DemandChart points={chart} cutoff={origin.cutoff} active={active} onActive={setActive} layers={{ actual: true, point: true, interval: shownModel === 'chronos', baseline: shownModel !== 'seasonal_naive' }} intraday/>
      <div className="legend-static lab-legend"><span><i className="mint-line"/>{labels[shownModel]}</span>{shownModel !== 'seasonal_naive' && <span><i className="amber-line"/>Seasonal naive</span>}<span>Dark line: actuals</span></div>
      <details className="lab-details"><summary>Chronological decisions · {run.origins.length} blocks</summary>
        <div className="table-scroll"><table><caption>Positive gain means lower error than retaining the previous model on that block.</caption>
          <thead><tr><th>Cutoff · UTC</th><th>Policy decision</th><th>Selected MAE</th><th>Gain vs retaining</th></tr></thead>
          <tbody>{run.origins.map((item, i) => <tr key={item.cutoff}><th scope="row"><button className="text-button" onClick={() => { setIndex(i); setActive(0); }}>{fullTimestamp(item.cutoff)} <ArrowRight size={13}/></button></th>
            <td>{item.decision.reason === 'warming_up' ? 'Warm-up' : item.decision.reason === 'switch' ? 'Switch' : 'Retain'} · {labels[item.decision.selected_model]}</td>
            <td>{item.outcome ? fmt(item.outcome.mae[item.decision.selected_model]!, 3) : 'Pending'}</td>
            <td>{item.outcome && item.decision.reason === 'switch' ? signed(item.outcome.gain_vs_retaining) : '—'}</td></tr>)}</tbody></table></div>
      </details>
    </section>}
  </>;
}
