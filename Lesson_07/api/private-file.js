import { createClient } from '@libsql/client';
import { get } from '@vercel/blob';

function database() {
  return createClient({ url: process.env.TURSO_DATABASE_URL, authToken: process.env.TURSO_AUTH_TOKEN });
}

export default async function handler(request) {
  if (request.method !== 'GET' && request.method !== 'HEAD') return new Response('Method not allowed', { status: 405 });
  const url = new URL(request.url);
  const meeting = url.searchParams.get('meeting');
  const file = url.searchParams.get('file');
  if (!meeting || !file) return new Response('Missing file reference', { status: 400 });
  const client = database();
  try {
    const row = await client.execute({
      sql: "SELECT f.path FROM files f JOIN meetings m ON m.id=f.meeting_id WHERE f.id=? AND f.meeting_id=? AND m.deleted=0",
      args: [file, meeting],
    });
    if (!row.rows.length) return new Response('Not found', { status: 404 });
    const result = await get(String(row.rows[0].path), {
      access: 'private',
      ifNoneMatch: request.headers.get('if-none-match') || undefined,
    });
    if (!result) return new Response('Not found', { status: 404 });
    if (result.statusCode === 304) {
      return new Response(null, { status: 304, headers: { ETag: result.blob.etag, 'Cache-Control': 'private, no-cache' } });
    }
    return new Response(request.method === 'HEAD' ? null : result.stream, {
      headers: {
        'Content-Type': result.blob.contentType,
        'Content-Length': String(result.blob.size),
        ETag: result.blob.etag,
        'Cache-Control': 'private, no-cache',
        'X-Content-Type-Options': 'nosniff',
      },
    });
  } finally {
    client.close();
  }
}
