"use client";

import { useState } from "react";

const BASE_URL = "https://llm.ai-vfx.com/api/v1";
const MODEL = "davidau-qwen3-30b-a3b-claude-4-5-opus-high-reasoning-2507-abliterated-uncensored-v2";

const examples = {
  curl: `curl -X POST ${BASE_URL}/chat/completions \\
  -H "Authorization: Bearer sk-unch-your-key-here" \\
  -H "Content-Type: application/json" \\
  -d '{
    "model": "${MODEL}",
    "messages": [
      {"role": "user", "content": "Hello, how are you?"}
    ],
    "temperature": 0.7,
    "max_tokens": 512
  }'`,
  python: `from openai import OpenAI

client = OpenAI(
    api_key="sk-unch-your-key-here",
    base_url="${BASE_URL}"
)

response = client.chat.completions.create(
    model="${MODEL}",
    messages=[
        {"role": "user", "content": "Hello, how are you?"}
    ],
    temperature=0.7,
    max_tokens=512,
)

print(response.choices[0].message.content)`,
  javascript: `import OpenAI from "openai";

const client = new OpenAI({
  apiKey: "sk-unch-your-key-here",
  baseURL: "${BASE_URL}",
});

const response = await client.chat.completions.create({
  model: "${MODEL}",
  messages: [
    { role: "user", content: "Hello, how are you?" }
  ],
  temperature: 0.7,
  max_tokens: 512,
});

console.log(response.choices[0].message.content);`,
};

type Lang = keyof typeof examples;

export default function CodeExample() {
  const [lang, setLang] = useState<Lang>("python");

  return (
    <div className="border border-surface-400">
      <div className="flex border-b border-surface-400">
        {(Object.keys(examples) as Lang[]).map((l) => (
          <button
            key={l}
            onClick={() => setLang(l)}
            className={`px-5 py-2.5 text-xs font-mono uppercase tracking-widest transition-colors border-r border-surface-400 last:border-r-0 ${
              lang === l
                ? "bg-surface-200 text-terminal-400"
                : "bg-surface-100 text-surface-800 hover:text-neutral-300"
            }`}
          >
            {l === "curl" ? "curl" : l}
          </button>
        ))}
      </div>
      <pre className="bg-surface-50 p-6 overflow-x-auto">
        <code className="text-xs font-mono text-surface-900 whitespace-pre leading-relaxed">{examples[lang]}</code>
      </pre>
    </div>
  );
}
