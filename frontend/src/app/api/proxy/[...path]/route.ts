export const maxDuration = 120;

const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:8000";

async function proxyRequest(req: Request) {
  const url = new URL(req.url);
  const path = url.pathname.replace("/api/proxy", "");
  const backendUrl = `${BACKEND_URL}${path}${url.search}`;

  const headers: Record<string, string> = {
    "Content-Type": req.headers.get("content-type") || "application/json",
  };

  const auth = req.headers.get("authorization");
  if (auth) {
    headers["Authorization"] = auth;
  }

  const isBodyMethod = ["POST", "PUT", "PATCH"].includes(req.method);
  const response = await fetch(backendUrl, {
    method: req.method,
    headers,
    body: isBodyMethod ? await req.text() : undefined,
  });

  const responseHeaders = new Headers();
  const ct = response.headers.get("content-type");
  if (ct) responseHeaders.set("content-type", ct);

  if (ct?.includes("text/event-stream")) {
    responseHeaders.set("cache-control", "no-cache");
    responseHeaders.set("connection", "keep-alive");
  }

  return new Response(response.body, {
    status: response.status,
    headers: responseHeaders,
  });
}

export async function GET(req: Request) { return proxyRequest(req); }
export async function POST(req: Request) { return proxyRequest(req); }
export async function PUT(req: Request) { return proxyRequest(req); }
export async function DELETE(req: Request) { return proxyRequest(req); }
export async function PATCH(req: Request) { return proxyRequest(req); }
