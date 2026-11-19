import assert from 'node:assert/strict';
import {writeFile} from 'node:fs/promises';
import {weather} from './server.mjs';
let history=[];const results=[];
for(const message of ['Какая сейчас погода в Екатеринбурге?','А в Казани?']){
 const r=await weather(message,history);history=r.history;results.push({message,...r});
 console.log(message,r.answer);assert(!r.error,r.answer);assert(r.trace.some(t=>t.tool.includes('weather')&&t.result&&!t.error),'Нет успешного погодного вызова');
}
process.env.WEATHER_MCP_URL='http://127.0.0.1:1/mcp';const failure=await weather('Какая погода в Москве?');assert(failure.error);results.push(failure);
await writeFile('evidence/verification.json',JSON.stringify(results,null,2));
