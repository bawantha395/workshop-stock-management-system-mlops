import { test } from "node:test";
import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";
import { JSDOM } from "jsdom";
import { build } from "esbuild";
test("forecast labels ML and requires explicit history confirmation before snapshot",async()=>{
 const root=fileURLToPath(new URL("..",import.meta.url));
 const result=await build({stdin:{contents:`import React from 'react';import {createRoot} from 'react-dom/client';import {StockForecast} from './src/StockForecast';const root=createRoot(document.getElementById('root'));window.cleanup=()=>root.unmount();root.render(<StockForecast/>);`,resolveDir:root,loader:"tsx"},bundle:true,write:false,format:"iife",platform:"browser",define:{"process.env.NODE_ENV":'"production"'}});
 const dom=new JSDOM('<div id="root"></div>',{url:'https://stock.test',runScripts:'dangerously'}),w=dom.window;w.Headers=Headers;w.STOCKLANE_CONFIG={authMode:'local'};const writes=[];
 w.fetch=async(url,options)=>{if(options?.method==='POST'){writes.push(JSON.parse(options.body));return new Response(JSON.stringify({message:'History prepared.'}),{status:200});}return new Response(JSON.stringify({status:'ready',message:'Usage estimates',products:[{id:'p',sku:'FILTER',name:'AC filter',unit:'UNIT',availableNow:5,next7:8,next30:32,suggestedTopUp7:3,status:'trained_ml',message:'Passed held-out test'}]}),{status:200});};
 w.eval(result.outputFiles[0].text);await new Promise(r=>setTimeout(r,80));assert.match(w.document.body.textContent,/Trained ML/);assert.match(w.document.body.textContent,/AC filter/);
 const button=[...w.document.querySelectorAll('button')].find(b=>b.textContent==='Prepare forecast history');assert.equal(button.disabled,true);const check=w.document.querySelector('input[type="checkbox"]');check.click();await new Promise(r=>setTimeout(r,20));assert.equal(button.disabled,false);button.click();await new Promise(r=>setTimeout(r,30));assert.equal(writes.length,1);assert.equal(writes[0].historyConfirmed,true);assert.ok(writes[0].historyFrom);w.cleanup();dom.window.close();
});
