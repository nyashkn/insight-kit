---
name: agent-browser-verify
type: skill
description: Post-hydration Evidence page verification. Invoke on curl returning 200 but user sees "Application Error" / blank charts / failed mounts; or for post-deploy smoke tests.
roles_using: [renderer, critic, analyst]
metadata:
  last_verified: 2026-04-29
---

## Purpose

Evidence pages use Svelte server-side rendering (SSR) + client-side hydration. A page that returns HTTP 200 and contains valid-looking HTML in `curl` output can still fail at runtime — Svelte hydrates claim components asynchronously after the initial HTML is delivered. Raw HTML inspection (`curl`, `requests.get`) only sees the SSR shell; it cannot detect "Application Error" messages, blank chart containers, or failed component mounts that only appear after JavaScript executes. This skill establishes the correct verification workflow.

## When to invoke

- After deploying or rebuilding an Evidence reports site.
- When a preflight passes but a user reports a blank chart or "Application Error" in the browser.
- When verifying that `<ClaimBlock>`, `<ClaimInline>`, or `<ProvenanceRail>` rendered correctly.
- When a critic claims a page is broken but curl returns 200.
- When running post-deploy smoke tests in CI.

## Why curl can lie on Evidence pages

Evidence pages emit an initial HTML shell during build. That shell includes:

1. Static content and skeleton HTML (visible to curl).
2. Svelte component placeholders that are empty `<div>` elements until JS runs.
3. `<script>` tags that trigger hydration.

When a Svelte component fails (e.g., `ClaimBlock` cannot find its data query, or `evidenceInclude=true` is missing), Evidence replaces the component mount point with an "Application Error" panel — but this happens only in the browser, after hydration. `curl` sees the shell HTML, returns 200, and has no idea the page is broken.

Specific failure modes that curl cannot detect:

| Failure | curl sees | Browser sees |
|---------|-----------|-------------|
| Missing `evidenceInclude=true` on component | `<div id="..."></div>` | "Application Error: Component is not defined" |
| DuckDB query returning 0 rows (chart empty) | `<div class="chart-container"></div>` | Blank chart area with no data message |
| `ClaimBlock` claim_id not found in view | 200, shell HTML | "No claim found for ID: NMK-D-042" |
| Svelte hydration mismatch (SSR vs client) | Valid HTML | Console hydration warning, partial render |

## Procedure

### Option A: Use the `agent-browser` skill (preferred)

```
/agent-browser <evidence-url>
```

The `agent-browser` skill opens a headless browser, waits for hydration, and returns the post-hydration DOM. Use this when you need programmatic verification.

### Option B: Playwright snapshot

```python
from playwright.sync_api import sync_playwright

def verify_evidence_page(url: str, wait_for_selector: str = ".claim-block") -> dict:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(url, wait_until="networkidle")
        # Wait for Svelte hydration to complete
        page.wait_for_selector(wait_for_selector, timeout=10_000)

        errors = page.locator("text=Application Error").count()
        blank_charts = page.locator(".chart-container:empty").count()
        claim_blocks = page.locator(".claim-block").count()

        browser.close()
        return {
            "url": url,
            "application_errors": errors,
            "blank_charts": blank_charts,
            "claim_blocks_rendered": claim_blocks,
        }

result = verify_evidence_page("http://localhost:3000/reports/q1-analysis")
assert result["application_errors"] == 0, f"Application errors on page: {result}"
assert result["claim_blocks_rendered"] > 0, "No ClaimBlock components rendered"
```

Install Playwright if not present:
```bash
bun add -d playwright
bunx playwright install chromium
```

### Option C: Evidence dev server + manual browser check

```bash
cd viz/<evidence-package>
bun run dev
# → http://localhost:3000
```

Open the page in a browser. Check browser DevTools Console for:

- Red errors starting with `Application Error`
- `Hydration mismatch` warnings (yellow)
- Failed network requests to DuckDB views (404 on `.parquet` files)

### Option D: Check SSR output for known failure markers

This is not a replacement for hydration verification, but can catch some build-time failures:

```bash
# After `evidence build`, check the built HTML for known failure strings
grep -r "Application Error\|evidenceInclude\|undefined" viz/<evidence-package>/build/ 2>/dev/null | grep -v ".map"
```

If this returns matches, the page has a build-time component failure (not just a runtime hydration failure).

### Procedure for CI / post-deploy smoke test

```bash
# 1. Build the Evidence site
cd viz/<evidence-package>
bun run build 2>&1 | tee build.log

# 2. Start the preview server in the background
bun run preview &
SERVER_PID=$!
sleep 3

# 3. Check the index page with curl first (quick sanity)
STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:3000/)
if [ "$STATUS" != "200" ]; then
  echo "FAIL: index page returned $STATUS"
  kill $SERVER_PID; exit 1
fi

# 4. Use Playwright for post-hydration check on key pages
bun run node -e "
const { chromium } = require('playwright');
(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage();
  await page.goto('http://localhost:3000/reports/q1-analysis');
  await page.waitForLoadState('networkidle');
  const errors = await page.locator('text=Application Error').count();
  if (errors > 0) { console.error('FAIL: Application Error on q1-analysis'); process.exit(1); }
  console.log('PASS: q1-analysis rendered cleanly');
  await browser.close();
})();
"

kill $SERVER_PID
```

## Acceptance criteria

- Post-hydration DOM contains 0 `"Application Error"` panels on all key pages.
- All `<ClaimBlock>` mounts resolve to non-empty `.claim-block` elements.
- No blank chart containers (`chart-container:empty`) on pages with chart requirements.
- DuckDB view queries return at least 1 row on non-empty datasets.
- CI smoke test exits 0.

## Common pitfalls

**Using curl as the only verification:** curl returns the SSR shell and always shows 200 for built pages, even when every Svelte component fails to hydrate. Always supplement with a headless browser check.

**Not waiting for `networkidle`:** Evidence loads chart data via async DuckDB queries. `page.goto(url)` alone does not wait for charts to populate. Use `wait_until="networkidle"` or `page.wait_for_selector(".chart-container")`.

**Missing `evidenceInclude = true` in component:** A Svelte component used in Evidence pages must declare `const evidenceInclude = true;` in `<script context="module">`. Without this, Evidence's tree-shaker removes it, causing "Application Error: Component is not defined" in the browser — invisible to curl.

**DuckDB view not registered:** A chart that queries `agent_run.claims_manifest` will be blank if the DuckDB view was not created. Run `bun run build:claim-views` before starting the dev server.

**Playwright not installed:** The Playwright Chromium binary is not installed by default. Run `bunx playwright install chromium` before attempting headless verification.

## Examples

### Quick curl sanity (not sufficient alone)

```bash
curl -s -o /dev/null -w "%{http_code}" http://localhost:3000/reports/q1-analysis
# 200 — but this does NOT confirm components rendered
```

### Full post-hydration check

```python
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page()
    page.goto("http://localhost:3000/reports/q1-analysis", wait_until="networkidle")
    page.wait_for_selector(".claim-block", timeout=8000)
    errors = page.locator("text=Application Error").count()
    print("Application errors:", errors)   # must be 0
    browser.close()
```

## Related skills

- `evidence-page-creation` — create the page that this skill verifies.
- `preflight` — build-time validation (L1-L6); does not catch hydration failures.
- `viz-evidence-authoring` — add `evidenceInclude=true` to component definitions.
