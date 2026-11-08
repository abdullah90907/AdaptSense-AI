import type { PlotPoint, Workspace, Catalog, Forecast, Replay, Reading, Evaluation } from './types';
const API = import.meta.env.DEV ? '/api' : '';
export async function get<T>(path:string, signal?:AbortSignal):Promise<T> {
  const response = await fetch(API + path, {signal});
  if (!response.ok) throw new Error(response.status === 404 ? 'Saved demonstration evidence is unavailable. Seed the Victoria demo, then reconnect.' : `The local evidence service returned ${response.status}. Check that the backend is running.`);
  return response.json();
}
export async function loadWorkspace(signal:AbortSignal):Promise<Workspace> {
  const catalog = await get<Catalog>('/demo', signal);
  const [series, forecast, replay, evaluation] = await Promise.all([
    get<{name:string;unit:string;readings:Reading[]}>(`/series/${catalog.series_id}`,signal),
    get<Forecast>(`/forecasts/${catalog.forecast_id}`,signal), get<Replay>(`/replays/${catalog.replay_id}`,signal),
    get<Evaluation>(`/forecasts/${catalog.forecast_id}/evaluation?actual_series_id=${encodeURIComponent(catalog.series_id)}`,signal)
  ]);
  return {catalog,series,forecast,replay,evaluation};
}
export function forecastPoints(data:Workspace):PlotPoint[] {
  const values = new Map(data.series.readings.map(r=>[new Date(r.timestamp).getTime(), {timestamp:r.timestamp,actual:r.value} as PlotPoint]));
  data.forecast.predictions.forEach(p=>{
    const key = new Date(p.timestamp).getTime();
    values.set(key,{...values.get(key),...p, timestamp:p.timestamp});
  });
  return [...values.values()].sort((a,b)=>new Date(a.timestamp).getTime()-new Date(b.timestamp).getTime());
}
export function linePath(points:PlotPoint[], field:keyof PlotPoint, x:(i:number)=>number,y:(n:number)=>number):string {
  let open=false;
  return points.map((p,i)=>{const value=p[field]; if(typeof value!=='number'){open=false;return '';} const command=open?'L':'M'; open=true;return `${command}${x(i).toFixed(2)},${y(value).toFixed(2)}`;}).join(' ');
}
export const fmt=(n:number,digits=2)=>new Intl.NumberFormat('en-US',{minimumFractionDigits:digits,maximumFractionDigits:digits}).format(n);
export const date=(s:string,full=false)=>new Intl.DateTimeFormat('en-GB',{day:'numeric',month:'short',...(full ? {year:'numeric' as const}:{}),timeZone:'UTC'}).format(new Date(s));
export function statusLabel(status:string){return status === 'deterioration_supported'?'Deterioration supported':status === 'possible_deterioration'?'Possible deterioration':status === 'no_deterioration_detected'?'No deterioration detected':'Classification unavailable';}

