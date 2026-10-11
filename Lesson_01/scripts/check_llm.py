"""Explicit provider check; requests only with --models or --probe."""
import argparse
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
load_dotenv(root / '.env')
from app.main import Settings
from app.llm import build_request, parse_reply, validate_provider


def main():
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--models', action='store_true', help='List models if GET /models is supported')
    group.add_argument('--probe', action='store_true', help='One potentially billable request, even in mock mode')
    args = parser.parse_args()
    settings = Settings.from_env()
    try:
        validate_provider(settings)
    except ValueError as error:
        raise SystemExit(str(error)) from None
    print('API format:', settings.api_format)
    if not args.models and not args.probe:
        print('No request sent. Use --models or --probe explicitly.')
        return
    if not settings.api_key:
        raise SystemExit('Заполните LLM_API_KEY в .env. Не присылайте ключ в чат.')
    if args.probe and not settings.model:
        raise SystemExit('Заполните LLM_MODEL точным ID модели провайдера.')
    try:
        with httpx.Client(timeout=httpx.Timeout(30, connect=4),
                          transport=httpx.HTTPTransport(retries=2), follow_redirects=False) as client:
            headers = {'Authorization': f'Bearer {settings.api_key}'}
            if args.models:
                response = client.get(settings.base_url.rstrip('/') + '/models', headers=headers)
            else:
                url, payload = build_request(settings, 'Отвечай кратко.', [{'role': 'user', 'content': 'Скажи привет.'}])
                response = client.post(url, headers=headers, json=payload)
            if response.status_code != 200:
                raise SystemExit(f'LLM API: HTTP {response.status_code}. Проверьте URL, ключ, модель и баланс. '
                                 'Список /models поддерживается не всеми провайдерами.')
            if args.models:
                for item in response.json()['data']:
                    print(item['id'])
            else:
                parse_reply(response.json(), settings.api_format)
                print('Успех: получен непустой завершённый ответ модели.')
    except httpx.HTTPError:
        raise SystemExit('Ошибка соединения с LLM-провайдером; ключ и тело ответа не выводятся.') from None
    except (ValueError, KeyError, TypeError, IndexError, AttributeError):
        raise SystemExit('Неполный ответ или неподдерживаемый формат ответа провайдера.') from None


if __name__ == '__main__':
    main()
