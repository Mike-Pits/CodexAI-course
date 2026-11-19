import {writeFile} from 'node:fs/promises';
import {excel,invoke,read,sheet} from './excel.mjs';
export async function format(c,trace){
 await invoke(c,'format_range',{sheet,range:'A1:D100',style:{font_name:'Calibri',font_size:12,vertical_alignment:'center',wrap_text:true}},trace);
 await invoke(c,'format_range',{sheet,range:'A1:D1',style:{bold:true,fill_color:'#254DDB',font_color:'#FFFFFF'}},trace);
 await invoke(c,'set_sheet_layout',{sheet,layout:{column_widths_chars:{A:10,B:28,C:48,D:18},row_heights_pt:{1:30,2:34,3:34,4:34,5:34},freeze_panes:'A2',print_setup:{orientation:'landscape',paper_size:'a4',fit_to_pages:{wide:1,tall:0},title_rows:'1:1'}}},trace);
}
if(process.argv[1]?.endsWith('format.mjs')){const c=await excel(),trace=[];try{await format(c,trace);console.log(await read(c,trace));await writeFile('evidence/format.json',JSON.stringify(trace,null,2));}finally{await c.close();}}
