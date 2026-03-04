export const maxDuration = 120;

const API_URL = process.env.BACKEND_URL || "http://localhost:8000";

export async function POST(req: Request) {
  const { messages, model: modelSlug } = await req.json();

  const authHeader = req.headers.get("authorization") || "";
  const token = authHeader.replace("Bearer ", "");

  if (!token) {
    return new Response(JSON.stringify({ error: "Not authenticated" }), {
      status: 401,
      headers: { "Content-Type": "application/json" },
    });
  }

  const response = await fetch(`${API_URL}/playground/chat`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({
      model: modelSlug || "default",
      messages: messages.map((m: any) => ({
        role: m.role,
        content: typeof m.content === "string" ? m.content : m.content?.map((p: any) => p.text).join("") || "",
      })),
      stream: true,
    }),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Backend error" }));
    return new Response(JSON.stringify({ error: error.detail || "Request failed" }), {
      status: response.status,
      headers: { "Content-Type": "application/json" },
    });
  }

  return new Response(response.body, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      Connection: "keep-alive",
    },
  });
}
