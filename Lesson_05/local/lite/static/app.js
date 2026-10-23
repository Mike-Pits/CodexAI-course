const form = document.querySelector("#question-form");
const input = document.querySelector("#question");
const chat = document.querySelector("#chat");
const health = document.querySelector("#health");
const submit = form.querySelector("button");

function message(role, text, sources = []) {
  const article = document.createElement("article");
  article.className = `message ${role}`;
  const avatar = document.createElement("div");
  avatar.className = "avatar";
  avatar.textContent = role === "user" ? "ВЫ" : "СУБ";
  const bubble = document.createElement("div");
  const body = document.createElement("p");
  body.textContent = text;
  bubble.append(body);
  if (sources.length) {
    const list = document.createElement("ul");
    list.className = "sources";
    for (const source of sources) {
      const item = document.createElement("li");
      item.innerHTML = `<strong>${escapeHtml(source.source)}</strong> — ${escapeHtml(source.section)} (сходство ${source.score})`;
      list.append(item);
    }
    bubble.append(list);
  }
  article.append(avatar, bubble);
  chat.append(article);
  article.scrollIntoView({ behavior: "smooth", block: "end" });
}

function escapeHtml(value) {
  const node = document.createElement("span");
  node.textContent = value;
  return node.innerHTML;
}

async function refreshHealth() {
  try {
    const response = await fetch("/api/health");
    const data = await response.json();
    if (data.status === "ready") {
      health.textContent = `Готово: ${data.documents} документов · ${data.embedding_model}`;
      health.className = "status ready";
    } else {
      health.textContent = "Нужны API-ключ и построенный индекс";
      health.className = "status warn";
    }
  } catch {
    health.textContent = "Backend недоступен";
    health.className = "status warn";
  }
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const question = input.value.trim();
  if (!question) return;
  message("user", question);
  input.value = "";
  submit.disabled = true;
  submit.textContent = "Ищем…";
  try {
    const response = await fetch("/api/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "Неизвестная ошибка");
    message("assistant", data.text, data.sources);
  } catch (error) {
    message("assistant", `Ошибка: ${error.message}`);
  } finally {
    submit.disabled = false;
    submit.textContent = "Отправить";
    input.focus();
  }
});

refreshHealth();

