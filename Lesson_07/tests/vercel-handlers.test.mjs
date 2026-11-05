import assert from 'node:assert/strict';
import test from 'node:test';

import aiProcess, {
  DEFAULT_TRANSCRIPTION_MODEL,
  processingErrorMessage,
} from '../api/ai-process.js';
import blobUpload from '../api/blob-upload.js';
import privateFile from '../api/private-file.js';

for (const [name, handler] of [
  ['ai-process', aiProcess],
  ['blob-upload', blobUpload],
  ['private-file', privateFile],
]) {
  test(`${name} uses the Vercel Web Handler contract`, () => {
    assert.equal(typeof handler, 'object');
    assert.equal(typeof handler.fetch, 'function');
  });
}

test('blob-upload handles a Web Request without a runtime type error', async () => {
  const response = await blobUpload.fetch(new Request('https://example.test/api/blob-upload', {
    method: 'POST',
    headers: { 'content-type': 'application/json', origin: 'https://example.test' },
    body: '{}',
  }));

  assert.equal(response.status, 400);
  const payload = await response.json();
  assert.equal(typeof payload.error, 'string');
});

test('AI Gateway billing failures have an actionable public message', () => {
  const error = Object.assign(new Error('credit card required'), {
    name: 'GatewayInternalServerError',
    statusCode: 403,
    cause: new Error('{"error":{"type":"customer_verification_required"}}'),
  });

  assert.match(processingErrorMessage(error), /платёжн.*карт/i);
  assert.doesNotMatch(processingErrorMessage(error), /GatewayInternalServerError/);
});

test('the default transcription model exists in the AI Gateway catalog', () => {
  assert.equal(DEFAULT_TRANSCRIPTION_MODEL, 'openai/gpt-4o-mini-transcribe');
});
