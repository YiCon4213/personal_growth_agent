const backendUrl = process.env.BACKEND_URL || "http://127.0.0.1:8000";
const maxRequestBytes = 12 * 1024 * 1024;

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

async function readLimitedBody(request: Request): Promise<Uint8Array> {
  const declaredLength = Number(request.headers.get("content-length") || "0");
  if (Number.isFinite(declaredLength) && declaredLength > maxRequestBytes) {
    throw new Error("request_too_large");
  }
  if (!request.body) return new Uint8Array();

  const reader = request.body.getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    total += value.byteLength;
    if (total > maxRequestBytes) {
      await reader.cancel();
      throw new Error("request_too_large");
    }
    chunks.push(value);
  }
  const body = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    body.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return body;
}

export async function POST(request: Request) {
  let body: Uint8Array;
  try {
    body = await readLimitedBody(request);
  } catch (error) {
    if (error instanceof Error && error.message === "request_too_large") {
      return Response.json({ detail: "Request body exceeds the configured limit." }, { status: 413 });
    }
    throw error;
  }

  const headers: Record<string, string> = {
    "Content-Type": request.headers.get("content-type") || "application/json",
    Accept: "text/event-stream",
  };
  const requestId = request.headers.get("x-request-id");
  const forwardedFor = request.headers.get("x-forwarded-for");
  if (requestId) headers["X-Request-ID"] = requestId;
  if (forwardedFor) headers["X-Forwarded-For"] = forwardedFor;

  const upstream = await fetch(`${backendUrl}/api/v1/chat/stream`, {
    method: "POST",
    headers,
    body,
    cache: "no-store",
  });

  if (!upstream.body) {
    return new Response("Backend chat stream did not provide a response body.", { status: 502 });
  }

  return new Response(upstream.body, {
    status: upstream.status,
    headers: {
      "Content-Type": upstream.headers.get("content-type") || "text/event-stream; charset=utf-8",
      "Cache-Control": "no-cache, no-transform",
      Connection: "keep-alive",
      "X-Accel-Buffering": "no",
      ...(upstream.headers.get("x-request-id")
        ? { "X-Request-ID": upstream.headers.get("x-request-id") as string }
        : {}),
    },
  });
}
