// @ts-check
import { defineConfig } from "astro/config";
import starlight from "@astrojs/starlight";
import starlightCopyButton from "starlight-copy-button";
import starlightKbd from "starlight-kbd";

// https://astro.build/config
export default defineConfig({
  site: "https://supercompute.dev",
  integrations: [
    starlight({
      title: "Supercompute",
      plugins: [
        starlightCopyButton(),
        starlightKbd({
          globalPicker: false,
          types: [
            { id: "mac", label: "macOS", detector: "apple", default: true },
            { id: "windows", label: "Windows", detector: "windows" },
          ],
        }),
      ],
      components: {
        Hero: "./src/components/Hero.astro",
      },
      social: [{ icon: "github", label: "GitHub", href: "https://github.com/stackific/supercompute" }],
      sidebar: [
        {
          label: "Start Here",
          items: [
            { label: "Get started locally", slug: "start-here/get-started" },
            { label: "Get started locally with a roaming node", slug: "start-here/get-started-roaming-node" },
            { label: "Deploy to production", slug: "start-here/deploy-to-production" },
            { label: "Deploy with GitHub Actions", slug: "start-here/deploy-with-github-actions" },
          ],
        },
        {
          label: "Guides",
          items: [
            { label: "Adding a public node", slug: "guides/adding-public-node" },
            { label: "Adding a roaming node", slug: "guides/adding-roaming-node" },
          ],
        },
        {
          label: "Reference",
          items: [{ label: "Task commands", slug: "reference/task" }],
        },
      ],
    }),
  ],
});
