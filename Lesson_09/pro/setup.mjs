import {format} from './format.mjs';
import {mkdir,writeFile} from 'node:fs/promises';
import {excel,invoke,initial,directory,read,sheet} from './excel.mjs';
await mkdir(directory,{recursive:true});const c=await excel(),trace=[];try{
 await invoke(c,'create_workbook',{sheets:[sheet]},trace);
 await invoke(c,'write_range',{sheet,at:'A1',rows:initial},trace);
 await format(c,trace);
 console.log(JSON.stringify(await read(c,trace)));
 await writeFile('evidence/setup.json',JSON.stringify(trace,null,2));
}finally{await c.close();}
