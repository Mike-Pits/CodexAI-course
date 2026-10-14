const $ = id => document.getElementById(id);
let currentUser = null;
let config = null;
let history = [];

function notice(message, bad=false){
  const n=$('notice'); n.textContent=message; n.style.background=bad?'#8a2c2c':''; n.hidden=false;
  clearTimeout(notice.timer); notice.timer=setTimeout(()=>n.hidden=true,3500);
}
async function api(path, options={}){
  const response=await fetch(path,{...options,headers:{'Content-Type':'application/json',...(options.headers||{})}});
  const value=await response.json();
  if(!response.ok) throw Error(value.error||'Ошибка запроса');
  return value;
}
function profileValues(){
  return {goal:$('goal').value,budget:$('budget').value,format:$('format').value,pace:$('pace').value,experience:$('experience').value};
}
function fillProfile(profile={}){
  for(const key of ['goal','budget','format','pace','experience']) $(key).value=profile[key]||'';
}
function renderChat(){
  const chat=$('chat'); chat.replaceChildren();
  if(!history.length){const welcome=document.createElement('div');welcome.className='welcome';welcome.innerHTML='<span>П</span><p>Расскажите о задаче или спросите, какой тариф подойдёт. Я учту сохранённые предпочтения.</p>';chat.append(welcome);return;}
  for(const item of history){const bubble=document.createElement('div');bubble.className='bubble '+item.role;const small=document.createElement('small');small.textContent=item.role==='user'?'Вы':'Куратор';bubble.append(small,document.createTextNode(item.content));chat.append(bubble);}
  chat.scrollTop=chat.scrollHeight;
}
function showView(user){
  currentUser=user;
  $('login-view').hidden=!!user;$('client-view').hidden=!user||user.role!=='client';$('admin-view').hidden=!user||user.role!=='admin';$('session-actions').hidden=!user;
  if(!user)return;
  $('identity').textContent=`${user.profile.name||user.username} · ${user.role==='admin'?'администратор':'клиент'}`;
  if(user.role==='client'){$('client-name').textContent=user.profile.name||user.username;fillProfile(user.profile);$('model-badge').textContent=config.model;history=[];renderChat();}
  else loadUsers();
}
async function loadUsers(){
  try{const {users}=await api('/api/users');const root=$('users');root.replaceChildren();for(const user of users){
    const card=document.createElement('article');card.className='panel user-card';
    const role=user.role==='admin'?'администратор':'клиент';card.innerHTML=`<p class="kicker">${role.toUpperCase()}</p><h2></h2><p class="user-meta"></p>`;card.querySelector('h2').textContent=user.profile.name||user.username;card.querySelector('.user-meta').textContent=`@${user.username} · обновлено ${user.updated_at||'—'}`;
    const form=document.createElement('form');form.dataset.id=user.id;
    for(const [key,label] of Object.entries({goal:'Цель',budget:'Бюджет',format:'Формат',pace:'Темп',experience:'Опыт'})){const l=document.createElement('label');l.textContent=label;const input=document.createElement('input');input.name=key;input.value=user.profile[key]||'';l.append(input);form.append(l);}
    const button=document.createElement('button');button.textContent='Сохранить изменения';form.append(button);form.onsubmit=saveAdmin;card.append(form);root.append(card);
  }}catch(e){notice(e.message,true)}
}
async function saveAdmin(event){event.preventDefault();const form=event.currentTarget;const profile=Object.fromEntries(new FormData(form));try{await api('/api/users/'+encodeURIComponent(form.dataset.id),{method:'PUT',body:JSON.stringify({profile})});notice('Данные пользователя сохранены');await loadUsers();}catch(e){notice(e.message,true)}}
$('login-form').onsubmit=async event=>{event.preventDefault();try{const {user}=await api('/api/login',{method:'POST',body:JSON.stringify({username:$('username').value,password:$('password').value})});showView(user);}catch(e){notice(e.message,true)}};
$('logout').onclick=async()=>{try{await api('/api/logout',{method:'POST',body:'{}'})}finally{showView(null)}};
$('profile-form').onsubmit=async event=>{event.preventDefault();try{const {user}=await api('/api/profile',{method:'PUT',body:JSON.stringify({profile:profileValues()})});currentUser=user;fillProfile(user.profile);notice('Долгосрочная память обновлена');}catch(e){notice(e.message,true)}};
$('chat-form').onsubmit=async event=>{event.preventDefault();const message=$('message').value.trim();if(!message)return;const button=event.submitter;button.disabled=true;history.push({role:'user',content:message});$('message').value='';renderChat();try{const result=await api('/api/chat',{method:'POST',body:JSON.stringify({message})});history=result.history;fillProfile(result.profile);renderChat();if(Object.keys(result.saved).length)notice('Новые сведения сохранены: '+Object.keys(result.saved).join(', '));}catch(e){history.pop();renderChat();notice(e.message,true)}finally{button.disabled=false}};
$('new-dialog').onclick=async()=>{try{await api('/api/new-dialog',{method:'POST',body:'{}'});history=[];renderChat();notice('Текущий контекст очищен, профиль сохранён');}catch(e){notice(e.message,true)}};
for(const button of document.querySelectorAll('.suggestions button'))button.onclick=()=>{$('message').value=button.textContent;$('message').focus()};
Promise.all([api('/api/config'),api('/api/me')]).then(([c,session])=>{config=c;showView(session.user)}).catch(e=>notice(e.message,true));
