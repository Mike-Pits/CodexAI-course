"use strict";

const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;

const elements = {
  connectionBadge: document.querySelector("#connectionBadge"),
  connectionText: document.querySelector("#connectionText"),
  transcript: document.querySelector("#transcript"),
  emptyState: document.querySelector("#emptyState"),
  messageTemplate: document.querySelector("#messageTemplate"),
  statusVisual: document.querySelector("#statusVisual"),
  statusTitle: document.querySelector("#statusTitle"),
  statusDescription: document.querySelector("#statusDescription"),
  startSessionButton: document.querySelector("#startSessionButton"),
  endSessionButton: document.querySelector("#endSessionButton"),
  micButton: document.querySelector("#micButton"),
  micButtonText: document.querySelector("#micButtonText"),
  textForm: document.querySelector("#textForm"),
  textInput: document.querySelector("#textInput"),
  sendButton: document.querySelector("#sendButton"),
  clearButton: document.querySelector("#clearButton"),
  errorActions: document.querySelector("#errorActions"),
  retryButton: document.querySelector("#retryButton"),
  newSessionButton: document.querySelector("#newSessionButton"),
  simulateErrorButton: document.querySelector("#simulateErrorButton"),
};

const states = {
  idle: ["Разговор не начат", "Запустите новую голосовую сессию. История начнётся с чистого состояния."],
  ready: ["Соединение установлено", "Нажмите «Говорить» и задайте вопрос о времени консультации."],
  listening: ["Слушаю пользователя", "Говорите. Помощник обработает реплику после небольшой паузы."],
  processing: ["Проверяю расписание", "Сначала помощник получает данные, затем формирует ответ."],
  speaking: ["Воспроизвожу ответ", "Текст появляется постепенно. Можно перебить помощника кнопкой «Говорить»."],
  ended: ["Разговор завершён", "Начните новую сессию, чтобы очистить контекст и задать другой вопрос."],
  error: ["Возникла ошибка", "Не удалось завершить проверку. Повторите запрос или начните новую сессию."],
};

let sessionActive = false;
let sessionVersion = 0;
let responseVersion = 0;
let recognition = null;
let isListening = false;
let timers = new Set();
let lastRequest = "";

function setState(state, description) {
  const [title, defaultDescription] = states[state];
  elements.statusVisual.dataset.state = state;
  elements.statusTitle.textContent = title;
  elements.statusDescription.textContent = description || defaultDescription;
  elements.errorActions.hidden = state !== "error";
  elements.micButtonText.textContent = state === "listening" ? "Слушаю…" : "Говорить";
}

function updateControls() {
  elements.connectionBadge.dataset.connected = String(sessionActive);
  elements.connectionText.textContent = sessionActive ? "Соединение установлено" : "Нет соединения";
  elements.startSessionButton.disabled = sessionActive;
  elements.endSessionButton.disabled = !sessionActive;
  elements.micButton.disabled = !sessionActive;
  elements.textInput.disabled = !sessionActive;
  elements.sendButton.disabled = !sessionActive;
  elements.clearButton.disabled = !sessionActive;
  elements.simulateErrorButton.disabled = !sessionActive;
}

function clearTimers() {
  timers.forEach((timer) => window.clearTimeout(timer));
  timers.clear();
}

function later(callback, delay) {
  const timer = window.setTimeout(() => {
    timers.delete(timer);
    callback();
  }, delay);
  timers.add(timer);
  return timer;
}

function cancelCurrentResponse({ announce = false } = {}) {
  responseVersion += 1;
  clearTimers();
  if ("speechSynthesis" in window) window.speechSynthesis.cancel();
  if (announce && sessionActive) addMessage("system", "Текущий ответ остановлен. Слушаю новую просьбу.");
}

function clearTranscript() {
  elements.transcript.replaceChildren(elements.emptyState);
  elements.emptyState.hidden = false;
}

function addMessage(role, text = "") {
  elements.emptyState.hidden = true;
  const fragment = elements.messageTemplate.content.cloneNode(true);
  const article = fragment.querySelector(".message");
  const meta = fragment.querySelector(".message-meta");
  const message = fragment.querySelector(".message-text");
  article.dataset.role = role;
  meta.textContent = role === "user" ? "Вы" : role === "assistant" ? "Помощник" : "";
  message.textContent = text;
  elements.transcript.append(fragment);
  elements.transcript.scrollTop = elements.transcript.scrollHeight;
  return elements.transcript.lastElementChild.querySelector(".message-text");
}

function beginSession() {
  cancelCurrentResponse();
  stopRecognition();
  sessionVersion += 1;
  sessionActive = true;
  lastRequest = "";
  clearTranscript();
  updateControls();
  setState("ready");
  elements.textInput.focus();
}

function endSession() {
  sessionVersion += 1;
  sessionActive = false;
  cancelCurrentResponse();
  stopRecognition();
  updateControls();
  setState("ended");
}

function ensureRecognition() {
  if (!SpeechRecognition) return null;
  if (recognition) return recognition;
  recognition = new SpeechRecognition();
  recognition.lang = "ru-RU";
  recognition.continuous = false;
  recognition.interimResults = true;

  recognition.addEventListener("result", (event) => {
    const text = Array.from(event.results).map((result) => result[0].transcript).join(" ").trim();
    elements.statusDescription.textContent = text ? `Распознано: «${text}»` : states.listening[1];
    if (event.results[event.results.length - 1].isFinal && text) processRequest(text);
  });

  recognition.addEventListener("end", () => {
    isListening = false;
    if (sessionActive && elements.statusVisual.dataset.state === "listening") setState("ready", "Речь не распознана. Попробуйте ещё раз или введите просьбу текстом.");
  });

  recognition.addEventListener("error", (event) => {
    isListening = false;
    const messages = {
      "not-allowed": "Доступ к микрофону запрещён. Разрешите его в браузере или используйте текстовое поле.",
      "no-speech": "Речь не распознана. Нажмите «Говорить» и повторите просьбу.",
      network: "Сервис распознавания речи недоступен. Используйте текстовое поле или повторите позже.",
    };
    showError(messages[event.error] || "Не удалось распознать речь. Повторите попытку.");
  });
  return recognition;
}

function startListening() {
  if (!sessionActive || isListening) return;
  if (elements.statusVisual.dataset.state === "speaking") cancelCurrentResponse({ announce: true });
  const service = ensureRecognition();
  if (!service) {
    showError("Этот браузер не поддерживает распознавание речи. Откройте приложение в Chrome или Edge либо используйте текстовое поле.");
    return;
  }
  try {
    isListening = true;
    setState("listening");
    service.start();
  } catch (error) {
    isListening = false;
    showError("Микрофон уже запускается. Подождите секунду и повторите попытку.");
  }
}

function stopRecognition() {
  if (recognition && isListening) {
    try { recognition.abort(); } catch (error) { /* Сессия уже остановлена браузером. */ }
  }
  isListening = false;
}

function parseRequest(rawText) {
  const text = rawText.toLowerCase().replace(/ё/g, "е");
  if (text.includes("послезавтра")) return { type: "no-data" };
  if (!text.includes("завтра")) return { type: "unknown-date" };
  const asksNineteen = /(^|\D)(19([:.]00)?|девятнадцат|сем(ь|и))($|\D)/.test(text);
  const asksEighteenThirty = /18[:.]?30|восемнадцат.*тридцат|половин/.test(text);
  if (asksNineteen && !asksEighteenThirty && !text.includes("после шест")) return { type: "busy" };
  return { type: "available" };
}

function scheduleAnswer(result) {
  switch (result.type) {
    case "available":
      return "Завтра в 18:30 свободно, а в 19:00 время занято. Вам подходит 18:30?";
    case "busy":
      return "Завтра в 19:00 время занято. В 18:30 свободно. Вам подходит 18:30?";
    case "no-data":
      return "На послезавтра в расписании нет данных. Я не могу подтвердить свободное время. Попробовать проверить другой день?";
    default:
      return "В учебном расписании есть данные только на завтра. Уточните, пожалуйста, хотите проверить завтра после шести?";
  }
}

function processRequest(text) {
  if (!sessionActive) return;
  stopRecognition();
  cancelCurrentResponse();
  const ownSession = sessionVersion;
  const ownResponse = responseVersion;
  lastRequest = text.trim();
  addMessage("user", lastRequest);
  addMessage("system", "Проверяю учебное расписание…");
  setState("processing");

  later(() => {
    if (!sessionActive || ownSession !== sessionVersion || ownResponse !== responseVersion) return;
    const result = parseRequest(lastRequest);
    streamAndSpeak(scheduleAnswer(result), ownSession, ownResponse);
  }, 650);
}

function streamAndSpeak(answer, ownSession, ownResponse) {
  setState("speaking");
  const target = addMessage("assistant", "");
  const words = answer.split(" ");
  words.forEach((word, index) => {
    later(() => {
      if (!sessionActive || ownSession !== sessionVersion || ownResponse !== responseVersion) return;
      target.textContent += `${index ? " " : ""}${word}`;
      elements.transcript.scrollTop = elements.transcript.scrollHeight;
      if (index === words.length - 1) speak(answer, ownSession, ownResponse);
    }, index * 55);
  });
}

function speak(text, ownSession, ownResponse) {
  if (!("speechSynthesis" in window)) {
    showError("Браузер показал текст, но не поддерживает синтез речи. Откройте приложение в Chrome или Edge.");
    return;
  }
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.lang = "ru-RU";
  utterance.rate = 1;
  utterance.onend = () => {
    if (sessionActive && ownSession === sessionVersion && ownResponse === responseVersion) setState("ready", "Ответ завершён. Можно задать следующий вопрос.");
  };
  utterance.onerror = () => {
    if (sessionActive && ownSession === sessionVersion && ownResponse === responseVersion) showError("Не удалось воспроизвести голосовой ответ. Текст ответа сохранён в диалоге.");
  };
  window.speechSynthesis.cancel();
  window.speechSynthesis.speak(utterance);
}

function showError(message) {
  cancelCurrentResponse();
  addMessage("system", message);
  setState("error", message);
}

function simulateError() {
  if (!sessionActive) return;
  cancelCurrentResponse();
  if (!lastRequest) lastRequest = "Можно завтра после шести?";
  addMessage("system", "Проверка расписания завершилась ошибкой. Свободное время не подтверждено.");
  setState("error", "Не удалось получить данные расписания. Повторите запрос или начните новую сессию.");
}

elements.startSessionButton.addEventListener("click", beginSession);
elements.endSessionButton.addEventListener("click", endSession);
elements.micButton.addEventListener("click", startListening);
elements.clearButton.addEventListener("click", () => {
  cancelCurrentResponse();
  clearTranscript();
  lastRequest = "";
  setState("ready");
});
elements.textForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const text = elements.textInput.value.trim();
  if (!text) return;
  elements.textInput.value = "";
  processRequest(text);
});
elements.retryButton.addEventListener("click", () => lastRequest ? processRequest(lastRequest) : setState("ready"));
elements.newSessionButton.addEventListener("click", beginSession);
elements.simulateErrorButton.addEventListener("click", simulateError);

updateControls();
setState("idle");
