#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$PROJECT_DIR/.env"
umask 077

printf '\nDeepSeek — подключение Lite и PRO\n\n'
printf 'Откройте официальный кабинет DeepSeek: https://platform.deepseek.com\n'
printf 'Создайте API key и вставьте его ниже. Ввод скрыт; ключ не отправляется в чат.\n\n'
read -r -s -p 'Вставьте ключ DeepSeek: ' DEEPSEEK_API_KEY
printf '\n'
if [[ -z "$DEEPSEEK_API_KEY" || "$DEEPSEEK_API_KEY" =~ [[:space:]] ]]; then
  printf 'Ключ пуст или содержит пробелы; .env не изменён.\n' >&2
  exit 1
fi

if [[ -f "$ENV_FILE" && ! -e "$PROJECT_DIR/.env.before-deepseek" ]]; then
  cp -- "$ENV_FILE" "$PROJECT_DIR/.env.before-deepseek"
  chmod 600 "$PROJECT_DIR/.env.before-deepseek"
fi

tmp=$(mktemp)
grep -vE '^(MODEL_API_KEY|API_BASE_URL|API_STYLE|JSON_MODE|WORKER_MODEL|JUDGE_MODEL|CLIENT_MODEL|PORT)=' "$ENV_FILE" 2>/dev/null >"$tmp" || true
{
  printf 'MODEL_API_KEY=%s\n' "$DEEPSEEK_API_KEY"
  printf 'API_BASE_URL=https://api.deepseek.com\n'
  printf 'API_STYLE=chat_completions\n'
  printf 'JSON_MODE=json_object\n'
  printf 'WORKER_MODEL=deepseek-flash\n'
  printf 'JUDGE_MODEL=deepseek-v4-pro\n'
  printf 'CLIENT_MODEL=deepseek-flash\n'
  printf 'PORT=8765\n'
} >>"$tmp"
mv "$tmp" "$ENV_FILE"
chmod 600 "$ENV_FILE"
unset DEEPSEEK_API_KEY

printf '\nНастройки сохранены в %s.\n' "$ENV_FILE"
printf 'Далее выполните: python3 -m lite.preflight\n'
printf 'После успешной проверки перезапустите локальный сервер.\n'
