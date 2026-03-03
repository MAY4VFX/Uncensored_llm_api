import { createOpenAI } from "@ai-sdk/openai";
import { convertToModelMessages, streamText } from "ai";

export const maxDuration = 120;

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export async function POST(req: Request) {
  const { messages, model: modelSlug } = await req.json();

  // Extract JWT token from cookie or authorization header
  const authHeader = req.headers.get("authorization") || "";
  const token = authHeader.replace("Bearer ", "");

  if (!token) {
    return new Response(JSON.stringify({ error: "Not authenticated" }), {
      status: 401,
      headers: { "Content-Type": "application/json" },
    });
  }

  // Create an OpenAI-compatible client pointing to our own backend
  const unchained = createOpenAI({
    apiKey: token,
    baseURL: `${API_URL}/v1`,
    // Our backend accepts JWT tokens in the playground via the
    // standard /v1/chat/completions when using the playground proxy,
    // but for the playground we use a direct proxy approach
  });

  // Proxy directly to our backend's playground endpoint
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

  // Forward the SSE stream
  return new Response(response.body, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      Connection: "keep-alive",
    },
  });
}
