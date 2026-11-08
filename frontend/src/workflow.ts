import type { Reading } from './types';
export type Provenance={kind:'csv_upload'|'json_upload'|'pasted_csv'|'pasted_json'|'demo'|'submitted_actuals';label:string;sha256?:string;note:string};
export type ParsedReadings={readings:Reading[];name?:string;unit?:string};
export type InputSeries={id:string;name:string;unit:string;readings:Reading[];provenance?:Provenance|null};
export const MAX_BYTES=2_000_000;

function csvRows(text:string):string[][]{
  const rows:string[][]=[];let row:string[]=[],cell='',quoted=false;
  for(let i=0;i<text.length;i++){
    const char=text[i];
    if(char==='"'){if(quoted&&text[i+1]==='"'){cell+='"';i++;}else if(quoted||cell==='')quoted=!quoted;else throw new Error('Invalid CSV quoting. Use timestamp,value columns.');}
    else if(char===','&&!quoted){row.push(cell);cell='';}
    else if((char==='\n'||char==='\r')&&!quoted){row.push(cell);if(row.some(c=>c.trim()))rows.push(row);row=[];cell='';if(char==='\r'&&text[i+1]==='\n')i++;}
    else cell+=char;
  }
  if(quoted)throw new Error('A CSV quoted field is not closed.');
  row.push(cell);if(row.some(c=>c.trim()))rows.push(row);return rows;
}
function timestamp(value:unknown,row:number):string{
  if(typeof value!=='string')throw new Error(`Row ${row}: timestamp must be an ISO date and time with Z or an explicit offset.`);
  const match=value.trim().match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2})(?:\.(\d{1,3}))?)?(Z|[+-]\d{2}:\d{2})$/);
  if(!match)throw new Error(`Row ${row}: use an ISO timestamp with Z or an offset, for example 2014-01-01T00:00:00Z.`);
  const [,year,month,day,hour,minute,second,,offset]=match;
  const days=new Date(Date.UTC(Number(year),Number(month),0)).getUTCDate();
  if(Number(year)<1||Number(month)<1||Number(month)>12||Number(day)<1||Number(day)>days||Number(hour)>23||Number(minute)>59||Number(second??0)>59||(offset!=='Z'&&(Number(offset.slice(1,3))>23||Number(offset.slice(4))>59)))throw new Error(`Row ${row}: invalid calendar date, time or timezone offset.`);
  const ms=Date.parse(value.trim());if(!Number.isFinite(ms))throw new Error(`Row ${row}: invalid timestamp.`);return new Date(ms).toISOString();
}
export function validateReadings(rows:unknown[],minimum=32):Reading[]{
  if(rows.length<minimum)throw new Error(`Provide at least ${minimum} reading${minimum===1?'':'s'}; received ${rows.length}.`);
  if(rows.length>20000)throw new Error('The limit is 20,000 readings per upload.');
  const readings=rows.map((item,i)=>{if(!item||typeof item!=='object')throw new Error(`Row ${i+1}: expected timestamp and value.`);const row=item as Record<string,unknown>;
    if(typeof row.value!=='number'||!Number.isFinite(row.value)||row.value<0)throw new Error(`Row ${i+1}: value must be a finite, nonnegative number.`);
    return {timestamp:timestamp(row.timestamp,i+1),value:row.value};});
  const step=readings.length>1?Date.parse(readings[1].timestamp)-Date.parse(readings[0].timestamp):0;
  for(let i=1;i<readings.length;i++){const delta=Date.parse(readings[i].timestamp)-Date.parse(readings[i-1].timestamp);if(delta<=0)throw new Error(`Row ${i+1}: timestamps must be sorted and unique.`);if(delta!==step)throw new Error(`Row ${i+1}: readings must have a regular interval with no gaps. No values are imputed.`);}
  return readings;
}
export function parseReadings(text:string,minimum=32):ParsedReadings{
  if(new TextEncoder().encode(text).length>MAX_BYTES)throw new Error('The upload limit is 2 MB.');
  text=text.replace(/^\uFEFF/,'').trim();if(!text)throw new Error('Choose a CSV/JSON file or paste readings first.');
  if(text.startsWith('[')||text.startsWith('{')){
    let parsed:unknown;try{parsed=JSON.parse(text);}catch{throw new Error('The JSON could not be read. Use an array of timestamp/value objects or an object containing readings.');}
    if(Array.isArray(parsed))return {readings:validateReadings(parsed,minimum)};
    if(parsed&&typeof parsed==='object'&&'readings' in parsed){const record=parsed as Record<string,unknown>;if(!Array.isArray(record.readings))throw new Error('JSON readings must be an array.');
      for(const key of ['name','unit'])if(record[key]!==undefined&&typeof record[key]!=='string')throw new Error(`JSON ${key} must be text.`);
      return {readings:validateReadings(record.readings,minimum),name:record.name as string|undefined,unit:record.unit as string|undefined};}
    throw new Error('JSON must be an array of readings or an object with a readings array.');
  }
  const rows=csvRows(text);const headers=rows.shift()?.map(h=>h.trim());
  if(!headers||headers.filter(h=>h==='timestamp').length!==1||headers.filter(h=>h==='value').length!==1)throw new Error('CSV needs one timestamp column and one value column.');
  const ti=headers.indexOf('timestamp'),vi=headers.indexOf('value');
  return {readings:validateReadings(rows.map((row,i)=>{if(row.length!==headers.length)throw new Error(`CSV row ${i+2}: column count does not match the header.`);if(!row[vi].trim())throw new Error(`CSV row ${i+2}: value is empty.`);if(!/^[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?$/.test(row[vi].trim()))throw new Error(`CSV row ${i+2}: value must be a decimal number.`);return {timestamp:row[ti].trim(),value:Number(row[vi])};}),minimum)};
}
export function mergeActuals(history:Reading[],known:Reading[],incoming:Reading[],unit:string,incomingUnit?:string):Reading[]{
  if(incomingUnit!==undefined&&incomingUnit.trim()!==unit)throw new Error(`Actual readings must use the forecast unit: ${unit}.`);
  const cutoff=Date.parse(history.at(-1)!.timestamp),step=Date.parse(history[1].timestamp)-Date.parse(history[0].timestamp);
  const merged=new Map([...history,...known].map(r=>[Date.parse(r.timestamp),r]));
  for(const reading of incoming){const time=Date.parse(reading.timestamp),old=merged.get(time);
    if(old&&old.value!==reading.value)throw new Error('An uploaded value conflicts with saved history or previously submitted actuals. Existing observations are not replaced.');
    if(time<=cutoff&&!old)throw new Error('Actuals cannot extend or change the historical forecast context.');
    if(time>cutoff&&(time-cutoff)%step!==0)throw new Error('Actual timestamps must match the original forecast interval.');
    merged.set(time,reading);
  }
  return validateReadings([...merged.values()].sort((a,b)=>Date.parse(a.timestamp)-Date.parse(b.timestamp)));
}
export function cadence(readings:Reading[]):string{
  const ms=Date.parse(readings[1].timestamp)-Date.parse(readings[0].timestamp);
  for(const [size,label] of [[86400000,'day'],[3600000,'hour'],[60000,'minute'],[1000,'second']] as const)if(ms%size===0){const n=ms/size;return `${n} ${label}${n===1?'':'s'}`;}
  return `${ms} milliseconds`;
}
export function fullTimestamp(value:string):string{return new Date(value).toISOString().replace('T',' ').replace(/(?:\.000)?Z$/,' UTC');}
export async function hashSource(bytes:ArrayBuffer):Promise<string>{const hash=await crypto.subtle.digest('SHA-256',bytes);return [...new Uint8Array(hash)].map(b=>b.toString(16).padStart(2,'0')).join('');}

