import { handleUpload } from '@vercel/blob/client';

const allowed = new Set(['video/webm', 'video/mp4']);

async function fetch(request) {
  if (request.method !== 'POST') {
    return Response.json({ error: 'Method not allowed' }, { status: 405 });
  }
  const origin = request.headers.get('origin');
  if (origin && new URL(origin).host !== new URL(request.url).host) {
    return Response.json({ error: 'Cross-origin upload is forbidden' }, { status: 403 });
  }
  try {
    const body = await request.json();
    const result = await handleUpload({
      body,
      request,
      onBeforeGenerateToken: async (pathname) => {
        const suffix = pathname.toLowerCase().split('.').pop();
        if (!['webm', 'mp4'].includes(suffix)) throw new Error('Only WebM and MP4 are allowed');
        return {
          allowedContentTypes: [...allowed],
          maximumSizeInBytes: 500_000_000,
          addRandomSuffix: true,
          tokenPayload: JSON.stringify({ kind: 'meeting-recording' }),
        };
      },
      onUploadCompleted: async () => {},
    });
    return Response.json(result);
  } catch (error) {
    return Response.json({ error: error instanceof Error ? error.message : 'Upload failed' }, { status: 400 });
  }
}

export default { fetch };
