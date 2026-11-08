import { describe,expect,it,vi,afterEach } from 'vitest';
import { parseReadings,validateReadings,mergeActuals,cadence } from '../src/workflow';
import { executeForecast,request } from '../src/workflowApi';
import type { InputSeries } from '../src/workflow';

const rows=(n=40)=>Array.from({length:n},(_,i)=>({timestamp:new Date(Date.UTC(2024,0,1)+i*3600000).toISOString(),value:100+i}));
const csv=(n=40)=>'timestamp,value\r\n'+rows(n).map(r=>`"${r.timestamp}","${r.value}"`).join('\r\n');
afterEach(()=>vi.unstubAllGlobals());
describe('upload validation and honest actuals',()=>{
  it('parses BOM, quoted CSV and exact decimal values',()=>{const parsed=parseReadings('\uFEFF'+csv());expect(parsed.readings).toEqual(rows());expect(cadence(parsed.readings)).toBe('1 hour');});
  it('accepts a JSON array or named unit-bearing series without losing values',()=>{expect(parseReadings(JSON.stringify(rows())).readings).toEqual(rows());expect(parseReadings(JSON.stringify({name:'Meter',unit:'kWh',readings:rows()}))).toMatchObject({name:'Meter',unit:'kWh'});});
  it('normalizes timezone offsets while recognizing duplicate instants',()=>{const input=rows();input[0].timestamp='2024-01-01T05:00:00+05:00';expect(validateReadings(input)[0].timestamp).toBe(rows()[0].timestamp);input[1].timestamp=input[0].timestamp;expect(()=>validateReadings(input)).toThrow('sorted and unique');});
  it.each(['2024-01-01','2024-02-30T00:00:00Z','2024-01-01T00:00:00','2024-01-01T25:00:00Z'])('rejects ambiguous or invalid timestamps: %s',timestamp=>{const input=rows();input[0].timestamp=timestamp;expect(()=>validateReadings(input)).toThrow();});
  it('rejects gaps, missing values, negatives and nonfinite data',()=>{const input=rows();input.splice(10,1);expect(()=>validateReadings(input)).toThrow('regular interval');for(const value of [-1,NaN,Infinity])expect(()=>validateReadings([{...rows()[0],value},...rows().slice(1)])).toThrow('finite, nonnegative');expect(()=>parseReadings(csv().replace('100"','"'))).toThrow('empty');});
  it('rejects insufficient history, malformed JSON, missing columns and oversized data',()=>{expect(()=>parseReadings(csv(31))).toThrow('at least 32');expect(()=>parseReadings('{readings:[]}')).toThrow('JSON');expect(()=>parseReadings('date,value\n2024-01-01,1')).toThrow('timestamp column');expect(()=>parseReadings(' '.repeat(2_000_001))).toThrow('2 MB');});
  it('allows one later actual by merging unchanged history without requiring 32 new readings',()=>{const history=rows(40),actual=rows(41).slice(-1);const parsed=parseReadings(JSON.stringify(actual),1);const merged=mergeActuals(history,[],parsed.readings,'kWh');expect(merged).toHaveLength(41);expect(merged.slice(0,40)).toEqual(history);});
  it('accepts a full later snapshot and deduplicates only identical observations',()=>{expect(mergeActuals(rows(40),[],rows(60),'kWh','kWh')).toEqual(rows(60));});
  it('refuses unit conflicts, revised actuals, off-grid timestamps and missing intervening actuals',()=>{expect(()=>mergeActuals(rows(40),[],rows(41),'kWh','GW')).toThrow('forecast unit');const changed=rows(41);changed[0].value=500;expect(()=>mergeActuals(rows(40),[],changed,'kWh')).toThrow('conflicts');const prior=rows(41);const revised=[{...prior.at(-1)!,value:0}];expect(()=>mergeActuals(rows(40),prior,revised,'kWh')).toThrow('conflicts');expect(()=>mergeActuals(rows(40),[],[{timestamp:'2024-01-02T15:30:00Z',value:20}],'kWh')).toThrow('interval');expect(()=>mergeActuals(rows(40),[],rows(42).slice(-1),'kWh')).toThrow('no gaps');});
  it('submits only the saved series ID, last historical timestamp and horizon to inference',async()=>{const mocked=vi.fn(async()=>new Response(JSON.stringify({id:'saved'}),{status:201}));vi.stubGlobal('fetch',mocked);const series={id:'history',name:'Meter',unit:'kWh',readings:rows()} as InputSeries;await executeForecast(series,12);const [path,init]=mocked.mock.calls[0] as unknown as [string,RequestInit];expect(path).toContain('/forecasts');expect(JSON.parse(init.body as string)).toEqual({series_id:'history',cutoff:rows().at(-1)!.timestamp,horizon:12});});
  it('surfaces backend field errors and never automatically retries a failed inference request',async()=>{const mocked=vi.fn(async()=>new Response(JSON.stringify({detail:[{loc:['body','readings',1,'timestamp'],msg:'Invalid timestamp'}]}),{status:422}));vi.stubGlobal('fetch',mocked);await expect(request('/series',{})).rejects.toThrow('readings.1.timestamp: Invalid timestamp');expect(mocked).toHaveBeenCalledTimes(1);});
});

it('rejects non-decimal CSV coercion and retains actual intraday UTC times',async()=>{
  expect(()=>parseReadings(csv().replace('100"','0x10"'))).toThrow('decimal number');
  const {fullTimestamp}=await import('../src/workflow');
  expect(fullTimestamp('2024-01-01T15:30:00+05:00')).toBe('2024-01-01 10:30:00 UTC');
  expect(fullTimestamp('2024-01-01T15:30:00.125Z')).toBe('2024-01-01 15:30:00.125 UTC');
});
