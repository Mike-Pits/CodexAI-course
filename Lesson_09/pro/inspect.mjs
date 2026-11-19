import {connect} from '../lite/lib.mjs';
const c=await connect('excel');try{const {tools}=await c.listTools();console.log(JSON.stringify(tools.filter(t=>['create_workbook','read_range','write_range','set_sheet_layout','format_range'].includes(t.name)),null,2));}finally{await c.close();}
