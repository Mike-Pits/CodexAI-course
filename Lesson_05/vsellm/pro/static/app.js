const form = document.querySelector("#question-form");
const input = document.querySelector("#question");
const chat = document.querySelector("#chat");
const health = document.querySelector("#health");
const submit = form.querySelector("button");
const reindex = document.querySelector("#reindex");

function escapeHtml(value) {
  const node = document.createElement("span");
  node.textContent = value;
  return node.innerHTML;
}

function diagnosticsBlock(diagnostics) {
  const details = document.createElement("details");
  details.className = "diagnostics";
  const summary = document.createElement("summary");
  summary.textContent = "Диагностика гибридного поиска";
  details.append(summary);
  const labels = { vector: "Векторный поиск", bm25: "BM25", final: "Итоговый контекст RRF" };
  for (const [key, label] of Object.entries(labels)) {
    const section = document.createElement("section");
    section.className = "channel";
    section.innerHTML = `<h4>${label}</h4>`;
    for (const hit of diagnostics[key] || []) {
      const row = document.createElement("div");
      row.className = "hit";
      row.innerHTML = `<b>#${hit.rank} · ${escapeHtml(hit.section)}</b> · score ${hit.score}<br>${escapeHtml(hit.preview)}`;
      section.append(row);
    }
    details.append(section);
  }
  return details;
}

function message(role, text, sources = [], diagnostics = null) {
  const article = document.createElement("article");
  article.className = `message ${role}`;
  const avatar = document.createElement("div");
  avatar.className = "avatar";
  avatar.textContent = role === "user" ? "ВЫ" : "PRO";
  const bubble = document.createElement("div");
  const body = document.createElement("p");
  body.textContent = text;
  bubble.append(body);
  if (sources.length) {
    const list = document.createElement("ul");
    list.className = "sources";
    for (const source of sources) {
      const item = document.createElement("li");
      item.innerHTML = `<strong>${escapeHtml(source.source)}</strong> — ${escapeHtml(source.section)}, версия ${escapeHtml(source.version)}`;
      list.append(item);
    }
    bubble.append(list);
  }
  if (diagnostics) bubble.append(diagnosticsBlock(diagnostics));
  article.append(avatar, bubble);
  chat.append(article);
  article.scrollIntoView({ behavior: "smooth", block: "end" });
}

async function refreshHealth() {
  try {
    const response = await fetch("/api/health");
    const data = await response.json();
    health.textContent = data.status === "ready"
      ? `Готово: ${data.chunks_before_indexing} чанков · ${data.search}`
      : "Нужны API-ключ и построенный индекс";
    health.className = data.status === "ready" ? "status ready" : "status warn";
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
    message("assistant", data.text, data.sources, data.diagnostics);
  } catch (error) {
    message("assistant", `Ошибка: ${error.message}`);
  } finally {
    submit.disabled = false;
    submit.textContent = "Отправить";
    input.focus();
  }
});

reindex.addEventListener("click", async () => {
  reindex.disabled = true;
  reindex.textContent = "Индексируем…";
  try {
    const response = await fetch("/api/reindex", { method: "POST" });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "Ошибка переиндексации");
    message("assistant", `Индекс обновлён: ${data.documents} документ, ${data.chunks} чанков.`);
    await refreshHealth();
  } catch (error) {
    message("assistant", `Ошибка: ${error.message}`);
  } finally {
    reindex.disabled = false;
    reindex.textContent = "Обновить индекс";
  }
});

refreshHealth();

