const backendUrl = process.env.BACKEND_URL || "http://127.0.0.1:8000";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function POST(request: Request) {
  const upstream = await fetch(`${backendUrl}/api/v1/chat/stream`, {
    method: "POST",
    headers: {
      "Content-Type": request.headers.get("content-type") || "application/json",
      Accept: "text/event-stream",
    },
    body: await request.text(),
    cache: "no-store",
  });

  if (!upstream.body) {
    return new Response("Backend chat stream did not provide a response body.", {
      status: 502,
    });
  }

  return new Response(upstream.body, {
    status: upstream.status,
    headers: {
      "Content-Type": upstream.headers.get("content-type") || "text/event-stream; charset=utf-8",
      "Cache-Control": "no-cache, no-transform",
      Connection: "keep-alive",
      "X-Accel-Buffering": "no",
    },
  });
}
