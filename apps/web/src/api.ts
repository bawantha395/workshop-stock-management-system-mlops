import {UserManager, WebStorageStateStore} from 'oidc-client-ts';
declare global {interface Window {STOCKLANE_CONFIG:{authMode:string;authority:string;clientId:string;scope:string;apiBase?:string;logoutUrl?:string}}}
export const config=window.STOCKLANE_CONFIG;
export const auth=config.authMode==='cognito'?new UserManager({authority:config.authority,client_id:config.clientId,redirect_uri:location.origin+'/auth/callback',post_logout_redirect_uri:location.origin,response_type:'code',scope:config.scope,userStore:new WebStorageStateStore({store:sessionStorage}),automaticSilentRenew:true}):null;
export async function headers(){
 const result:Record<string,string>={};
 if(auth){const user=await auth.getUser();if(user&&!user.expired)result.Authorization='Bearer '+user.access_token;}
 else result['X-Demo-User']=localStorage.getItem('stocklane.role')||'owner';
 return result;
}
export class ApiError extends Error { constructor(message:string,public status:number){super(message);this.name="ApiError";} }
export async function api<T=any>(path:string,options:RequestInit={},key?:string):Promise<T>{
 const h=new Headers(await headers());new Headers(options.headers).forEach((v,k)=>h.set(k,v));
 if(options.body&&!(options.body instanceof FormData))h.set('Content-Type','application/json');
 if(key)h.set('Idempotency-Key',key);
 const response=await fetch((config.apiBase||'')+path,{...options,headers:h});
 if(!response.ok){let message='The service is unavailable. Keep this form open and retry.';try{const e=await response.json();message=e.message||e.detail||message;}catch{/* keep safe fallback */}if(response.status===401)message='Sign in to continue.';throw new ApiError(message,response.status);}
 if(response.status===204)return undefined as T;
 return response.json();
}
export async function download(path:string,name:string){const response=await fetch((config.apiBase||'')+path,{headers:await headers()});if(!response.ok)throw new Error('The file could not be downloaded');const url=URL.createObjectURL(await response.blob());const a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
export type Product={id:string;sku:string;name:string;category:string;brand:string;grade:string;capacity:string;barcode:string|null;unit:string;quantity:number;selling_price:number;reorder_level:number;image_id:string|null};
export type Job={id:string;customer:string;vehicle:string;registration:string;phone:string;summary:string;status:string;created_at:string};
export type Movement={id:string;product_id:string;sku:string;name:string;unit:string;kind:string;quantity:number;unit_price:number;balance?:number;job_id:string|null;issue_id:string|null;actor:string;receiver_name?:string|null;note:string;created_at:string};
export type Draft={id:string;image_id:string;fields:Record<string,string>;suggestions?:Record<string,string>;ai?:{status:string;code?:string;message?:string};source:string;status:string;created_at:string;product_id:string|null;captureId?:string};
export type Invoice={id:string;job_id:string;invoice_number:string;labour:number;total:number;created_at:string};
export type Match={identifiedProductId?:string;qrValue?:string;imageId:string;state:string;modelVersion:string;candidates:{product:Product;imageId:string;similarity:number;sameSkuEstimate?:number|null}[];message:string};
export type BarcodeLookup={barcode:string;found:boolean;suggestions:Record<string,string>};
export function csv(name:string,rows:Record<string,unknown>[]){if(!rows.length)return;const keys=Object.keys(rows[0]);const escape=(x:unknown)=>'"'+String(x??'').replace(/^[=+@-]/,"'$&").replaceAll('"','""')+'"';const blob=new Blob([[keys.map(escape).join(','),...rows.map(r=>keys.map(k=>escape(r[k])).join(','))].join('\r\n')],{type:'text/csv;charset=utf-8;'});const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download=name;a.click();URL.revokeObjectURL(url);}


export async function signOut(){await auth?.removeUser();if(config.logoutUrl)location.assign(config.logoutUrl+'?client_id='+encodeURIComponent(config.clientId)+'&logout_uri='+encodeURIComponent(location.origin));else if(auth)await auth.signoutRedirect();}
