import { describe, expect, it, vi, afterEach } from 'vitest';
import { date, forecastPoints, get, linePath, loadWorkspace, statusLabel } from '../src/data';
import type { Workspace } from '../src/types';

afterEach(()=>vi.unstubAllGlobals());
describe('evidence display integrity',()=>{
  it('joins equivalent UTC timestamps without duplicating actuals or inventing forecast points',()=>{
    const data={series:{readings:[{timestamp:'2014-01-01T00:00:00Z',value:10},{timestamp:'2014-01-02T00:00:00Z',value:11}]},forecast:{predictions:[{timestamp:'2014-01-02T00:00:00+00:00',point:12,q50:12,q10:9,q90:15}]}} as Workspace;
    const rows=forecastPoints(data);
    expect(rows).toHaveLength(2);expect(rows[0].point).toBeUndefined();expect(rows[1]).toMatchObject({actual:11,point:12,q10:9,q90:15});
  });
  it('breaks plotted lines at missing predictions',()=>{
    expect(linePath([{timestamp:'a',point:1},{timestamp:'b'},{timestamp:'c',point:3}],'point',i=>i,n=>n)).toBe('M0.00,1.00  M2.00,3.00');
  });
  it('formats dates in UTC and preserves the three analytical classifications',()=>{
    expect(date('2014-12-31T23:30:00-02:00',true)).toBe('1 Jan 2015');
    expect(statusLabel('possible_deterioration')).toBe('Possible deterioration');
    expect(statusLabel('deterioration_supported')).toBe('Deterioration supported');
    expect(statusLabel('no_deterioration_detected')).toBe('No deterioration detected');
  });
  it('loads actual saved records and backend evaluation only through GET',async()=>{
    const mock=vi.fn(async(url:string,_options?:RequestInit)=>new Response(JSON.stringify(url.endsWith('/demo')?{series_id:'s',forecast_id:'f',replay_id:'r'}:url.includes('/evaluation?')?{metrics:{mae:11.833980992903806},matched:32}:url.includes('/series/')?{readings:[]}:url.includes('/forecasts/')?{predictions:[]}:{origins:[]}),{status:200,headers:{'Content-Type':'application/json'}}));
    vi.stubGlobal('fetch',mock);
    const result=await loadWorkspace(new AbortController().signal);
    expect(result.evaluation.metrics.mae).toBe(11.833980992903806);expect(mock).toHaveBeenCalledTimes(5);
    expect(mock.mock.calls.every(([,options])=>!options||!('method' in options))).toBe(true);
    expect(mock.mock.calls.some(([url])=>url.includes('actual_series_id=s'))).toBe(true);
  });
  it('fails explicitly instead of falling back to fabricated demo results',async()=>{
    vi.stubGlobal('fetch',vi.fn(async()=>new Response('',{status:404})));
    await expect(get('/demo')).rejects.toThrow('Saved demonstration evidence is unavailable');
  });
});

