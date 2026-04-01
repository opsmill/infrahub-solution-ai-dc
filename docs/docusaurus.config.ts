import {themes as prismThemes} from 'prism-react-renderer';
import type {Config} from '@docusaurus/types';
import type * as Preset from '@docusaurus/preset-classic';

const config: Config = {
  title: 'AI/DC Solution for Infrahub',
  tagline: 'Design-driven automation for AI data center fabrics',
  favicon: 'img/favicon.ico',

  url: 'https://docs.infrahub.app',
  baseUrl: '/',

  organizationName: 'opsmill',
  projectName: 'infrahub-solution-ai-dc',
  onBrokenLinks: 'throw',
  onDuplicateRoutes: 'throw',

  i18n: {
    defaultLocale: 'en',
    locales: ['en'],
  },

  presets: [
    [
      'classic',
      {
        docs: {
          editUrl: 'https://github.com/opsmill/infrahub-solution-ai-dc/tree/stable/docs',
          path: 'docs/solution-ai-dc',
          routeBasePath: 'solution-ai-dc',
          sidebarPath: './sidebars/sidebars-solution-ai-dc.ts',
          sidebarCollapsed: true,
        },
        blog: false,
        theme: {
          customCss: './src/css/custom.css',
        },
      } satisfies Preset.Options,
    ],
  ],

  themes: ['@docusaurus/theme-mermaid'],

  themeConfig: {
    navbar: {
      logo: {
        alt: 'Infrahub',
        src: 'img/infrahub-hori.svg',
        srcDark: 'img/infrahub-hori-dark.svg',
        href: '/solution-ai-dc/overview',
      },
      items: [
        {
          type: 'docSidebar',
          sidebarId: 'solutionAiDcSidebar',
          label: 'AI/DC Solution',
        },
        {
          href: 'https://github.com/opsmill/infrahub-solution-ai-dc',
          position: 'right',
          className: 'header-github-link',
          'aria-label': 'GitHub repository',
        },
      ],
    },
    footer: {
      copyright: `Copyright © ${new Date().getFullYear()} - <b>Infrahub</b> by OpsMill.`,
    },
    prism: {
      theme: prismThemes.oneDark,
      additionalLanguages: ['bash', 'python', 'json', 'toml', 'yaml'],
    },
  } satisfies Preset.ThemeConfig,

  markdown: {
    format: 'mdx',
    mermaid: true,
    hooks: {
      onBrokenMarkdownLinks: 'warn',
    },
  },
};

export default config;
