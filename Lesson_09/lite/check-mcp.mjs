import {connect,call} from './lib.mjs';
const c=await connect('weather');try{const list=await c.listTools();console.log(JSON.stringify(list,null,2));if(process.argv[2])await call(c,process.argv[2],JSON.parse(process.argv[3]||'{}'),[]);}finally{await c.close();}
