import { useEffect, useRef, useState } from 'react';
import { date, fmt, linePath } from './data';
import type { PlotPoint } from './types';

export function DemandChart({points,cutoff,active,onActive,layers,intraday=false}:{points:PlotPoint[];intraday?:boolean;cutoff:string;active:number;onActive:(i:number)=>void;layers:{actual:boolean;point:boolean;interval:boolean;baseline?:boolean}}) {
  const ref=useRef<HTMLDivElement>(null);
  const [width,setWidth]=useState(800);
  useEffect(()=>{const el=ref.current;if(!el)return;const observer=new ResizeObserver(([entry])=>setWidth(Math.max(300,entry.contentRect.width)));observer.observe(el);return()=>observer.disconnect();},[]);
  const height=280,left=45,right=20,top=28,bottom=32;
  const numbers=points.flatMap(p=>[p.actual,p.point,p.q10,p.q90,p.baseline].filter((v):v is number=>v!==undefined));
  const min=Math.floor((Math.min(...numbers)-8)/10)*10, max=Math.ceil((Math.max(...numbers)+8)/10)*10;
  const x=(i:number)=>left+i/Math.max(points.length-1,1)*(width-left-right);
  const y=(n:number)=>height-bottom-(n-min)/Math.max(max-min,1)*(height-top-bottom);
  const index=Math.min(Math.max(active,0),points.length-1),current=points[index];
  const band=points.map((p,i)=>({p,i})).filter(({p})=>p.q10!==undefined&&p.q90!==undefined);
  const area=band.length ? 'M'+band.map(({p,i})=>`${x(i)},${y(p.q90!)}`).join(' L')+' L'+[...band].reverse().map(({p,i})=>`${x(i)},${y(p.q10!)}`).join(' L')+' Z':'';
  const cutoffIndex=points.findIndex(p=>new Date(p.timestamp).getTime()===new Date(cutoff).getTime());
  const tickCount=intraday&&width<500?3:5;
  const ticks=Array.from({length:tickCount},(_,i)=>Math.round(i*(points.length-1)/(tickCount-1)));
  return <div ref={ref} className="chart-wrap" tabIndex={0} role="group" aria-label="Demand chart. Use left and right arrow keys to inspect readings." onKeyDown={e=>{if(['ArrowLeft','ArrowRight'].includes(e.key)){e.preventDefault();onActive(Math.min(points.length-1,Math.max(0,index+(e.key==='ArrowRight'?1:-1))));}}}>
    <svg className="demand-chart" width="100%" height={height} viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`Electricity demand and saved forecast from ${date(points[0].timestamp,true)} to ${date(points.at(-1)!.timestamp,true)}`} onPointerMove={e=>{const bounds=e.currentTarget.getBoundingClientRect();onActive(Math.min(points.length-1,Math.max(0,Math.round(((e.clientX-bounds.left)/bounds.width*width-left)/(width-left-right)*(points.length-1)))));}}>
      <defs><linearGradient id="forecast-band" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="var(--accent)" stopOpacity=".22"/><stop offset="100%" stopColor="var(--accent)" stopOpacity=".035"/></linearGradient></defs>
      {[0,1,2,3,4].map(i=>{const n=min+(max-min)*i/4;return <g key={i}><line x1={left} y1={y(n)} x2={width-right} y2={y(n)} stroke="var(--chart-grid)" strokeDasharray="3 5"/><text x={left-12} y={y(n)+4} textAnchor="end" className="axis-label">{fmt(n,0)}</text></g>;})}
      {cutoffIndex>=0&&<g><rect x={x(cutoffIndex)} y={top} width={Math.max(0,width-right-x(cutoffIndex))} height={height-top-bottom} fill="var(--accent)" opacity=".025"/><line x1={x(cutoffIndex)} x2={x(cutoffIndex)} y1={top-8} y2={height-bottom} stroke="var(--chart-cursor)" strokeDasharray="3 5"/><text x={Math.max(left+4,Math.min(width-130,x(cutoffIndex)+9))} y={14} className="chart-kicker">FORECAST ORIGIN</text></g>}
      {layers.interval&&<path d={area} fill="url(#forecast-band)" className="band-enter"/>}
      {layers.baseline&&<path d={linePath(points,'baseline',x,y)} fill="none" stroke="var(--amber)" strokeWidth="1.6" strokeDasharray="4 5"/>}
      {layers.actual&&<path d={linePath(points,'actual',x,y)} fill="none" stroke="var(--chart-actual)" strokeWidth="1.7" strokeLinejoin="round" className="chart-line" pathLength="1"/>}
      {layers.point&&<path d={linePath(points,'point',x,y)} fill="none" stroke="var(--accent)" strokeWidth="2.4" strokeLinejoin="round" className="chart-line forecast-line" pathLength="1"/>}
      {current&&<g><line x1={x(index)} x2={x(index)} y1={top} y2={height-bottom} stroke="var(--chart-cursor)" strokeDasharray="2 4"/>{layers.actual&&current.actual!==undefined&&<circle cx={x(index)} cy={y(current.actual)} r="4" fill="var(--chart-actual)" stroke="var(--surface)" strokeWidth="2"/>}{layers.point&&current.point!==undefined&&<circle cx={x(index)} cy={y(current.point)} r="4" fill="var(--accent)" stroke="var(--surface)" strokeWidth="2"/>}</g>}
      {ticks.map(i=><text key={i} x={x(i)} y={height-6} textAnchor={i===0?'start':i===points.length-1?'end':'middle'} className="axis-label">{intraday?new Intl.DateTimeFormat('en-GB',{hour:'2-digit',minute:'2-digit',timeZone:'UTC'}).format(new Date(points[i].timestamp)):date(points[i].timestamp)}</text>)}
    </svg>
    <div className="chart-inspection"><span className="live-dot"/><span>{current?date(current.timestamp,true):'Inspect a reading'}</span><span className="inspection-values">Actual <b>{current?.actual!==undefined?fmt(current.actual):'—'}</b><i/>Median <b className="mint">{current?.point!==undefined?fmt(current.point):'—'}</b></span><span className="utc-label">{current?new Date(current.timestamp).toISOString().slice(11,16):'—'} UTC</span></div>
    <input className="scrubber" type="range" aria-label="Inspect reading" min="0" max={points.length-1} value={index} onChange={e=>onActive(Number(e.target.value))} aria-valuetext={current?`${date(current.timestamp,true)}, actual ${current.actual!==undefined?fmt(current.actual):'unavailable'}, forecast ${current.point!==undefined?fmt(current.point):'unavailable'}`:''}/>
  </div>;
}

export function ErrorTimeline({origins,onSelect}:{origins:{cutoff:string;mae:number;evidence:{baseline_absolute_error:number}[]}[];onSelect:(i:number)=>void}) {
  const values=origins.map(o=>({model:o.mae,baseline:o.evidence.reduce((s,r)=>s+r.baseline_absolute_error,0)/o.evidence.length}));
  const max=Math.ceil(Math.max(...values.flatMap(v=>[v.model,v.baseline]))/10)*10;
  const x=(i:number)=>38+i/(values.length-1)*880,y=(n:number)=>166-n/max*140;
  return <svg viewBox="0 0 940 200" className="error-timeline" role="img" aria-label="Mean absolute error by nonoverlapping chronological forecast origin">
    <rect x="478" y="20" width="440" height="146" fill="var(--accent)" opacity=".025"/>
    {[0,.5,1].map(t=><g key={t}><line x1="38" y1={y(t*max)} x2="918" y2={y(t*max)} stroke="var(--chart-grid)" strokeDasharray="3 5"/><text x="25" y={y(t*max)+4} textAnchor="end" className="axis-label">{t*max}</text></g>)}
    <line x1="478" x2="478" y1="20" y2="166" stroke="var(--chart-cursor)" strokeDasharray="3 5"/>
    <path d={values.map((v,i)=>`${i?'L':'M'}${x(i)},${y(v.baseline)}`).join(' ')} fill="none" stroke="var(--amber)" strokeWidth="1.7" strokeDasharray="4 4"/>
    <path d={values.map((v,i)=>`${i?'L':'M'}${x(i)},${y(v.model)}`).join(' ')} fill="none" stroke="var(--accent)" strokeWidth="2"/>
    {origins.map((o,i)=><g key={o.cutoff}><circle cx={x(i)} cy={y(o.mae)} r="9" fill="transparent" tabIndex={0} role="button" aria-label={`Inspect origin ${date(o.cutoff,true)}, MAE ${fmt(o.mae)}`} onClick={()=>onSelect(i)} onKeyDown={e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();onSelect(i);}}}><title>{date(o.cutoff)} · Chronos MAE {fmt(o.mae)} · Baseline {fmt(values[i].baseline)}</title></circle><circle pointerEvents="none" cx={x(i)} cy={y(o.mae)} r="2" fill="var(--accent)"/></g>)}
    {[0,Math.floor(origins.length/2),origins.length-1].map(i=><text key={i} x={x(i)} y="190" textAnchor={i===0?'start':i===origins.length-1?'end':'middle'} className="axis-label">{date(origins[i].cutoff)}</text>)}
  </svg>;
}



