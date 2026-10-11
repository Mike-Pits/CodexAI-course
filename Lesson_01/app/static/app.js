'use strict';
const form = document.querySelector('#chat-form');
const input = document.querySelector('#message');
const messages = document.querySelector('#messages');
const status = document.querySelector('#status');
const send = document.querySelector('#send');
const clear = document.querySelector('#clear');
const counter = document.querySelector('#counter');
const suggestions = [...document.querySelectorAll('.suggestions button')];
const welcome = messages.firstElementChild.cloneNode(true);
let modeReady = false;
let history = [];
let controller = null;
let generation = 0;

function addMessage(role, text) {
  const article = document.createElement('article');
  article.className = `message ${role}`;
  const label = document.createElement('span');
  label.className = 'message-label';
  label.textContent = role === 'user' ? 'ВЫ' : 'ТОЧКА ОПОРЫ';
  const paragraph = document.createElement('p');
  paragraph.textContent = text; // Never interpret model/user output as HTML.
  article.append(label, paragraph);
  messages.append(article);
  messages.scrollTop = messages.scrollHeight;
  return article;
}
function busy(value) {
  send.disabled = value || !modeReady;
  input.disabled = value;
  suggestions.forEach(button => { button.disabled = value || !modeReady; });
  form.setAttribute('aria-busy', String(value));
}
function count() { counter.textContent = `${input.value.length} / 1500`; }
input.addEventListener('input', count);
input.addEventListener('keydown', event => {
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    if (!controller) form.requestSubmit();
  }
});
suggestions.forEach(button => button.addEventListener('click', () => {
  input.value = button.textContent;
  count();
  form.requestSubmit();
}));
clear.addEventListener('click', () => {
  generation += 1;
  controller?.abort();
  controller = null;
  history = [];
  messages.replaceChildren(welcome.cloneNode(true));
  input.value = '';
  count();
  status.textContent = '';
  status.className = 'status';
  busy(false);
  input.focus();
});
form.addEventListener('submit', async event => {
  event.preventDefault();
  const text = input.value.trim();
  if (!text || controller || !modeReady) return;
  const current = generation;
  const requestController = new AbortController();
  controller = requestController;
  const timeout = setTimeout(() => requestController.abort(), 45000);
  const bubble = addMessage('user', text);
  input.value = '';
  count();
  busy(true);
  status.className = 'status';
  status.textContent = 'Готовлю ответ…';
  try {
    const response = await fetch('/api/chat', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({message: text, history}), signal: requestController.signal
    });
    const data = await response.json();
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Не удалось отправить сообщение.');
    if (current !== generation) return;
    if (typeof data.reply !== 'string') throw new Error('Не удалось прочитать ответ.');
    addMessage('assistant', data.reply);
    history.push({role: 'user', content: text}, {role: 'assistant', content: data.reply.slice(0, 4000)});
    history = history.slice(-8);
    while (history.reduce((sum, item) => sum + item.content.length, 0) > 12000) history.splice(0, 2);
    status.textContent = '';
  } catch (error) {
    if (current !== generation) return;
    bubble.remove();
    input.value = text;
    count();
    status.className = 'status error';
    status.textContent = error.name === 'AbortError' ? 'Ответ задерживается. Попробуйте ещё раз.' :
      error instanceof TypeError ? 'Нет связи с сервером. Проверьте подключение.' : error.message;
  } finally {
    clearTimeout(timeout);
    if (current === generation) {
      controller = null;
      busy(false);
      input.focus();
    }
  }
});

// Determine mode from the server before allowing the first message.
busy(true);
fetch('/api/health').then(async response => {
  if (!response.ok) throw new Error('Mode unavailable');
  const config = await response.json();
  const mock = config.mode === 'mock';
  document.querySelector('#mode-notice').textContent = mock
    ? 'Тестовый режим · готовые ответы · без OpenAI и расходов API'
    : 'Режим LLM · ответы генерирует подключённая модель';
  document.querySelector('#privacy').textContent = mock
    ? 'Сообщения обрабатываются только этим приложением и не отправляются в OpenAI. Не вводите чувствительные сведения. История исчезнет при обновлении страницы.'
    : 'Не указывайте личные и чувствительные сведения. Сообщения передаются настроенному провайдеру LLM. История исчезнет при обновлении страницы.';
  if (mock) {
    welcome.querySelector('p').textContent = 'Здравствуйте! Сейчас включены готовые тестовые ответы без OpenAI. Можно спросить об услугах, ценах, расписании и порядке обращения. Свободный диалог и понимание истории в этом режиме не поддерживаются.';
    messages.replaceChildren(welcome.cloneNode(true));
  }
  modeReady = true;
  busy(false);
}).catch(() => {
  document.querySelector('#mode-notice').textContent = 'Не удалось проверить режим чата. Обновите страницу.';
  busy(false);
});
