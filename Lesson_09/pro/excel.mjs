import {resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {connect,call,content} from '../lite/lib.mjs';
export const directory=fileURLToPath(new URL('./data',import.meta.url));
const filename=process.env.REQUESTS_FILE||'requests.xlsx';
if(!/^[a-zA-Z0-9._-]+\.xlsx$/.test(filename))throw new Error('REQUESTS_FILE должен быть именем .xlsx без папок');
export const path=resolve(directory,filename),sheet='Заявки';
export const initial=[['ID','Клиент','Проблема','Статус'],[101,'Иван Петров','Ноутбук не включается','Новый'],[102,'Мария Соколова','Принтер не печатает','В работе'],[103,'Олег Иванов','Мерцает монитор','Готово']];
export async function excel(){return connect('excel',{directory});}
export async function invoke(c,name,args,trace){return call(c,name,{path,...args},trace);}
export async function read(c,trace){
 const rows=[];let range;
 do{const r=JSON.parse(content(await invoke(c,'read_range',{sheet,range,max_cells:2000},trace)));if(!Array.isArray(r.values))throw new Error('Неожиданный формат MCP read_range: '+JSON.stringify(r));rows.push(...r.values);range=r.next_range;}while(range);
 while(rows.length&&rows.at(-1).every(x=>x===null||x===''))rows.pop();
 if(JSON.stringify(rows[0])!==JSON.stringify(initial[0]))throw new Error('Ожидаются столбцы ID, Клиент, Проблема, Статус');
 const ids=rows.slice(1).filter(r=>r.some(v=>v!==null&&v!=='' )).map(r=>r[0]);if(ids.some(id=>!Number.isInteger(id))||new Set(ids).size!==ids.length)throw new Error('Некорректные или повторяющиеся ID');return rows;
}
export function text(value,label){if(typeof value!=='string'||!value.trim()||value.length>500)throw new Error(`Уточните ${label}`);if(/^[=+@-]/.test(value.trim()))throw new Error('Текст не должен начинаться с символа формулы');return value.trim();}
export const statuses=['Новый','В работе','Готово'];
export function canonicalStatus(value){const normalized=typeof value==='string'?value.trim().replace(/^[«\"']|[»\"']$/g,'').replace(/\s+/g,' ').toLocaleLowerCase('ru'):'';const status=statuses.find(s=>s.toLocaleLowerCase('ru')===normalized);if(!status)throw new Error('Допустимые статусы: '+statuses.join(', '));return status;}
export async function add(c,args,trace){const client=text(args.client,'имя клиента'),problem=text(args.problem,'проблему клиента');const before=await read(c,trace);const id=Math.max(100,...before.slice(1).map(r=>Number(r[0])||0))+1;const row=[id,client,problem,'Новый'];await invoke(c,'write_range',{sheet,at:`A${before.length+1}`,rows:[row]},trace);const after=await read(c,trace);if(JSON.stringify(after)!==JSON.stringify([...before,row]))throw new Error('Не удалось проверить добавление. Обновите таблицу, прежде чем повторять запрос.');return {answer:`Добавлена заявка №${id}: ${client}, ${problem}. Статус: Новый.`,rows:after};}
export async function propose(c,args,trace){args.status=canonicalStatus(args.status);const rows=await read(c,trace);const matches=rows.slice(1).map((r,i)=>({r,index:i+1})).filter(({r})=>args.id!=null?r[0]===args.id:typeof args.client==='string'&&r[1].toLocaleLowerCase('ru')===args.client.toLocaleLowerCase('ru'));if(matches.length!==1)return {answer:matches.length?'Найдено несколько заявок. Укажите ID.':'Заявка не найдена. Файл не изменён.',rows};const {r,index}=matches[0];return {answer:`Требуется подтверждение изменения заявки №${r[0]} (${r[1]}): «${r[3]}» → «${args.status}».`,rows,pending:{id:r[0],client:r[1],old:r[3],status:args.status,index,before:rows}};}
export async function confirm(c,p,trace){const current=await read(c,trace);if(JSON.stringify(current)!==JSON.stringify(p.before))throw new Error('Таблица изменилась после запроса подтверждения. Запросите изменение заново.');await invoke(c,'write_range',{sheet,at:`D${p.index+1}`,rows:[[p.status]]},trace);const after=await read(c,trace),expected=structuredClone(current);expected[p.index][3]=p.status;if(JSON.stringify(after)!==JSON.stringify(expected))throw new Error('Изменение не удалось проверить. Обновите таблицу.');return {answer:`Статус заявки №${p.id} изменён на «${p.status}». Проверено чтением через MCP.`,rows:after};}
