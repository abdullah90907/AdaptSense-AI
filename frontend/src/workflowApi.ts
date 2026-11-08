import type { Evaluation, Forecast } from './types';
import type { InputSeries, Provenance } from './workflow';
const API=import.meta.env.DEV?'/api':'';
export type SavedForecast=Forecast & {id:string;source_provenance?:Provenance|null};
export type Evaluated=Evaluation & {forecast_id:string;reliability:{status:string;method:string;advisory:string};limitations:string};
export async function request<T>(path:string,body?:unknown):Promise<T>{
  let response:Response;
  try{response=await fetch(API+path,body===undefined?undefined:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});}catch{throw new Error('The local backend could not be reached. No automatic retry was made. If a forecast was running, it may have completed on the server.');}
  if(!response.ok){let message='';try{const error=await response.json();message=typeof error.detail==='string'?error.detail:Array.isArray(error.detail)?error.detail.slice(0,3).map((d:{loc?:unknown[];msg?:string})=>`${d.loc?.slice(1).join('.')??'Input'}: ${d.msg??'invalid'}`).join('; '):'';}catch{ /* A proxy may return a plain error response. */ }
    throw new Error(message||(response.status===503?'The cached model could not run. Check the backend and local model cache.':`The backend returned ${response.status}. No automatic retry was made.`));}
  return response.json();
}
export const uploadSeries=(name:string,unit:string,readings:InputSeries['readings'],provenance:Provenance)=>request<InputSeries>('/series',{name,unit,readings,provenance});
export const executeForecast=(series:InputSeries,horizon:number,cutoff=series.readings.at(-1)!.timestamp)=>request<SavedForecast>('/forecasts',{series_id:series.id,cutoff,horizon});
export const evaluateForecast=(forecastId:string,actualSeriesId:string)=>request<Evaluated>(`/forecasts/${encodeURIComponent(forecastId)}/evaluate`,{actual_series_id:actualSeriesId});
