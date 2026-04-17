# Copy Model ID on Model Card Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Добавить на карточку модели явную кнопку `Copy ID`, которая копирует полный slug и временно показывает состояние `Copied`.

**Architecture:** Изменение локализуется внутри `ModelCard`: компонент уже получает `slug`, поэтому копирование можно реализовать без изменения API и без проброса нового состояния через страницу `/models`. Локальный `useState` внутри карточки будет хранить кратковременное состояние подтверждения после успешного копирования.

**Tech Stack:** Next.js / React client component, TypeScript, browser Clipboard API, существующие стили карточки модели.

---

## File Structure

- **Modify:** `frontend/src/components/ModelCard.tsx`
  - Добавить кнопку `Copy ID`
  - Копировать полный `slug` через Clipboard API
  - Показать временное состояние `Copied`

---

### Task 1: Добавить failing test-планку через ручную verification checklist

**Files:**
- Modify: `frontend/src/components/ModelCard.tsx`
- Test: manual browser verification only

- [ ] **Step 1: Re-read the target component before editing**

Run:
```bash
python3 - <<'PY'
from pathlib import Path
p = Path('/Users/may/Uncensored_llm_api/frontend/src/components/ModelCard.tsx')
print(p.read_text())
PY
```
Expected: видно, что `ModelCard` уже получает `slug` prop и внизу карточки выводит его как `<code>`.

- [ ] **Step 2: Define the exact manual acceptance criteria before writing code**

Use this checklist while implementing:

```text
[ ] Card shows visible "Copy ID" button next to slug
[ ] Clicking button copies full slug value from props
[ ] Button text changes to "Copied"
[ ] Button returns to "Copy ID" after a short delay
[ ] Copied value is full slug even if slug text is visually truncated
```

- [ ] **Step 3: Do not commit anything yet**

No code changes should be committed before the implementation and manual verification are complete.

---

### Task 2: Реализовать кнопку Copy ID в карточке модели

**Files:**
- Modify: `frontend/src/components/ModelCard.tsx`
- Test: browser/manual verification

- [ ] **Step 1: Add React state import and copied state**

Change the top of `frontend/src/components/ModelCard.tsx` to import `useState`:

```tsx
import { useState } from "react";

interface ModelCardProps {
  id: string;
  slug: string;
  displayName: string;
  paramsB: number;
  quantization: string;
  gpuType: string;
  gpuCount?: number;
  status: string;
  costInput: number;
  costOutput: number;
  description: string | null;
  hfRepo?: string;
  hfDownloads?: number | null;
  hfLikes?: number | null;
  isAdmin?: boolean;
  onDeploy?: (modelId: string) => void;
  onUndeploy?: (modelId: string) => void;
  deploying?: boolean;
  undeploying?: boolean;
}
```

Then inside `ModelCard(...)`, directly after `const st = ...`, add:

```tsx
  const [copied, setCopied] = useState(false);
```

- [ ] **Step 2: Add a small copy handler that uses the full slug prop**

Inside `ModelCard(...)`, directly after `const [copied, setCopied] = useState(false);`, add:

```tsx
  const handleCopySlug = async () => {
    try {
      await navigator.clipboard.writeText(slug);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      setCopied(false);
    }
  };
```

- [ ] **Step 3: Replace the bottom slug row with slug + explicit Copy ID button**

Replace this block in `frontend/src/components/ModelCard.tsx`:

```tsx
      <div className="mt-3 pt-3 border-t border-surface-300 flex items-center justify-between gap-2">
        <code className="text-[10px] font-mono text-surface-700 break-all flex-1 min-w-0 truncate">{slug}</code>
        {isAdmin && (status === "inactive" || status === "pending") && onDeploy && (
```

with this:

```tsx
      <div className="mt-3 pt-3 border-t border-surface-300 flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0 flex-1">
          <code className="text-[10px] font-mono text-surface-700 break-all flex-1 min-w-0 truncate">{slug}</code>
          <button
            type="button"
            onClick={handleCopySlug}
            className="text-[10px] font-mono uppercase tracking-wider px-2 py-1 border text-surface-800 border-surface-400 bg-surface-100 hover:bg-surface-200 transition-colors flex-shrink-0"
            title="Copy model ID"
          >
            {copied ? "Copied" : "Copy ID"}
          </button>
        </div>
        {isAdmin && (status === "inactive" || status === "pending") && onDeploy && (
```

This keeps the existing layout, adds a clear text button, and ensures the copied value comes from `slug` rather than whatever is visually shown.

- [ ] **Step 4: Verify the file still parses cleanly by reading the modified section**

Run:
```bash
python3 - <<'PY'
from pathlib import Path
p = Path('/Users/may/Uncensored_llm_api/frontend/src/components/ModelCard.tsx')
text = p.read_text()
start = text.index('const [copied, setCopied] = useState(False)') if 'const [copied, setCopied] = useState(False)' in text else text.index('const [copied, setCopied] = useState(false)')
print(text[start:start+1200])
PY
```
Expected: видно `useState`, `handleCopySlug`, кнопку `Copy ID` и существующие admin actions ниже без поломки JSX-структуры.

- [ ] **Step 5: Commit the implementation**

```bash
git add frontend/src/components/ModelCard.tsx
git commit -m "feat(ui): add copy model id action to model cards"
```

---

### Task 3: Проверить поведение в UI вручную

**Files:**
- Modify: none
- Test: browser/manual verification only

- [ ] **Step 1: Open the models page and verify the new button is visible**

Check in the running app that each model card now shows:
- slug text
- explicit `Copy ID` button

Expected: кнопка читается как действие и не выглядит как неочевидная иконка.

- [ ] **Step 2: Click Copy ID on one real model card**

Expected:
- button text changes from `Copy ID` to `Copied`
- state returns to `Copy ID` after about 1.5 seconds

- [ ] **Step 3: Paste clipboard contents into a text field or terminal**

Expected: в clipboard полный slug, а не укороченная строка, даже если на карточке slug визуально обрезан.

Example expected value shape:
```text
ArliAI/gpt-oss-120b-Derestricted
```
or the project slug equivalent shown on the card.

- [ ] **Step 4: Verify admin actions still remain usable**

If logged in as admin, check that `Deploy` / `Undeploy` buttons still align and remain clickable.

Expected: новая кнопка не ломает нижнюю строку карточки и не перекрывает admin actions.

- [ ] **Step 5: Do not commit anything here unless you had to fix a bug**

If manual verification exposed a layout bug and you fixed it, commit that follow-up fix with:

```bash
git add frontend/src/components/ModelCard.tsx
git commit -m "fix(ui): align copy model id action on model cards"
```

If no follow-up fix was needed, skip this commit.

---

## Spec Coverage Check

- **Явная кнопка `Copy ID`:** covered by Task 2 Step 3.
- **Копирование полного slug из данных:** covered by Task 2 Step 2 and Task 3 Step 3.
- **Временный статус `Copied`:** covered by Task 2 Step 2 and Task 3 Step 2.
- **Без иконки-only UX:** covered by Task 2 Step 3.
- **Без API изменений и большого рефакторинга:** covered by File Structure + Task 2 localized changes.

No spec gaps found.
