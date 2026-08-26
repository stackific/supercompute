# How to deploy on Cloudflare Pages

Starlight site under `docs/` (Bun + `astro build` → `dist`). Operator runbooks are in **`../internal/`** at the worktree root.

## Pages build settings

| Setting                | Value                                            |
| ---------------------- | ------------------------------------------------ |
| Root directory         | `docs`                                           |
| Build command          | `bun install --frozen-lockfile && bun run build` |
| Build output directory | `dist`                                           |

Chain `bun install` in the build command: Pages may otherwise install with npm even when `bun.lock` is present.

## Build-time environment variables

Set these under **Settings → Environment variables** for the **Build** environment ([Build image](https://developers.cloudflare.com/pages/configuration/build-image/)):

| Variable                  | Value                                    | Purpose                                                                                                |
| ------------------------- | ---------------------------------------- | ------------------------------------------------------------------------------------------------------ |
| `BUN_VERSION`             | e.g. `1.2.15` (or pin to your local Bun) | Selects the Bun runtime on the Pages build image (v3 default is `1.2.15`).                             |
| `SKIP_DEPENDENCY_INSTALL` | `true`                                   | Disables Pages’ automatic dependency install so the build command’s `bun install` owns `node_modules`. |

Sources: [Build image](https://developers.cloudflare.com/pages/configuration/build-image/) (`BUN_VERSION`, `SKIP_DEPENDENCY_INSTALL`); [Build configuration](https://developers.cloudflare.com/pages/configuration/build-configuration/) / [Deploy an Astro site](https://developers.cloudflare.com/pages/framework-guides/deploy-an-astro-site/) (Astro → `dist`).
