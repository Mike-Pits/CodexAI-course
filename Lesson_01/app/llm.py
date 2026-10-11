"""Wire formats shared by the app and the explicit provider probe."""
from urllib.parse import urlsplit


def validate_provider(settings):
    url = urlsplit(settings.base_url)
    local = url.hostname in ('localhost', '127.0.0.1', '::1')
    if not url.hostname or not (url.scheme == 'https' or (url.scheme == 'http' and local)):
        raise ValueError('LLM_BASE_URL must use HTTPS (HTTP is allowed only on localhost)')
    if url.username or url.password or url.query or url.fragment:
        raise ValueError('LLM_BASE_URL must not contain credentials, query or fragment')
    if settings.api_format not in ('responses', 'chat_completions'):
        raise ValueError('LLM_API_FORMAT must be responses or chat_completions')
    if settings.token_parameter not in ('max_tokens', 'max_completion_tokens'):
        raise ValueError('LLM_TOKEN_PARAMETER must be max_tokens or max_completion_tokens')


def build_request(settings, instructions, messages):
    validate_provider(settings)
    payload = {'model': settings.model}
    if settings.api_format == 'responses':
        path = '/responses'
        payload.update(instructions=instructions, input=messages, store=False,
                       max_output_tokens=settings.max_output_tokens)
        if settings.reasoning_effort:
            payload['reasoning'] = {'effort': settings.reasoning_effort}
    else:
        path = '/chat/completions'
        payload['messages'] = [{'role': 'system', 'content': instructions}, *messages]
        payload[settings.token_parameter] = settings.max_output_tokens
        if settings.reasoning_effort:
            payload['reasoning_effort'] = settings.reasoning_effort
    return settings.base_url.rstrip('/') + path, payload


def parse_reply(data, api_format):
    if api_format == 'responses':
        if data.get('status') != 'completed':
            raise ValueError('Incomplete response')
        reply = '\n'.join(part['text'] for item in data.get('output', [])
                          if item.get('type') == 'message' for part in item.get('content', [])
                          if part.get('type') == 'output_text')
    else:
        choice = data['choices'][0]
        if choice.get('finish_reason') != 'stop':
            raise ValueError('Incomplete or non-text response')
        reply = choice['message']['content']
    if not isinstance(reply, str) or not reply.strip():
        raise ValueError('Empty response')
    return reply.strip()
