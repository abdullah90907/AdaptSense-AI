import { ArrowRight, AudioLines, Database, FlaskConical, ScanLine } from 'lucide-react';
import { date, fmt, statusLabel } from './data';
import { labels, type Dataset, type ExperimentStatus, type ForecastEntry } from './labApi';
import type { Workspace } from './types';

export default function Dashboard({ datasets, forecasts, experiments, data, error, refresh, openForecast, openLab, openReplay }: {
  datasets: Dataset[]; forecasts: ForecastEntry[]; experiments: ExperimentStatus[]; data: Workspace | null;
  error: string; refresh: () => void; openForecast: (seriesId?: string) => void;
  openLab: (seriesId?: string) => void; openReplay: () => void;
}) {
  const assessment = data?.replay.assessment;
  const latest = experiments.find(run => run.summary)?.summary;
  const best = latest && Object.entries(latest.metrics).filter(([key]) => key !== 'adaptive').sort(([, a], [, b]) => a.mae - b.mae)[0];
  const demo = data?.catalog;
  const demoUrl = demo?.experiment_id && demo.comparison_id
    ? `?experiment=${encodeURIComponent(demo.experiment_id)}&against=${encodeURIComponent(demo.comparison_id)}` : null;
  return <main className="content page-enter">
    <section className="page-heading"><div><div className="eyebrow"><span/> RESEARCH WORKSPACE</div>
      <h1>Forecasting workspace</h1><p>Go from observed readings to forecasts and measured model decisions.</p></div>
      <button className="primary-button" onClick={() => openForecast()}><AudioLines size={16}/> New forecast <ArrowRight size={15}/></button>
    </section>
    {error && <div className="workflow-error" role="alert">{error}<button className="text-button" onClick={refresh}>Retry</button></div>}
    {demoUrl && <section className="panel featured-demo"><div><div className="small-kicker">START WITH A VERIFIED EXAMPLE</div>
      <h2>Did a more complex model improve the forecast?</h2>
      <p>Explore the saved Victoria electricity-demand experiment, see how the evolved model performed after validation, and compare the two adaptive policies on the same dates.</p></div>
      <a className="primary-button" href={demoUrl}>Explore Victoria results <ArrowRight size={15}/></a></section>}
    <div className="overview-grid">
      <section className="panel overview-card"><Database size={20}/><div className="small-kicker">OBSERVATIONS</div><h2>Saved datasets</h2><p>{datasets.length ? `${datasets.length} datasets shown in this workspace` : 'Import regular time-series readings or use the Victoria example.'}</p><button className="text-button" onClick={() => openForecast()}>Select or import readings <ArrowRight size={14}/></button></section>
      <section className="panel overview-card"><ScanLine size={20}/><div className="small-kicker">VICTORIA RELIABILITY</div><h2>{assessment ? statusLabel(assessment.status) : 'Saved reliability replay'}</h2><p>{assessment ? `MAE change ${fmt(assessment.delta_mae)} against a ${fmt(assessment.practical_delta_threshold)} threshold, in source units.` : 'Compare equal forecast leads across historical periods.'}</p><button className="text-button" onClick={openReplay}>Inspect replay evidence <ArrowRight size={14}/></button></section>
      <section className="panel overview-card"><FlaskConical size={20}/><div className="small-kicker">LATEST COMPLETED EXPERIMENT</div><h2>{best ? labels[best[0] as keyof typeof labels] : 'Compare forecasting models'}</h2><p>{best && latest ? `Lowest observed fixed MAE: ${fmt(best[1].mae, 3)} across ${latest.scored_targets} matched targets.` : 'Run a sequential experiment to score all candidates on the same targets.'}</p><button className="text-button" onClick={() => openLab()}>Open Experiment Lab <ArrowRight size={14}/></button></section>
    </div>
    <div className="overview-lists">
      <section className="panel lab-panel"><div className="panel-heading"><div><div className="small-kicker">DATA LIBRARY</div><h2>Choose a dataset</h2></div></div>
        {datasets.length ? <ul className="workspace-list">{datasets.slice(0, 6).map(row => <li key={row.id}><div><strong>{row.name}</strong><small>{row.observations.toLocaleString()} readings · {row.unit} · {date(row.last_timestamp, true)}</small></div><div className="lab-actions"><button className="text-button" onClick={() => openForecast(row.id)}>Forecast</button><button className="text-button" onClick={() => openLab(row.id)}>Experiment <ArrowRight size={13}/></button></div></li>)}</ul> : <p className="lab-muted">No datasets to show yet.</p>}
      </section>
      <section className="panel lab-panel"><div className="panel-heading"><div><div className="small-kicker">RECENT OUTPUT</div><h2>Saved forecasts</h2></div></div>
        {forecasts.length ? <ul className="workspace-list">{forecasts.slice(0, 6).map(row => <li key={row.id}><div><strong>{datasets.find(dataset => dataset.id === row.series_id)?.name ?? 'Saved series'}</strong><small>{row.horizon} steps · {date(row.cutoff, true)} cutoff · {row.unit}</small></div><a className="text-button" href={`?forecast=${encodeURIComponent(row.id)}`}>Open <ArrowRight size={13}/></a></li>)}</ul> : <p className="lab-muted">Forecasts appear here after a successful run.</p>}
      </section>
    </div>
  </main>;
}
