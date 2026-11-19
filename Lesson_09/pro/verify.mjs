import assert from 'node:assert/strict';
import {writeFile} from 'node:fs/promises';
process.env.REQUESTS_FILE=`test-${Date.now()}.xlsx`;
const {handle}=await import('./server.mjs');
const {excel,invoke,initial,sheet}=await import('./excel.mjs');
const setupClient=await excel();try{await invoke(setupClient,'create_workbook',{sheets:[sheet]},[]);await invoke(setupClient,'write_range',{sheet,at:'A1',rows:initial},[]);}finally{await setupClient.close();}
const session={history:[]},results=[];
async function ask(input){const r=await handle(input,session);results.push({input,...r});await writeFile('evidence/verification.json',JSON.stringify(results,null,2));console.log(JSON.stringify({input,answer:r.answer,error:r.error,pending:!!r.pending}));assert(!r.error,r.answer);return r;}
const baseline=await ask({refresh:true});assert.equal(baseline.rows.length,4,'Тест рассчитан на исходные три заявки. Не запускайте на рабочих данных.');
const added=await ask({message:'Добавь заявку от Анны Смирновой: ноутбук сильно тормозит'});assert.equal(added.rows?.[4]?.[0],104);assert.equal(added.rows[4][3],'Новый');
const proposed=await ask({message:'Измени статус заявки Анны Смирновой на "В работе"'});assert.equal(proposed.pending?.id,104);assert.equal(proposed.rows[4][3],'Новый');assert(!proposed.trace.some(t=>t.tool==='write_range'));
const changed=await ask({confirm:true});assert.equal(changed.rows[4][3],'В работе');assert.deepEqual(changed.rows.slice(0,4),baseline.rows);assert.deepEqual(changed.rows[4].slice(0,3),added.rows[4].slice(0,3));
const filtered=await ask({message:'Покажи все заявки со статусом "В работе"'});assert.deepEqual(filtered.rows.slice(1).map(r=>r[0]),[102,104]);
const missing=await ask({message:'Измени статус заявки №999 на "Готово"'});assert.match(missing.answer,/не найдена/i);assert(!missing.trace.some(t=>t.tool==='write_range'));
const incomplete=await ask({message:'Добавь новую заявку от Дмитрия'});assert(!incomplete.trace.some(t=>t.tool==='write_range'));assert.match(incomplete.answer,/проблем|неисправ|случил/i);
const final=await ask({refresh:true});assert.deepEqual(final.rows,changed.rows);console.log('Все сценарии Pro пройдены.');
