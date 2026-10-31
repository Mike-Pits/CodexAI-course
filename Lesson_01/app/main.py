import json
import logging
import os
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, field_validator
from starlette.concurrency import run_in_threadpool

from app.limits import Quotas
from app.demo import demo_reply
from app.llm import build_request, parse_reply, validate_provider

ROOT = Path(__file__).parent
load_dotenv()
logger = logging.getLogger('tochka')


@dataclass
class Settings:
    api_key: str = ''
    model: str = ''
    quota_secret: str = ''
    quota_db: str = 'data/quotas.sqlite3'
    per_minute: int = 5
    per_day: int = 100
    public_origin: str = 'http://127.0.0.1:8000'
    reasoning_effort: str = ''
    max_output_tokens: int = 600
    chat_mode: str = 'openai'
    base_url: str = 'https://api.openai.com/v1'
    api_format: str = 'responses'
    token_parameter: str = 'max_tokens'

    @classmethod
    def from_env(cls):
        # Never forward a legacy OpenAI key to a newly configured third-party host.
        generic = any(name in os.environ for name in ('LLM_BASE_URL', 'LLM_API_KEY', 'LLM_MODEL'))
        return cls(os.getenv('LLM_API_KEY' if generic else 'OPENAI_API_KEY', ''),
                   os.getenv('LLM_MODEL' if generic else 'OPENAI_MODEL', ''),
                   os.getenv('QUOTA_SECRET', ''), os.getenv('QUOTA_DB', 'data/quotas.sqlite3'),
                   int(os.getenv('REQUESTS_PER_MINUTE', '5')), int(os.getenv('REQUESTS_PER_DAY', '100')),
                   os.getenv('PUBLIC_ORIGIN', 'http://127.0.0.1:8000').rstrip('/'),
                   os.getenv('LLM_REASONING_EFFORT' if generic else 'OPENAI_REASONING_EFFORT', ''),
                   int(os.getenv('MAX_OUTPUT_TOKENS', '600')),
                   os.getenv('CHAT_MODE', 'openai'),
                   os.getenv('LLM_BASE_URL', 'https://api.openai.com/v1').rstrip('/'),
                   os.getenv('LLM_API_FORMAT', 'chat_completions' if generic else 'responses'),
                   os.getenv('LLM_TOKEN_PARAMETER', 'max_tokens'))


class Message(BaseModel):
    model_config = ConfigDict(extra='forbid')
    role: Literal['user', 'assistant']
    content: str = Field(min_length=1, max_length=4000)

    @field_validator('content')
    @classmethod
    def nonempty(cls, value):
        if not value.strip():
            raise ValueError('empty')
        return value.strip()


class ChatInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    message: str = Field(min_length=1, max_length=1500)
    history: list[Message] = Field(default_factory=list, max_length=8)

    @field_validator('message')
    @classmethod
    def nonempty(cls, value):
        if not value.strip():
            raise ValueError('empty')
        return value.strip()


class ChatOutput(BaseModel):
    reply: str


class BodyLimit:
    """Bound even chunked bodies before JSON parsing; no user body in errors."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        body = bytearray()
        while True:
            event = await receive()
            if event['type'] == 'http.disconnect':
                return
            body.extend(event.get('body', b''))
            if len(body) > 65536:
                return await JSONResponse({'detail': 'Сообщение слишком большое.'}, 413)(scope, receive, send)
            if not event.get('more_body', False):
                break
        delivered = False

        async def replay():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {'type': 'http.request', 'body': bytes(body), 'more_body': False}
            return await receive()
        await self.app(scope, replay, send)


def create_app(settings: Settings | None = None, transport=None):
    settings = settings or Settings.from_env()
    instructions = (ROOT / 'prompt.txt').read_text() + (ROOT / 'business.json').read_text()
    business = json.loads((ROOT / 'business.json').read_text())

    @asynccontextmanager
    async def lifespan(app):
        if settings.chat_mode not in ('openai', 'llm', 'mock'):
            raise RuntimeError('CHAT_MODE must be llm or mock (openai is a legacy alias)')
        if settings.chat_mode != 'mock':
            validate_provider(settings)
        if settings.per_minute < 1 or settings.per_day < 1:
            raise RuntimeError('Quota limits must be positive')
        if settings.reasoning_effort not in ('', 'none', 'low', 'medium', 'high', 'xhigh', 'max'):
            raise RuntimeError('Invalid LLM_REASONING_EFFORT')
        if not 100 <= settings.max_output_tokens <= 4000:
            raise RuntimeError('MAX_OUTPUT_TOKENS must be between 100 and 4000')
        if settings.chat_mode != 'mock' and settings.api_key and len(settings.quota_secret) < 32:
            raise RuntimeError('Set QUOTA_SECRET to at least 32 characters')
        app.state.quotas = Quotas(settings.quota_db, settings.quota_secret, settings.per_minute, settings.per_day)
        if settings.chat_mode == 'mock':
            yield
            return
        # Retry connection establishment only; never replay a sent generation request.
        llm_transport = transport if transport is not None else httpx.AsyncHTTPTransport(retries=2)
        async with httpx.AsyncClient(timeout=httpx.Timeout(30, connect=4), transport=llm_transport) as client:
            app.state.client = client
            yield

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(BodyLimit)

    @app.middleware('http')
    async def headers(request, call_next):
        response = await call_next(request)
        response.headers.update({
            'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
            'Referrer-Policy': 'no-referrer', 'X-Frame-Options': 'DENY',
            'Content-Security-Policy': "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
            'Permissions-Policy': 'camera=(), microphone=(), geolocation=()'
        })
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        return JSONResponse({'detail': 'Проверьте сообщение: до 1500 символов и до 8 сообщений истории.'}, 422)

    @app.get('/api/health')
    async def health():
        return {'status': 'ok', 'configured': settings.chat_mode == 'mock' or bool(settings.api_key and settings.model),
                'mode': settings.chat_mode}

    @app.get('/api/services')
    async def filter_services(max_price_rub: int = Query(ge=0, le=10000)):
        """Return demo services that fit the selected inclusive budget."""
        return {'services': [service for service in business['services']
                             if service['price_rub'] <= max_price_rub]}

    @app.post('/api/chat', response_model=ChatOutput)
    async def chat(payload: ChatInput, request: Request):
        origin = request.headers.get('origin')
        if origin and origin != settings.public_origin:
            raise HTTPException(403, 'Запрос с другого сайта запрещён.')
        if settings.chat_mode != 'mock' and (not settings.api_key or not settings.model):
            raise HTTPException(503, 'Чат ещё настраивается. Попробуйте позже.')
        if sum(len(m.content) for m in payload.history) > 12000:
            raise HTTPException(422, 'История слишком длинная. Начните новый диалог.')
        # Client-supplied forwarding headers are ignored; Uvicorn proxy headers are disabled.
        # Caddy is the only ingress to the unpublished app port and overwrites this header.
        ip = request.client.host if request.client else 'unknown'
        if os.getenv('TRUST_CADDY') == '1':
            ip = request.headers.get('x-real-ip', ip)
        limited = await run_in_threadpool(app.state.quotas.reserve, ip, time.time())
        if limited:
            raise HTTPException(429, limited[0], headers={'Retry-After': str(limited[1])})
        if settings.chat_mode == 'mock':
            return ChatOutput(reply=demo_reply(payload.message, business))
        url, api_input = build_request(settings, instructions,
            [m.model_dump() for m in payload.history] + [{'role': 'user', 'content': payload.message}])
        try:
            response = await app.state.client.post(url,
                headers={'Authorization': f'Bearer {settings.api_key}'},
                json=api_input)
            response.raise_for_status()
            reply = parse_reply(response.json(), settings.api_format)
            return ChatOutput(reply=reply)
        except (httpx.HTTPError, ValueError, KeyError, TypeError, IndexError, AttributeError):
            logger.warning('LLM request failed')  # no prompt, key, response body or IP
            raise HTTPException(502, 'Не удалось получить ответ. Попробуйте немного позже.') from None

    app.mount('/', StaticFiles(directory=ROOT / 'static', html=True), name='static')
    return app


app = create_app()
