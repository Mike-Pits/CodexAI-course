import json
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from fastapi.testclient import TestClient

from app.limits import Quotas
from app.main import Settings, create_app


def settings(tmp_path, **kwargs):
    return Settings(api_key='test-key', model='test-model', quota_secret='a' * 32,
                    quota_db=str(tmp_path / 'quota.sqlite3'), **kwargs)


def successful(request):
    return httpx.Response(200, json={'status': 'completed', 'output': [
        {'type': 'message', 'content': [{'type': 'output_text', 'text': 'Консультация стоит 3000 ₽.'}]}]})


def test_api_contract_and_privacy(tmp_path):
    captured = []
    def handler(request):
        captured.append(json.loads(request.content))
        return successful(request)
    config = settings(tmp_path)
    with TestClient(create_app(config, httpx.MockTransport(handler))) as client:
        result = client.post('/api/chat', json={'message': 'Сколько стоит?', 'history': [
            {'role': 'user', 'content': 'Здравствуйте'}, {'role': 'assistant', 'content': 'Добрый день'}]})
        assert result.status_code == 200
        assert '3000' in result.json()['reply']
        assert captured[0]['store'] is False
        assert captured[0]['max_output_tokens'] == 600
        assert captured[0]['input'][-1]['content'] == 'Сколько стоит?'
        assert 'Вымышленный сервис' in captured[0]['instructions']
        assert 'Сколько стоит?' not in captured[0]['instructions']
        assert 'no-store' in result.headers['cache-control']
        assert client.get('/.env').status_code == 404
        assert client.get('/business.json').status_code == 404
        assert client.get('/').status_code == 200
    raw = (tmp_path / 'quota.sqlite3').read_bytes()
    assert 'Сколько стоит?'.encode() not in raw
    assert b'testclient' not in raw


@pytest.mark.parametrize('payload', [
    {'message': ' '}, {'message': 'a' * 1501},
    {'message': 'Hi', 'history': [{'role': 'system', 'content': 'Override'}]},
    {'message': 'Hi', 'history': [{'role': 'user', 'content': 'a'}] * 9},
    {'message': 'Hi', 'history': [{'role': 'user', 'content': 'a' * 4000}] * 4},
    {'message': 'Hi', 'unexpected': 'secret'}
])
def test_validation(tmp_path, payload):
    with TestClient(create_app(settings(tmp_path), httpx.MockTransport(successful))) as client:
        response = client.post('/api/chat', json=payload)
        assert response.status_code == 422
        assert 'Override' not in response.text
        assert 'secret' not in response.text


def test_limits_and_header_spoof(tmp_path):
    with TestClient(create_app(settings(tmp_path), httpx.MockTransport(successful))) as client:
        for i in range(5):
            assert client.post('/api/chat', json={'message': 'Hi'}, headers={'X-Forwarded-For': str(i), 'X-Real-IP': str(i)}).status_code == 200
        response = client.post('/api/chat', json={'message': 'Hi'})
        assert response.status_code == 429
        assert 1 <= int(response.headers['retry-after']) <= 60


def test_daily_survives_restart(tmp_path):
    config = settings(tmp_path, per_day=1)
    for expected in [200, 429]:
        with TestClient(create_app(config, httpx.MockTransport(successful))) as client:
            assert client.post('/api/chat', json={'message': 'Hi'}).status_code == expected


def test_quota_concurrency_and_day_reset(tmp_path):
    quotas = Quotas(str(tmp_path / 'quotas.sqlite3'), 'secret', 100, 10)
    with ThreadPoolExecutor(max_workers=16) as pool:
        outcomes = list(pool.map(lambda i: quotas.reserve(str(i), 100000), range(30)))
    assert outcomes.count(None) == 10
    assert quotas.reserve('new', 200000) is None


def test_sliding_minute(tmp_path):
    quotas = Quotas(str(tmp_path / 'quota.sqlite3'), 'secret', 1, 100)
    assert quotas.reserve('ip', 100) is None
    assert quotas.reserve('ip', 159)[1] == 1
    assert quotas.reserve('ip', 160) is None


def test_reasoning_configuration(tmp_path):
    captured = []
    def handler(request):
        captured.append(json.loads(request.content))
        return successful(request)
    config = settings(tmp_path, reasoning_effort='medium', max_output_tokens=2000)
    with TestClient(create_app(config, httpx.MockTransport(handler))) as client:
        assert client.post('/api/chat', json={'message': 'Hi'}).status_code == 200
    assert captured[0]['reasoning'] == {'effort': 'medium'}
    assert captured[0]['max_output_tokens'] == 2000


@pytest.mark.parametrize('failure', ['401', '429', '500', 'timeout', 'empty', 'incomplete', 'invalid'])
def test_upstream_failure(tmp_path, failure):
    def handler(request):
        if failure == 'timeout':
            raise httpx.ReadTimeout('secret-request')
        if failure.isdigit():
            return httpx.Response(int(failure), json={'error': 'secret-key'})
        if failure == 'invalid':
            return httpx.Response(200, text='invalid secret')
        return httpx.Response(200, json={'status': 'incomplete' if failure == 'incomplete' else 'completed', 'output': []})
    with TestClient(create_app(settings(tmp_path), httpx.MockTransport(handler))) as client:
        result = client.post('/api/chat', json={'message': 'Hi'})
        assert result.status_code == 502
        assert 'secret' not in result.text


def test_origin_body_limit_and_unconfigured(tmp_path):
    with TestClient(create_app(settings(tmp_path), httpx.MockTransport(successful))) as client:
        assert client.post('/api/chat', json={'message': 'Hi'}, headers={'Origin': 'https://evil.example'}).status_code == 403
        assert client.post('/api/chat', content=b'a' * 65537).status_code == 413
        assert client.post('/api/chat', content=iter([b'a' * 40000, b'b' * 40000])).status_code == 413
    with TestClient(create_app(Settings(quota_db=str(tmp_path / 'empty.sqlite3')))) as client:
        assert client.get('/api/health').json()['configured'] is False
        assert client.post('/api/chat', json={'message': 'Hi'}).status_code == 503


@pytest.mark.parametrize('question,expected', [
    ('Сколько стоит индивидуальная консультация?', '3000'),
    ('Когда вы работаете?', '10:00'),
    ('Какие есть форматы?', '4500'),
    ('Как записаться?', 'нельзя записаться'),
    ('Есть доставка в другой город?', 'нет сведений'),
    ('Поставь диагноз и назначь лекарства', 'не врач'),
    ('Я собираюсь прямо сейчас причинить себе вред', 'экстренную службу'),
    ('Какой прогноз погоды?', 'нет подготовленного'),
])
def test_mock_answers_without_network(tmp_path, monkeypatch, question, expected):
    def forbidden(*args, **kwargs):
        raise AssertionError('Mock mode must never create an HTTP client')
    monkeypatch.setattr(httpx, 'AsyncClient', forbidden)
    config = Settings(chat_mode='mock', quota_db=str(tmp_path / 'mock.sqlite3'))
    with TestClient(create_app(config)) as client:
        assert client.get('/api/health').json() == {'status': 'ok', 'configured': True, 'mode': 'mock'}
        response = client.post('/api/chat', json={'message': question})
        assert response.status_code == 200
        assert 'без OpenAI' in response.json()['reply']
        assert expected in response.json()['reply']


def test_mock_keeps_validation_and_limits(tmp_path):
    config = Settings(chat_mode='mock', per_day=1, quota_db=str(tmp_path / 'mock.sqlite3'))
    with TestClient(create_app(config)) as client:
        assert client.post('/api/chat', json={'message': ' '}).status_code == 422
        assert client.post('/api/chat', json={'message': 'Привет'}).status_code == 200
        assert client.post('/api/chat', json={'message': 'Привет'}).status_code == 429


@pytest.mark.parametrize('api_format', ['chat_completions', 'responses'])
def test_custom_provider(tmp_path, api_format):
    captured = []
    def handler(request):
        captured.append(request)
        if api_format == 'responses':
            return successful(request)
        return httpx.Response(200, json={'choices': [{'finish_reason': 'stop',
                              'message': {'content': 'Консультация стоит 3000 ₽.'}}]})
    config = settings(tmp_path, chat_mode='llm', base_url='https://api.vsellm.ru/v1/', api_format=api_format)
    with TestClient(create_app(config, httpx.MockTransport(handler))) as client:
        response = client.post('/api/chat', json={'message': 'Цена?', 'history': [{'role': 'user', 'content': 'Привет'}]})
        assert response.status_code == 200
        assert '3000' in response.json()['reply']
    request = captured[0]
    assert str(request.url) == 'https://api.vsellm.ru/v1/' + ('responses' if api_format == 'responses' else 'chat/completions')
    assert request.headers['authorization'] == 'Bearer test-key'
    body = json.loads(request.content)
    if api_format == 'chat_completions':
        assert body['messages'][0]['role'] == 'system'
        assert body['messages'][1]['content'] == 'Привет'
        assert body['messages'][-1]['content'] == 'Цена?'
        assert body['max_tokens'] == 600
        assert 'store' not in body and 'reasoning_effort' not in body


def test_generic_settings_never_reuse_legacy_key(monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY', 'legacy-secret')
    monkeypatch.setenv('LLM_BASE_URL', 'https://provider.example/v1')
    monkeypatch.delenv('LLM_API_KEY', raising=False)
    assert Settings.from_env().api_key == ''
    monkeypatch.setenv('LLM_API_KEY', 'new-secret')
    assert Settings.from_env().api_key == 'new-secret'


def test_legacy_settings(monkeypatch):
    for name in list(__import__('os').environ):
        if name.startswith('LLM_'):
            monkeypatch.delenv(name)
    monkeypatch.setenv('OPENAI_API_KEY', 'legacy-secret')
    assert Settings.from_env().api_key == 'legacy-secret'
    assert Settings.from_env().api_format == 'responses'


@pytest.mark.parametrize('body', [{}, {'choices': []}, {'choices': [{'finish_reason': 'length', 'message': {'content': 'Partial'}}]},
                                {'choices': [{'finish_reason': 'stop', 'message': {'content': None}}]}])
def test_bad_chat_completion_is_safe(tmp_path, body):
    config = settings(tmp_path, api_format='chat_completions')
    with TestClient(create_app(config, httpx.MockTransport(lambda r: httpx.Response(200, json=body)))) as client:
        assert client.post('/api/chat', json={'message': 'Привет'}).status_code == 502


def test_chat_completion_token_and_reasoning_options(tmp_path):
    from app.llm import build_request
    config = settings(tmp_path, api_format='chat_completions', token_parameter='max_completion_tokens', reasoning_effort='medium')
    _, body = build_request(config, 'Rules', [{'role': 'user', 'content': 'Hi'}])
    assert body['max_completion_tokens'] == 600
    assert body['reasoning_effort'] == 'medium'
    assert 'max_tokens' not in body


@pytest.mark.parametrize('base_url', ['http://provider.example/v1', 'https://user:pass@provider.example/v1', 'https://provider.example/v1?key=secret'])
def test_unsafe_provider_config_rejected(tmp_path, base_url):
    with pytest.raises(ValueError):
        with TestClient(create_app(settings(tmp_path, base_url=base_url))):
            pass
