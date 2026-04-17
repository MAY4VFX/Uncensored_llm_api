# Model Filters Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Update the models catalog so filtering uses one compact chip cloud with AND semantics for derived tags, while adding sorting by newest, downloads, and likes.

**Architecture:** Keep the filtering UI centered in `frontend/src/app/models/page.tsx`, but change the interaction model: status remains single-select, size remains single-select, quant remains single-select, and derived tag chips become multi-select AND. Extend the admin models payload already returned from `/admin/models` so the frontend can sort by `created_at` without database changes or new storage.

**Tech Stack:** Next.js 14 App Router, React 18, TypeScript, Tailwind CSS, FastAPI response models

---

## File Structure

### Modify
- `frontend/src/app/models/page.tsx`
  - Collapse grouped filters into one chip cloud
  - Change tag semantics from OR to AND
  - Change quant semantics from multi-select to single-select
  - Add sorting state and sorted filtered list
  - Update clear button semantics
- `frontend/src/lib/api.ts`
  - Add `created_at` to the admin model type returned by `listAllModels`
- `backend/app/schemas/model.py`
  - Confirm/keep `created_at` in `ModelResponse` so the frontend can rely on it

### No new files
- Keep the implementation focused on the existing models page and its API typing.
- Do not add DB migrations, backend filtering, or URL state.

---

### Task 1: Update frontend model typing for sort metadata

**Files:**
- Modify: `frontend/src/lib/api.ts`
- Reference: `backend/app/schemas/model.py:7-26`

- [ ] **Step 1: Confirm `created_at` already exists in the backend response model**

Read and verify this backend schema:

```python
class ModelResponse(BaseModel):
    id: uuid.UUID
    slug: str
    display_name: str
    hf_repo: str
    params_b: float
    quantization: str
    gpu_type: str
    gpu_count: int = 1
    max_context_length: int
    status: str
    cost_per_1m_input: float
    cost_per_1m_output: float
    description: str | None
    system_prompt: str | None = None
    hf_downloads: int | None = None
    hf_likes: int | None = None
    created_at: datetime
```

Expected: `created_at` is already present, so no backend schema change is needed.

- [ ] **Step 2: Extend the frontend admin model type to include `created_at`**

In `frontend/src/lib/api.ts`, replace the `listAllModels` return type block:

```ts
export const listAllModels = (token: string) =>
  apiFetch<
    Array<{
      id: string;
      slug: string;
      display_name: string;
      hf_repo: string;
      params_b: number;
      quantization: string;
      gpu_type: string;
      gpu_count: number;
      status: string;
      cost_per_1m_input: number;
      cost_per_1m_output: number;
      description: string | null;
      hf_downloads: number | null;
      hf_likes: number | null;
    }>
  >("/admin/models", { token });
```

with:

```ts
export const listAllModels = (token: string) =>
  apiFetch<
    Array<{
      id: string;
      slug: string;
      display_name: string;
      hf_repo: string;
      params_b: number;
      quantization: string;
      gpu_type: string;
      gpu_count: number;
      status: string;
      cost_per_1m_input: number;
      cost_per_1m_output: number;
      description: string | null;
      hf_downloads: number | null;
      hf_likes: number | null;
      created_at: string;
    }>
  >("/admin/models", { token });
```

- [ ] **Step 3: Commit the API typing update**

```bash
git add frontend/src/lib/api.ts
git commit -m "feat(ui): add model created_at typing"
```

---

### Task 2: Update page model shape and filter state semantics

**Files:**
- Modify: `frontend/src/app/models/page.tsx`

- [ ] **Step 1: Extend the page-local `Model` interface with `created_at`**

In `frontend/src/app/models/page.tsx`, update the interface:

```tsx
interface Model {
  id: string;
  slug: string;
  display_name: string;
  hf_repo: string;
  params_b: number;
  quantization: string;
  gpu_type: string;
  gpu_count: number;
  status: string;
  cost_per_1m_input: number;
  cost_per_1m_output: number;
  description: string | null;
  hf_downloads: number | null;
  hf_likes: number | null;
  created_at: string | null;
}
```

- [ ] **Step 2: Add sort options and change quant state to single-select**

Replace the current top-level filter constants/state model so it includes sort state:

```tsx
const SORT_OPTIONS = ["newest", "downloads", "likes"] as const;
type SortOption = (typeof SORT_OPTIONS)[number];
```

Then replace this state block:

```tsx
const [statusFilter, setStatusFilter] = useState<string>("all");
const [sizeFilter, setSizeFilter] = useState<SizeBucket>("all");
const [quantFilters, setQuantFilters] = useState<QuantFilter[]>([]);
const [tagFilters, setTagFilters] = useState<TagFilter[]>([]);
```

with:

```tsx
const [statusFilter, setStatusFilter] = useState<string>("all");
const [sizeFilter, setSizeFilter] = useState<SizeBucket>("all");
const [quantFilter, setQuantFilter] = useState<QuantFilter | null>(null);
const [tagFilters, setTagFilters] = useState<TagFilter[]>([]);
const [sortBy, setSortBy] = useState<SortOption>("newest");
```

- [ ] **Step 3: Update the public fallback model mapping to include `created_at`**

Replace the public fallback mapping block with:

```tsx
setModels(
  data.data?.map((m: any) => ({
    id: m.id,
    slug: m.id,
    display_name: m.id,
    params_b: 0,
    quantization: "",
    gpu_type: "",
    gpu_count: 1,
    status: "active",
    cost_per_1m_input: 0,
    cost_per_1m_output: 0,
    description: null,
    hf_repo: "",
    hf_downloads: null,
    hf_likes: null,
    created_at: m.created ? new Date(m.created * 1000).toISOString() : null,
  })) || []
);
```

- [ ] **Step 4: Replace multi-select quant toggle with single-select quant setter**

Replace:

```tsx
const toggleQuantFilter = (quant: QuantFilter) => {
  setQuantFilters((prev) =>
    prev.includes(quant) ? prev.filter((value) => value !== quant) : [...prev, quant]
  );
};
```

with:

```tsx
const toggleQuantFilter = (quant: QuantFilter) => {
  setQuantFilter((prev) => (prev === quant ? null : quant));
};
```

- [ ] **Step 5: Update clear behavior to match the new design**

Replace:

```tsx
const clearExtraFilters = () => {
  setSizeFilter("all");
  setQuantFilters([]);
  setTagFilters([]);
};
```

with:

```tsx
const clearFilters = () => {
  setStatusFilter("all");
  setSizeFilter("all");
  setQuantFilter(null);
  setTagFilters([]);
  setSortBy("newest");
};
```

- [ ] **Step 6: Commit filter state changes**

```bash
git add frontend/src/app/models/page.tsx
git commit -m "feat(ui): update model filter state"
```

---

### Task 3: Change filter semantics and add sorting logic

**Files:**
- Modify: `frontend/src/app/models/page.tsx`

- [ ] **Step 1: Change quant matching helper to single-select**

Replace the quant helper:

```tsx
function matchesQuantFilter(model: Model, selectedQuants: QuantFilter[]): boolean {
  if (selectedQuants.length === 0) return true;

  const text = normalizeModelText(model);
  const quant = (model.quantization || "").toUpperCase();

  return selectedQuants.some((selected) => {
    if (selected === "GGUF") {
      return /gguf/i.test(text) || quant === "GGUF";
    }
    return quant === selected;
  });
}
```

with:

```tsx
function matchesQuantFilter(model: Model, selectedQuant: QuantFilter | null): boolean {
  if (!selectedQuant) return true;

  const text = normalizeModelText(model);
  const quant = (model.quantization || "").toUpperCase();

  if (selectedQuant === "GGUF") {
    return /gguf/i.test(text) || quant === "GGUF";
  }

  return quant === selectedQuant;
}
```

- [ ] **Step 2: Change tag matching from OR to AND**

Replace:

```tsx
function matchesTagFilter(model: Model, selectedTags: TagFilter[]): boolean {
  if (selectedTags.length === 0) return true;

  const derivedTags = getDerivedTags(model);
  return selectedTags.some((tag) => derivedTags.has(tag));
}
```

with:

```tsx
function matchesTagFilter(model: Model, selectedTags: TagFilter[]): boolean {
  if (selectedTags.length === 0) return true;

  const derivedTags = getDerivedTags(model);
  return selectedTags.every((tag) => derivedTags.has(tag));
}
```

- [ ] **Step 3: Update the `filtered` expression to use single quant**

Replace this part:

```tsx
const matchesQuant = matchesQuantFilter(m, quantFilters);
const matchesTags = matchesTagFilter(m, tagFilters);
```

with:

```tsx
const matchesQuant = matchesQuantFilter(m, quantFilter);
const matchesTags = matchesTagFilter(m, tagFilters);
```

- [ ] **Step 4: Add sorted filtered list**

Insert immediately below `filtered`:

```tsx
const sortedModels = [...filtered].sort((a, b) => {
  if (sortBy === "downloads") {
    return (b.hf_downloads || 0) - (a.hf_downloads || 0);
  }
  if (sortBy === "likes") {
    return (b.hf_likes || 0) - (a.hf_likes || 0);
  }

  const aTime = a.created_at ? new Date(a.created_at).getTime() : 0;
  const bTime = b.created_at ? new Date(b.created_at).getTime() : 0;
  return bTime - aTime;
});
```

- [ ] **Step 5: Update summary counters to use new state names**

Replace:

```tsx
const activeExtraFilterCount = (sizeFilter !== "all" ? 1 : 0) + quantFilters.length + tagFilters.length;
```

with:

```tsx
const activeFilterCount =
  (statusFilter !== "all" ? 1 : 0) +
  (sizeFilter !== "all" ? 1 : 0) +
  (quantFilter ? 1 : 0) +
  tagFilters.length;
```

- [ ] **Step 6: Commit filtering and sorting logic**

```bash
git add frontend/src/app/models/page.tsx
git commit -m "feat(ui): add model sorting and and-tag filters"
```

---

### Task 4: Replace grouped filter layout with one chip cloud and sort dropdown

**Files:**
- Modify: `frontend/src/app/models/page.tsx`

- [ ] **Step 1: Replace the separate Size / Quant / Tags sections with one chip cloud**

Remove the existing three labeled blocks and replace them with one compact section:

```tsx
{isAdmin && (
  <div className="flex flex-wrap gap-2 border-t border-surface-300 pt-3">
    {SIZE_BUCKETS.filter((bucket) => bucket !== "all").map((bucket) => {
      const isActive = sizeFilter === bucket;
      return (
        <button
          key={bucket}
          onClick={() => setSizeFilter(isActive ? "all" : bucket)}
          className={chipClass(isActive, "text-terminal-400 border-terminal-400")}
        >
          {sizeLabels[bucket]}
        </button>
      );
    })}

    {QUANT_FILTERS.map((quant) => {
      const isActive = quantFilter === quant;
      return (
        <button
          key={quant}
          onClick={() => toggleQuantFilter(quant)}
          className={chipClass(isActive, "text-terminal-400 border-terminal-400")}
        >
          {quant}
        </button>
      );
    })}

    {TAG_FILTERS.map((tag) => {
      const isActive = tagFilters.includes(tag);
      return (
        <button
          key={tag}
          onClick={() => toggleTagFilter(tag)}
          className={chipClass(isActive, "text-terminal-400 border-terminal-400")}
        >
          {tag}
        </button>
      );
    })}
  </div>
)}
```

- [ ] **Step 2: Add sort dropdown below the cloud**

Insert below the chip cloud:

```tsx
{isAdmin && (
  <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 border-t border-surface-300 pt-3">
    <div className="flex items-center gap-2">
      <label className="text-xs font-mono uppercase tracking-[0.2em] text-surface-900">Sort by</label>
      <select
        value={sortBy}
        onChange={(e) => setSortBy(e.target.value as SortOption)}
        className="input-field w-auto min-w-[180px]"
      >
        <option value="newest">Newest added</option>
        <option value="downloads">Most downloads</option>
        <option value="likes">Most likes</option>
      </select>
    </div>

    <button
      onClick={clearFilters}
      disabled={activeFilterCount === 0 && sortBy === "newest"}
      className="text-[10px] font-mono uppercase tracking-wider px-3 py-1.5 border text-surface-700 border-surface-400 hover:border-surface-600 disabled:opacity-40 disabled:hover:border-surface-400 transition-colors self-start"
    >
      Clear filters
    </button>
  </div>
)}
```

- [ ] **Step 3: Update the summary text**

Replace the current summary block with:

```tsx
<div className="border-t border-surface-300 pt-3">
  <p className="text-xs font-mono text-surface-800">
    {sortedModels.length} models found{isAdmin ? ` • sorted by ${sortBy}` : ""}
  </p>
</div>
```

- [ ] **Step 4: Render `sortedModels` instead of `filtered`**

Replace:

```tsx
{filtered.map((m) => (
```

with:

```tsx
{sortedModels.map((m) => (
```

- [ ] **Step 5: Commit the new cloud layout**

```bash
git add frontend/src/app/models/page.tsx
git commit -m "feat(ui): switch to model filter cloud layout"
```

---

### Task 5: Verify in deployed UI

**Files:**
- Modify: none
- Verify: `frontend/src/app/models/page.tsx`, admin `/models` page

- [ ] **Step 1: Push the completed branch or main update**

```bash
git push origin main
```

Expected: push succeeds and Dokploy starts frontend deploy.

- [ ] **Step 2: Verify status remains single-select**

Manual check:
- click `Active`
- click `Deploying`
- confirm the active selection switches rather than accumulates

Expected: only one status chip is active at a time.

- [ ] **Step 3: Verify size and quant are also single-select**

Manual check:
- click `30–70B`
- click `70B+`
- confirm only one remains active
- click `Q4`
- click `FP16`
- confirm only one remains active

Expected: size and quant behave like mutually exclusive selectors.

- [ ] **Step 4: Verify derived tags are AND, not OR**

Manual check:
- click `Qwen`
- then click `Reasoning`

Expected: list narrows to models matching both, not either.

- [ ] **Step 5: Verify sort dropdown**

Manual check:
- choose `Most downloads`
- confirm higher `hf_downloads` models bubble up
- choose `Most likes`
- confirm higher `hf_likes` models bubble up
- choose `Newest added`
- confirm recently added models appear first

Expected: filtering stays the same while item order changes.

- [ ] **Step 6: Verify clear behavior**

Manual check:
- set status, size, quant, and two tags
- change sort to `Most downloads`
- leave search text populated
- click `Clear filters`

Expected:
- status resets to `All`
- size resets
- quant resets
- tags reset
- sort resets to `Newest added`
- search text remains unchanged

- [ ] **Step 7: Verify public/non-admin safety**

Manual check:
- open page without admin auth

Expected:
- public path still works
- no broken layout
- no reliance on admin-only metadata causing empty or misleading filter cloud

- [ ] **Step 8: Confirm clean working tree**

```bash
git status
```

Expected: clean working tree.

---

## Self-Review

### Spec coverage
- One cloud layout: covered in Task 4.
- Status single-select: covered in Tasks 2 and 5.
- Size single-select: covered in Tasks 2, 3, and 5.
- Quant single-select: covered in Tasks 2, 3, and 5.
- Tags AND semantics: covered in Task 3 and Task 5.
- Sort by newest/downloads/likes: covered in Tasks 1, 3, 4, and 5.
- `created_at` support: covered in Task 1 and Task 2.
- Clear filters behavior: covered in Tasks 2, 4, and 5.
- Public/non-admin safety: covered in Task 5.

### Placeholder scan
- No TBD/TODO placeholders.
- Code snippets included for each code modification step.
- Verification steps contain exact expected behavior.

### Type consistency
- `SortOption`, `SizeBucket`, `QuantFilter`, `TagFilter` are defined before use.
- `quantFilter` naming is consistent after moving from multi-select to single-select.
- `sortedModels` is the final rendered list everywhere after sort is introduced.
