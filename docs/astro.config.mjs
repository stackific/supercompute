// @ts-check
import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';
import starlightCopyButton from 'starlight-copy-button';

// https://astro.build/config
export default defineConfig({
	integrations: [
		starlight({
			title: 'Supercompute',
			plugins: [starlightCopyButton()],
			components: {
				Hero: './src/components/Hero.astro',
			},
			social: [{ icon: 'github', label: 'GitHub', href: 'https://github.com/stackific/supercompute' }],
			sidebar: [
				{
					label: 'Start Here',
					items: [
						{ label: 'Get started locally', slug: 'start-here/get-started' },
						{ label: 'Deploy to production', slug: 'start-here/deploy-to-production' },
					],
				},
				{
					label: 'Guides',
					items: [{ label: 'Adding a public node', slug: 'guides/adding-public-node' }],
				},
				{
					label: 'Reference',
					items: [{ autogenerate: { directory: 'reference' } }],
				},
			],
		}),
	],
});
