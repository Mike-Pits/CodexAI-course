import 'dotenv/config';
import {Client} from '@modelcontextprotocol/sdk/client/index.js';
import {StreamableHTTPClientTransport} from '@modelcontextprotocol/sdk/client/streamableHttp.js';
import {StdioClientTransport} from '@modelcontextprotocol/sdk/client/stdio.js';
export async function connect(kind,{directory}={}){
 const client=new Client({name:`homework-${kind}`,version:'1.0.0'});
 const transport=kind==='weather'?new StreamableHTTPClientTransport(new URL(process.env.WEATHER_MCP_URL||'https://weather.chukai.io/mcp')):new StdioClientTransport({command:process.env.EXCEL_MCP_COMMAND||'../.venv/bin/excel-mcp-server',args:['stdio','--allow-dir',directory||process.cwd()],stderr:'inherit'});
 try {await client.connect(transport);return client;} catch(e){await transport.close().catch(()=>{});throw e;}
}
export async function call(client,name,args,trace){
 const entry={time:new Date().toISOString(),tool:name,arguments:args};trace.push(entry);
 try {const result=await client.callTool({name,arguments:args},undefined,{timeout:45000});entry.result=result;console.log(JSON.stringify(entry));if(result.isError)throw new Error(JSON.stringify(result.content));return result;}
 catch(e){entry.error=e.message;throw e;}
}
export function content(result){return result.content?.filter(x=>x.type==='text').map(x=>x.text).join('\n')||JSON.stringify(result);}
export async function completion(messages,tools){
 if(!process.env.LLM_API_KEY)throw new Error('LLM не настроена. Укажите LLM_API_KEY, LLM_BASE_URL и LLM_MODEL в .env.');
 const response=await fetch(`${(process.env.LLM_BASE_URL||'https://api.openai.com/v1').replace(/\/$/,'')}/chat/completions`,{method:'POST',headers:{'Content-Type':'application/json',Authorization:`Bearer ${process.env.LLM_API_KEY}`},body:JSON.stringify({temperature:0,model:process.env.LLM_MODEL||'gpt-4.1-mini',messages:messages.map((m,i)=>i===0&&process.env.LLM_MODEL?.startsWith('qwen3')?{...m,content:m.content+' /no_think'}:m),tools,parallel_tool_calls:false}),signal:AbortSignal.timeout(90000)});
 if(!response.ok)throw new Error(`LLM HTTP ${response.status}`);
 const data=await response.json();if(!data.choices?.[0]?.message)throw new Error('LLM вернула пустой ответ');return data.choices[0].message;
}
export async function agent(messages,tools,execute,done=()=>false){
 for(let step=0;step<12;step++){
  const reply=await completion(messages,tools);messages.push(reply);
  if(!reply.tool_calls?.length)return reply.content||'Нет текстового ответа.';
  for(const item of reply.tool_calls){let result;try{result=await execute(item.function.name,JSON.parse(item.function.arguments));}catch(e){result={error:e.message};}
   messages.push({role:'tool',tool_call_id:item.id,content:JSON.stringify(result)});
   if(done()){messages.push({role:'assistant',content:'Данные получены.'});return 'Данные получены.';}
  }
 }
 throw new Error('Достигнут лимит шагов агента. Повторите запрос точнее.');
}
export function fn(name,description,properties={},required=[]){return {type:'function',function:{name,description,parameters:{type:'object',properties,required,additionalProperties:false}}};}
