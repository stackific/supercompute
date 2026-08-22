# Public docs site (`docs/`)

The Starlight site in `docs/` is separate from operator runbooks in **`internal/`**.

## Local preview

```sh
cd docs
bun install
bun run dev
```

Default URL: `http://localhost:4321/`

## Cloudflare Pages

| Setting | Value |
| --- | --- |
| Root directory | `docs` |
| Build command | `bun install --frozen-lockfile && bun run build` |
| Build output | `dist` |

Build-time environment variables ([Build image](https://developers.cloudflare.com/pages/configuration/build-image/)):

| Variable | Value | Purpose |
| --- | --- | --- |
| `BUN_VERSION` | e.g. `1.2.15` | Pin Bun on the build image |
| `SKIP_DEPENDENCY_INSTALL` | `true` | Skip Pages auto-install; use build command’s `bun install` |

No `@astrojs/cloudflare` adapter is configured; static `dist` output is sufficient until SSR is needed.

## Content vs internal runbooks

Starlight content lives under `docs/src/content/docs/`. Operator runbooks and reference material live under **`internal/`** at the worktree root. Link to repository paths from Starlight pages when needed; do not assume runbooks are published on the website unless explicitly added to Starlight.
