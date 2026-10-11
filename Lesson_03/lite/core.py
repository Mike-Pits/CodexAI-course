"""Shared Lite agents, strict response contracts and auditable API transport."""
import json
import os
import time
import urllib.request
import urllib.error
from pathlib import Path
from threading import Lock

ROOT = Path(__file__).resolve().parents[1]

def load_environment():
    """Read only known configuration keys; never execute a dotenv file as code."""
    path = ROOT / ".env"
    if not path.exists():
        return
    allowed = {"MODEL_API_KEY", "OPENAI_API_KEY", "API_BASE_URL", "API_STYLE", "JSON_MODE", "WORKER_MODEL", "JUDGE_MODEL", "CLIENT_MODEL", "PORT"}
    for line in path.read_text(encoding="utf-8").splitlines():
        key, sep, value = line.strip().partition("=")
        if sep and key in allowed:
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            os.environ.setdefault(key, value)

load_environment()

def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))

def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)

def obj(properties):
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}

S = {"type": "string"}
STRINGS = {"type": "array", "items": S}
CRITERIA = {"required_skills": 40, "experience": 25, "outcomes": 15, "bonus_skills": 10, "communication": 10}
DISCRETE_SCORES = {"experience": {0, 5, 15, 25}, "outcomes": {0, 3, 8, 15}, "communication": {0, 5, 10}}
RECRUIT_SCHEMA = obj({
    "score": {"type": "integer", "minimum": 0, "maximum": 100},
    "criteria": {"type": "array", "items": obj({
        "key": {"type": "string", "enum": list(CRITERIA)},
        "points": {"type": "integer", "minimum": 0, "maximum": 40},
        "max_points": {"type": "integer"}, "reason": S,
        "evidence": STRINGS, "missing": STRINGS})},
    "strengths": STRINGS, "gaps": STRINGS, "missing_information": STRINGS,
    "verdict": {"type": "string", "enum": ["interview", "clarify", "insufficient_evidence"]},
    "conclusion": S})
SALES_SCHEMA = obj({"message": S, "known_needs": STRINGS, "unknown_conditions": STRINGS, "next_step": S})

def validate(value, schema):
    kind = schema["type"]
    if kind == "object":
        if not isinstance(value, dict) or set(value) != set(schema["properties"]):
            raise ValueError("Ответ не соответствует полям JSON-схемы")
        for key, child in schema["properties"].items():
            validate(value[key], child)
    elif kind == "array":
        if not isinstance(value, list):
            raise ValueError("Ожидался массив")
        for child in value:
            validate(child, schema["items"])
    elif kind == "string":
        if not isinstance(value, str):
            raise ValueError("Ожидалась строка")
    elif kind == "boolean":
        if not isinstance(value, bool):
            raise ValueError("Ожидалось логическое значение")
    elif kind == "integer":
        if type(value) is not int or not schema.get("minimum", -10**9) <= value <= schema.get("maximum", 10**9):
            raise ValueError("Число вне диапазона")
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError("Неизвестное значение")

def recruit_checks(result, resume):
    issues = []
    if len(result["criteria"]) != 5 or {c["key"] for c in result["criteria"]} != set(CRITERIA):
        issues.append("Должно быть ровно пять разных критериев")
    for c in result["criteria"]:
        if c["key"] in DISCRETE_SCORES and c["points"] not in DISCRETE_SCORES[c["key"]]:
            issues.append("Баллы не соответствуют фиксированной шкале: " + c["key"])
        if c["max_points"] != CRITERIA[c["key"]] or not 0 <= c["points"] <= CRITERIA[c["key"]]:
            issues.append("Неверный диапазон критерия " + c["key"])
        if any(not quote.strip() or quote not in resume for quote in c["evidence"]):
            issues.append("Цитата не найдена в резюме: " + c["key"])
    if sum(c["points"] for c in result["criteria"]) != result["score"]:
        issues.append("Итог не равен сумме критериев")
    expected = "interview" if result["score"] >= 80 else "clarify" if result["score"] >= 50 else "insufficient_evidence"
    if result["verdict"] != expected:
        issues.append("Вывод не соответствует порогу")
    return issues

class ModelClient:
    def __init__(self, log_path=None, max_calls=1000):
        self.key = os.environ.get("MODEL_API_KEY") or os.environ.get("OPENAI_API_KEY", "")
        self.log_path = Path(log_path) if log_path else None
        self.max_calls = max_calls
        self.calls = 0
        self.lock = Lock()

    def ask(self, model, instructions, messages, schema, tag):
        if not self.key:
            raise RuntimeError("Задайте MODEL_API_KEY в окружении сервера. Ключ в чат отправлять не нужно.")
        if not model:
            raise RuntimeError("Не задана модель. Укажите WORKER_MODEL, JUDGE_MODEL и CLIENT_MODEL в окружении.")
        base = os.getenv("API_BASE_URL", "https://api.openai.com/v1").rstrip("/")
        transport = os.getenv("API_STYLE", "responses")
        if transport not in ("responses", "chat_completions"):
            raise ValueError("API_STYLE: responses или chat_completions")
        if transport == "responses":
            payload = {"model": model, "instructions": instructions, "input": messages,
                       "store": False, "text": {"format": {"type": "json_schema", "name": "answer", "strict": True, "schema": schema}}}
            endpoint = base + "/responses"
        else:
            mode = os.getenv("JSON_MODE", "json_schema")
            if mode not in ("json_schema", "json_object", "prompt"):
                raise ValueError("JSON_MODE: json_schema, json_object или prompt")
            payload = {"model": model, "messages": [{"role": "system", "content": instructions + "\nВерни только JSON по схеме:\n" + json.dumps(schema, ensure_ascii=False)}, *messages]}
            if mode == "json_schema":
                payload["response_format"] = {"type": "json_schema", "json_schema": {"name": "answer", "strict": True, "schema": schema}}
            elif mode == "json_object":
                payload["response_format"] = {"type": "json_object"}
            endpoint = base + "/chat/completions"
        with self.lock:
            if self.calls >= self.max_calls:
                raise RuntimeError("Достигнут лимит API-запросов; результаты сохранены")
            self.calls += 1
            call_id = self.calls
        start = time.monotonic()
        record = {"call": call_id, "tag": tag, "model": model, "request": payload}
        try:
            request = urllib.request.Request(endpoint,
                data=json.dumps(payload).encode(), headers={"Authorization": "Bearer " + self.key, "Content-Type": "application/json"})
            with urllib.request.urlopen(request, timeout=180) as response:
                raw = json.load(response)
            record["response"] = raw
            if transport == "responses":
                if raw.get("status") != "completed":
                    raise RuntimeError("Модель не завершила ответ")
                chunks = [c["text"] for item in raw.get("output", []) for c in item.get("content", []) if c.get("type") == "output_text"]
            else:
                choice = raw.get("choices", [{}])[0]
                if choice.get("finish_reason") != "stop":
                    raise RuntimeError("Модель не завершила ответ")
                chunks = [choice.get("message", {}).get("content", "")]
            if not chunks:
                raise RuntimeError("Модель отказалась отвечать или вернула пустой ответ")
            result = json.loads("".join(chunks))
            validate(result, schema)
            return result
        except urllib.error.HTTPError as exc:
            try:
                detail = json.loads(exc.read()).get("error", {})
                error_code = str(detail.get("code") or detail.get("type") or "unknown")
                error_code = error_code if error_code.replace("_", "").isalnum() else "unknown"
            except (ValueError, AttributeError):
                error_code = "unknown"
            record["error"] = f"HTTP {exc.code}: {error_code}"
            hints = {"insufficient_quota": "Квота API исчерпана. Проверьте баланс и лимит расходов проекта в OpenAI Platform.",
                     "credit_balance_exhausted": "Баланс кредитов API исчерпан. Проверьте биллинг в OpenAI Platform.",
                     "rate_limit_exceeded": "Достигнут временный лимит запросов API. Повторите позже."}
            hint = hints.get(error_code, "Проверьте модель, ключ, баланс и доступ.")
            raise RuntimeError(f"API: HTTP {exc.code} ({error_code}). {hint}") from None
        except Exception as exc:
            record["error"] = type(exc).__name__ + ": " + str(exc)
            raise
        finally:
            record["elapsed_seconds"] = round(time.monotonic() - start, 3)
            if self.log_path:
                with self.lock:
                    self.log_path.parent.mkdir(parents=True, exist_ok=True)
                    with self.log_path.open("a", encoding="utf-8") as out:
                        out.write(json.dumps(record, ensure_ascii=False) + "\n")

def prompt(name):
    return (ROOT / "prompts" / (name + "_v1.txt")).read_text(encoding="utf-8")

def recruit(client, model, vacancy, resume, instructions=None, tag="lite/recruiter", strict=True):
    result = client.ask(model, instructions or prompt("recruiter"),
        [{"role": "user", "content": json.dumps({"vacancy": vacancy, "resume": resume}, ensure_ascii=False)}], RECRUIT_SCHEMA, tag)
    issues = recruit_checks(result, resume)
    if strict and issues:
        raise ValueError("Некорректная оценка модели: " + "; ".join(issues))
    return result

def sell(client, model, history, instructions=None, tag="lite/sales"):
    context = json.dumps(read_json(ROOT / "data/product.json"), ensure_ascii=False)
    return client.ask(model, (instructions or prompt("sales")) + "\nPRODUCT_CONTEXT:\n" + context,
                      history, SALES_SCHEMA, tag)
