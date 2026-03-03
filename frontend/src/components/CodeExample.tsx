"use client";

import { useState } from "react";

const examples = {
  curl: `curl -X POST https://api.unchained.ai/v1/chat/completions \\
  -H "Authorization: Bearer sk-unch-your-key-here" \\
  -H "Content-Type: application/json" \\
  -d '{
    "model": "your-model-slug",
    "messages": [
      {"role": "user", "content": "Hello, how are you?"}
    ],
    "temperature": 0.7,
    "max_tokens": 512
  }'`,
  python: `from openai import OpenAI

client = OpenAI(
    api_key="sk-unch-your-key-here",
    base_url="https://api.unchained.ai/v1"
)

response = client.chat.completions.create(
    model="your-model-slug",
    messages=[
        {"role": "user", "content": "Hello, how are you?"}
    ],
    temperature=0.7,
    max_tokens=512
)

print(response.choices[0].message.content)`,
  javascript: `import OpenAI from "openai";

const client = new OpenAI({
  apiKey: "sk-unch-your-key-here",
  baseURL: "https://api.unchained.ai/v1",
});

const response = await client.chat.completions.create({
  model: "your-model-slug",
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
    <div>
      <div className="flex gap-1 mb-0">
        {(Object.keys(examples) as Lang[]).map((l) => (
          <button
            key={l}
            onClick={() => setLang(l)}
            className={`px-4 py-2 text-sm rounded-t-lg transition-colors ${
              lang === l
                ? "bg-gray-800 text-cyan-400 border-t border-x border-gray-700"
                : "bg-gray-900 text-gray-500 hover:text-gray-300"
            }`}
          >
            {l === "curl" ? "cURL" : l === "python" ? "Python" : "JavaScript"}
          </button>
        ))}
      </div>
      <pre className="bg-gray-800 border border-gray-700 rounded-b-lg rounded-tr-lg p-4 overflow-x-auto">
        <code className="text-sm text-gray-300 whitespace-pre">{examples[lang]}</code>
      </pre>
    </div>
  );
}
