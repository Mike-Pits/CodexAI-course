'use strict';
const $ = id => document.getElementById(id);
let current = null, dirty = false, timer, saving = null, resultDirty = false;
const states = {queued:'В очереди',running:'Выполняется',done:'Завершено',error:'Ошибка',interrupted:'Прервано'};
function node(tag, text, cls) { const e = document.createElement(tag); if(text !== undefined)e.textContent=text; if(cls)e.className=cls; return e; }
function notice(message) { $('notice').textContent=message; $('notice').hidden=!message; }
async function api(path, options={}) {
  const response=await fetch('/api'+path,{...options,headers:{'X-Meetings-Client':'local',...(options.body && !(options.body instanceof FormData)?{'Content-Type':'application/json'}:{}),...options.headers}});
  if(!response.ok){ let data;try{data=await response.json();}catch{data={detail:'Ошибка сервера. Проверьте запуск приложения.'};} throw Error(typeof data.detail==='string'?data.detail:'Проверьте заполнение полей и допустимые значения.'); }
  return response.json();
}
function action(button, fn) { button.addEventListener('click', async()=>{button.disabled=true;notice('');try{await fn();}catch(e){notice(e.message);}finally{button.disabled=false;if(button.id==='analyze'&&current)button.disabled=current.jobs.some(j=>['queued','running'].includes(j.state))||!!current.results.candidate;}}); }
function localDate() { const d=new Date();return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`; }
async function list() {
  const items=await api('/meetings'); $('meetings').replaceChildren();$('start').textContent=items.length?'Создать новую встречу →':'Создать первую встречу →';
  $('meeting-count').textContent=items.length;
  $('processed-count').textContent=items.filter(m=>m.has_result).length;
  $('active-count').textContent=items.filter(m=>['queued','running'].includes(m.job_state)).length;
  $('recent-meetings').replaceChildren();
  if(!items.length)$('recent-meetings').append(node('p','Добавьте первую видеозапись — готовый конспект появится здесь.','hint'));
  for(const m of items.slice(0,6)){
    const card=node('button',undefined,'meeting-card');
    card.append(node('span',m.source==='cloud'?'Из облака':'Загружено вручную','source-pill'),node('h3',m.title),node('small',`${m.meeting_date} · ${m.stage||'Черновик'}`),node('p',m.summary||'Результат появится после завершения обработки.'));
    action(card,()=>openMeeting(m.id));$('recent-meetings').append(card);
  }
  if(!items.length)$('meetings').append(node('p','Пока нет сохранённых встреч','hint'));
  for(const m of items){const b=node('button',undefined,current?.id===m.id?'active':'');b.append(node('strong',m.title),node('small',`${m.meeting_date} · ${['queued','running','error','interrupted'].includes(m.job_state)?m.stage:m.has_candidate?'Проверьте новый результат':m.has_result?'Результат сохранён':m.stage||'Черновик'}`));action(b,()=>openMeeting(m.id));$('meetings').append(b);}
}
async function openMeeting(id) {
  await flush();
  if(resultDirty && !confirm('Есть несохранённые правки результата. Перейти без сохранения?'))return;
  if(recorderState && !confirm('Запись будет удалена при переходе. Продолжить?'))return;
  cleanupRecording(); resultDirty=false; current=await api('/meetings/'+id);render(true);await list();
}
function render(fields=false) {
  if(!current)return;
  $('welcome').hidden=true;$('editor').hidden=false;$('heading').textContent=current.title;
  $('source-label').textContent=current.source==='cloud'?'Из облака':'Загружено вручную';
  if(fields){$('title').value=current.title;$('date').value=current.meeting_date;$('text').value=current.text;$('saved').textContent='Сохранено';dirty=false;}
  $('count').textContent=$('text').value.length.toLocaleString('ru')+' / 200 000';
  const busy=current.jobs.some(j=>['queued','running'].includes(j.state));
  $('analyze').disabled=busy||!!current.results.candidate;
  $('jobs').replaceChildren();
  for(const job of current.jobs.slice(0,4)){
    const box=node('div',undefined,'job'+(['error','interrupted'].includes(job.state)?' error':''));
    const jobName=job.kind==='analysis'?'AI-анализ':job.kind==='pipeline'?'Автоматический анализ':'Расшифровка';
    box.append(node('strong',`${jobName} · ${states[job.state]}`),node('div',job.error||job.stage));
    if(['error','interrupted'].includes(job.state)){const retry=node('button','Повторить с текущими материалами');action(retry,async()=>{await flush();current=await api(`/meetings/${current.id}/jobs/${job.id}/retry`,{method:'POST'});render();});box.append(retry);}
    $('jobs').append(box);
  }
  renderMedia();
  renderAudio(busy);
  if(!resultDirty)renderResults();
}
function renderMedia() {
  const files=current.files.filter(f=>f.kind==='video');
  $('media-list').replaceChildren();
  for(const f of files){const box=node('div',undefined,'media-item');box.append(node('strong',f.name),node('span',` ${Math.round(f.duration)} сек. · ${current.source==='cloud'?'из облака':'ручная загрузка'}`,'hint'));const player=node('video');player.controls=true;player.preload='metadata';player.src=`/api/meetings/${current.id}/files/${f.id}`;box.append(player);$('media-list').append(box);}
}
function renderAudio(busy) {
  const files=current.files.filter(f=>f.kind==='audio');
  const signature=JSON.stringify(files.map(f=>f.id));
  if($('audio-list').dataset.signature!==signature){
    $('audio-list').dataset.signature=signature;$('audio-list').replaceChildren();
    for(const f of files){const box=node('div',undefined,'audio-item');box.append(node('strong',f.name));const player=node('audio');player.controls=true;player.preload='metadata';player.src=`/api/meetings/${current.id}/files/${f.id}`;box.append(player);
      const speed=node('select');speed.setAttribute('aria-label','Скорость воспроизведения');for(const rate of [.75,1,1.25,1.5,2]){const o=node('option',rate+'×');o.value=rate;o.selected=rate===1;speed.append(o);}speed.onchange=()=>player.playbackRate=Number(speed.value);box.append(speed);
      const b=node('button','Расшифровать');b.dataset.transcribe='true';action(b,async()=>{await flush();if(current.text && !confirm('После расшифровки текущий текст будет заменён. Продолжить?'))return;current=await api(`/meetings/${current.id}/jobs?kind=transcription&file_id=${f.id}`,{method:'POST'});render();});box.append(b);$('audio-list').append(box);
    }
  }
  $('audio-list').querySelectorAll('[data-transcribe]').forEach(b=>b.disabled=busy);
}
function field(label, value, onChange, type='text') { const wrapper=node('label',label), input=node(type==='textarea'?'textarea':'input');if(type!=='textarea')input.type=type;else input.rows=3;input.value=value||'';input.oninput=()=>{resultDirty=true;onChange(input.value);};wrapper.append(input);return wrapper; }
function check(label, checked, onChange) { const wrapper=node('label',undefined,'check'), input=node('input');input.type='checkbox';input.checked=checked;input.onchange=()=>{resultDirty=true;onChange(input.checked);};wrapper.append(input,node('span',label));return wrapper; }
function renderResults() {
  $('results').replaceChildren();
  for(const kind of ['candidate','current']){
    const record=current.results[kind];if(!record)continue;
    const result=structuredClone(record.payload), section=node('section',undefined,`panel result ${kind}`);
    section.append(node('h2',kind==='candidate'?'Новый результат — проверьте перед сохранением':'Сохранённый результат'));
    if(record.stale)section.append(node('p','Текст или дата встречи изменились. Этот результат основан на предыдущей редакции.','warning'));
    if(record.manual)section.append(node('p','Результат исправлен пользователем. Цитаты относятся к исходному материалу.','hint'));
    section.append(field('Резюме',result.summary,v=>result.summary=v,'textarea'));
    for(const [key,label] of [['participants','Участники'],['topics','Обсуждённые темы'],['open_questions','Открытые вопросы']])section.append(field(label+' — по одному на строке',result[key].join('\n'),v=>result[key]=v.split('\n').map(x=>x.trim()).filter(Boolean),'textarea'));
    section.append(node('h3','Решения'));
    if(!result.decisions.length)section.append(node('p','Решения не зафиксированы','hint'));
    for(const d of result.decisions){const box=node('div',undefined,'result-item');box.append(field('Решение',d.text,v=>d.text=v,'textarea'),field('Цитата из исходного текста',d.quote,v=>d.quote=v,'textarea'));const remove=node('button','Убрать решение');remove.onclick=()=>{result.decisions.splice(result.decisions.indexOf(d),1);record.payload=result;resultDirty=true;renderResults();};box.append(remove);section.append(box);}
    const addDecision=node('button','Добавить решение');addDecision.onclick=()=>{result.decisions.push({text:'',quote:''});record.payload=result;resultDirty=true;renderResults();};section.append(addDecision);
    section.append(node('h3','Поручения'));
    if(!result.tasks.length)section.append(node('p','Поручения не зафиксированы','hint'));
    for(const t of result.tasks){const box=node('div',undefined,'result-item');box.append(field('Что сделать',t.text,v=>t.text=v,'textarea'),field('Цитата из исходного текста',t.quote,v=>t.quote=v,'textarea'));const grid=node('div',undefined,'task-fields');
      const owner=field('Ответственный',t.owner,v=>{t.owner=v.trim()||null;t.owner_confirmed=!!t.owner;});owner.append(check('Не указано',t.owner_confirmed&&!t.owner,v=>{t.owner_confirmed=v;t.owner=null;owner.querySelector('input').value='';}));owner.querySelector('input').addEventListener('input',()=>owner.querySelector('input[type=checkbox]').checked=false);grid.append(owner);
      const due=field('Срок',t.due_date,v=>{t.due_date=v||null;t.due_confirmed=!!v;},'date');if(t.due_raw)due.append(node('small','В записи: '+t.due_raw));due.append(check('Не указано',t.due_confirmed&&!t.due_date,v=>{t.due_confirmed=v;t.due_date=null;due.querySelector('input').value='';}));due.querySelector('input').addEventListener('input',()=>due.querySelector('input[type=checkbox]').checked=false);grid.append(due);
      const status=node('label','Статус'), select=node('select');for(const text of ['Не начато','В работе','Выполнено']){const opt=node('option',text);opt.selected=t.status===text;select.append(opt);}select.disabled=kind==='candidate';select.onchange=()=>{t.status=select.value;resultDirty=true;};status.append(select);grid.append(status);box.append(grid);
      if(!t.owner_confirmed||!t.due_confirmed)box.append(node('p','Уточните ответственного и срок или отметьте «Не указано».','warning'));
      const remove=node('button','Убрать поручение');remove.onclick=()=>{result.tasks.splice(result.tasks.indexOf(t),1);record.payload=result;resultDirty=true;renderResults();};box.append(remove);
      section.append(box);
    }
    const addTask=node('button','Добавить поручение');addTask.onclick=()=>{result.tasks.push({text:'',quote:'',owner:null,due_raw:null,due_date:null,status:'Не начато',owner_confirmed:false,due_confirmed:false,manual:true});record.payload=result;resultDirty=true;renderResults();};section.append(addTask);
    const controls=node('div',undefined,'row wrap');
    const save=node('button',kind==='candidate'?'Сохранить уточнения':'Сохранить правки');action(save,async()=>{current=await api(`/meetings/${current.id}/results/${kind}`,{method:'PUT',body:JSON.stringify({result,version:record.version})});resultDirty=false;render();});controls.append(save);
    if(kind==='candidate'){
      const accept=node('button',current.results.current?'Заменить текущий результат':'Подтвердить результат','primary');action(accept,async()=>{
        if(current.results.current&&!confirm('Новый результат полностью заменит прежний. Ручные правки будут потеряны, статусы поручений сбросятся на «Не начато». Продолжить?'))return;
        current=await api(`/meetings/${current.id}/results/candidate`,{method:'PUT',body:JSON.stringify({result,version:record.version})});
        const version=current.results.candidate.version;resultDirty=false;render();
        current=await api(`/meetings/${current.id}/accept?version=${version}`,{method:'POST'});render();await list();
      });controls.append(accept);
      const reject=node('button','Отклонить');action(reject,async()=>{if(!confirm('Удалить новый результат? Сохранённый результат останется.'))return;current=await api(`/meetings/${current.id}/candidate`,{method:'DELETE'});resultDirty=false;render();});controls.append(reject);
    }else{
      for(const [format,label] of [['md','Скачать Markdown'],['docx','Скачать DOCX']]){const link=node('a',label,'button');link.href=`/api/meetings/${current.id}/export/${format}`;link.addEventListener('click',e=>{if(resultDirty){e.preventDefault();notice('Сначала сохраните правки результата.');}});controls.append(link);}
      const copy=node('button','Копировать');action(copy,async()=>{if(resultDirty)throw Error('Сначала сохраните правки результата.');const response=await fetch(`/api/meetings/${current.id}/export/md`);if(!response.ok)throw Error('Не удалось скопировать результат.');await navigator.clipboard.writeText(await response.text());copy.textContent='Скопировано';});controls.append(copy);
    }
    section.append(controls);
    if(kind==='current'&&current.results.candidate){section.querySelectorAll('input,textarea,select,button').forEach(e=>e.disabled=true);section.append(node('p','Для редактирования текущего результата сначала примите или отклоните новый.','hint'));}
    $('results').append(section);
  }
}
async function flush() {
  clearTimeout(timer);if(saving)await saving;if(!dirty||!current)return;
  const id=current.id, values={title:$('title').value,meeting_date:$('date').value,text:$('text').value,version:current.version};
  $('saved').textContent='Сохраняется…';
  saving=(async()=>{
    try { const updated=await api('/meetings/'+id,{method:'PUT',body:JSON.stringify(values)});current=updated;
      dirty=values.title!==$('title').value||values.meeting_date!==$('date').value||values.text!==$('text').value;
      $('saved').textContent=dirty?'Есть изменения':'Сохранено';$('heading').textContent=current.title;
    }catch(e){$('saved').textContent='Ошибка сохранения';throw e;}
    finally{saving=null;}
  })();
  await saving;if(dirty)await flush();
}
for(const id of ['title','date','text'])$(id).addEventListener('input',()=>{dirty=true;$('saved').textContent='Есть изменения';$('count').textContent=$('text').value.length.toLocaleString('ru')+' / 200 000';clearTimeout(timer);timer=setTimeout(()=>flush().catch(e=>notice(e.message)),1000);});
function showNew(){ if(recorderState){notice('Сначала сохраните или удалите текущую запись.');return;} $('new-form').elements.date.value=localDate();$('new-dialog').showModal(); }
$('new').onclick=showNew;$('start').onclick=showNew;$('cancel-new').onclick=()=>$('new-dialog').close();
$('video-upload').onchange=async e=>{const file=e.target.files[0];if(!file)return;const label=e.target.closest('.dropzone');label.classList.add('loading');notice('');try{const form=new FormData();form.append('file',file);current=await api('/recordings',{method:'POST',body:form});resultDirty=false;render(true);await list();}catch(err){notice(err.message);}finally{label.classList.remove('loading');e.target.value='';}};
$('cloud-form').onsubmit=async e=>{e.preventDefault();const button=e.target.querySelector('button');button.disabled=true;notice('');try{current=await api('/recordings/cloud',{method:'POST',body:JSON.stringify({url:$('cloud-url').value})});resultDirty=false;render(true);await list();notice(current.duplicate?'Эта запись уже добавлена. Открыт сохранённый результат.':'Файл получен. Анализ запущен автоматически.');$('cloud-url').value='';}catch(err){notice(err.message+' Если ссылка требует входа, скачайте видео и загрузите его вручную.');}finally{button.disabled=false;}};
document.querySelector('.brand').style.cursor='pointer';document.querySelector('.brand').onclick=async()=>{await flush();if(resultDirty&&!confirm('Перейти без сохранения правок результата?'))return;current=null;resultDirty=false;$('editor').hidden=true;$('welcome').hidden=false;await list();};
$('new-form').onsubmit=async e=>{e.preventDefault();try{await flush();if(resultDirty && !confirm('Перейти без сохранения правок результата?'))return;const f=e.target;const created=await api('/meetings',{method:'POST',body:JSON.stringify({title:f.elements.title.value,meeting_date:f.elements.date.value})});resultDirty=false;current=created;render(true);await list();$('new-dialog').close();f.reset();}catch(err){notice(err.message);}};
action($('analyze'),async()=>{await flush();current=await api(`/meetings/${current.id}/jobs?kind=analysis`,{method:'POST'});render();});
for(const id of ['document','audio-file'])$(id).onchange=async e=>{const file=e.target.files[0];if(!file)return;try{await flush();if(id==='document'&&current.text&&!confirm('Импорт заменит текущий текст. Продолжить?'))return;const form=new FormData();form.append('file',file);current=await api(`/meetings/${current.id}/files`,{method:'POST',body:form});render(true);notice('');}catch(err){notice(err.message);}finally{e.target.value='';}};
action($('delete'),async()=>{if(!confirm('Удалить встречу, исходники, аудио и результаты? Скачанные копии останутся вне приложения.'))return;clearTimeout(timer);if(saving)await saving;await api('/meetings/'+current.id,{method:'DELETE'});cleanupRecording();current=null;dirty=false;resultDirty=false;$('editor').hidden=true;$('welcome').hidden=false;await list();});
let recorderState=null;
function cleanupRecording(){if(!recorderState)return;const state=recorderState;recorderState=null;clearInterval(state.timer);if(state.recorder?.state!=='inactive')state.recorder?.stop();state.streams.forEach(s=>s.getTracks().forEach(t=>t.stop()));state.context?.close();if(state.url)URL.revokeObjectURL(state.url);$('recorder').hidden=true;}
action($('record'),async()=>{
  if(recorderState)throw Error('Сначала сохраните или удалите текущую запись.');
  const streams=[];let context;
  try{
    const screen=await navigator.mediaDevices.getDisplayMedia({video:true,audio:true,systemAudio:'include'});streams.push(screen);
    if(!screen.getAudioTracks().length)throw Error('Браузер не предоставил звук настольного приложения. Загрузите готовую запись встречи.');
    const mic=await navigator.mediaDevices.getUserMedia({audio:true});streams.push(mic);context=new AudioContext();const destination=context.createMediaStreamDestination();
    for(const stream of streams)context.createMediaStreamSource(new MediaStream(stream.getAudioTracks())).connect(destination);
    const recorder=new MediaRecorder(destination.stream,{mimeType:'audio/webm;codecs=opus'});const state={recorder,streams,context,chunks:[],bytes:0,elapsed:0};recorderState=state;
    recorder.ondataavailable=e=>{if(e.data.size){state.chunks.push(e.data);state.bytes+=e.data.size;if(state.bytes>=499_000_000&&recorder.state!=='inactive')recorder.stop();}};
    recorder.onstop=()=>{clearInterval(state.timer);streams.forEach(s=>s.getTracks().forEach(t=>t.stop()));if(recorderState!==state)return;state.blob=new Blob(state.chunks,{type:'audio/webm'});state.url=URL.createObjectURL(state.blob);$('record-preview').src=state.url;$('record-preview').hidden=false;$('save-record').hidden=false;$('pause').hidden=true;$('stop').hidden=true;$('record-state').textContent='Запись остановлена. Прослушайте обе стороны перед сохранением.';};
    screen.getVideoTracks()[0].onended=()=>{if(recorder.state!=='inactive')recorder.stop();};
    recorder.start(1000);$('recorder').hidden=false;$('record-preview').hidden=true;$('save-record').hidden=true;$('pause').hidden=false;$('stop').hidden=false;$('pause').textContent='Пауза';
    state.timer=setInterval(()=>{if(recorder.state==='recording')state.elapsed++;$('record-state').textContent=`${recorder.state==='paused'?'Пауза':'Запись микрофона и предоставленного источника'} · ${Math.floor(state.elapsed/60)}:${String(state.elapsed%60).padStart(2,'0')}`;if(state.elapsed>=7200&&recorder.state!=='inactive')recorder.stop();},1000);
  }catch(e){
    if(recorderState)cleanupRecording();else{streams.forEach(s=>s.getTracks().forEach(t=>t.stop()));context?.close();}
    if(e.name==='NotAllowedError')throw Error('Доступ к записи не предоставлен или выбор источника отменён. Разрешите доступ в браузере либо загрузите готовое аудио.');
    if(e.name==='NotFoundError')throw Error('Микрофон или источник звука не найден. Подключите устройство либо загрузите готовое аудио.');
    if(e.name==='NotSupportedError'||e.name==='TypeError')throw Error('Браузер не поддерживает этот способ записи. Используйте Chrome/Chromium или загрузите готовое аудио.');
    throw e;
  }
});
$('pause').onclick=()=>{const r=recorderState.recorder;if(r.state==='recording'){r.pause();$('pause').textContent='Продолжить';}else{r.resume();$('pause').textContent='Пауза';}};
$('stop').onclick=()=>recorderState?.recorder.stop();$('discard-record').onclick=()=>{if(confirm('Удалить несохранённую запись?'))cleanupRecording();};
action($('save-record'),async()=>{const form=new FormData();form.append('file',recorderState.blob,'Запись.webm');current=await api(`/meetings/${current.id}/files?recording=true`,{method:'POST',body:form});cleanupRecording();render();});
window.addEventListener('beforeunload',e=>{if(dirty||resultDirty||recorderState){e.preventDefault();e.returnValue='';}});
setInterval(async()=>{if(!current||dirty||saving||resultDirty)return;try{const id=current.id;const updated=await api('/meetings/'+id);if(!current||current.id!==id||dirty||saving||resultDirty)return;const changed=JSON.stringify(updated)!==JSON.stringify(current);if(changed){const textChanged=updated.version!==current.version;current=updated;render(textChanged);await list();}}catch(e){notice(e.message);}},2000);
list().catch(e=>notice(e.message));
