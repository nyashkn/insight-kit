# insight-kit Evidence Components

These are [Evidence](https://evidence.dev) (Svelte) components for visualising
insight-kit claims in downstream Evidence reports.

## Components

| File | Purpose |
|------|---------|
| `ClaimBlock.svelte` | Full-width claim card with statement, value, confidence badge, caveats and supersedes chain |
| `ClaimInline.svelte` | Inline citation chip — renders `[[CITE: ID]]`-style references in prose |
| `ClaimDelta.svelte` | Delta/diff view comparing two claims in a supersedes chain |
| `claimsManifest.js` | JS helper that loads and indexes claims from a `claims.jsonl` file |

## Usage in downstream Evidence projects

```js
// In your Evidence page (e.g. +page.md)
import ClaimBlock from '$lib/ClaimBlock.svelte';
```

Or use the Python helper to locate and symlink the component directory:

```python
from insight_kit.assets import components_dir
import shutil, pathlib

dest = pathlib.Path("reports/components")
shutil.copytree(components_dir(), dest, dirs_exist_ok=True)
```
