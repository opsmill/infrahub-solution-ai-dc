import {themes as prismThemes} from 'prism-react-renderer';
import type {Config} from '@docusaurus/types';
import type * as Preset from '@docusaurus/preset-classic';

const config: Config = {
  title: 'Infrahub Solution for AI DCs',
  tagline: 'Step by step demo to discover Infrahub',
  favicon: 'img/favicon.ico',

  // Set the production url of your site here
  url: 'https://your-docusaurus-site.example.com',
  // Set the /<baseUrl>/ pathname under which your site is served
  // For GitHub pages deployment, it is often '/<projectName>/'
  baseUrl: '/',

  organizationName: 'opsmill',
  projectName: 'solution-ai-dc',

  onBrokenLinks: 'throw',
  onDuplicateRoutes: "throw",
  markdown: {
    mermaid: true,
    hooks: {
      onBrokenMarkdownLinks: 'warn',
    },
  },
  themes: ['@docusaurus/theme-mermaid'],
  // Even if you don't use internationalization, you can use this field to set
  // useful metadata like html lang. For example, if your site is Chinese, you
  // may want to replace "en" with "zh-Hans".
  i18n: {
    defaultLocale: 'en',
    locales: ['en'],
  },

  presets: [
    [
      "classic",
      {
        docs: {
          // Please change this to your repo.
          // Remove this to remove the "edit this page" links.
          editUrl: "https://github.com/opsmill/solution-ai-dc/tree/main/docs",
          routeBasePath: "/",
          sidebarCollapsed: true,
          sidebarPath: "./sidebars.ts",
        },
        blog: false,
        theme: {
          customCss: "./src/css/custom.css",
        },
      } satisfies Preset.Options,
    ],
  ],

  themeConfig: {
    // announcementBar: {
    //   content: 'Welcome to our brand new docs!',
    //   isCloseable: true,
    // },
    navbar: {
      logo: {
        alt: "Infrahub",
        src: "img/infrahub-hori.svg",
        srcDark: "img/infrahub-hori-dark.svg",
        href: "/",
      },
      items: [
        {
          type: "docSidebar",
          sidebarId: "SolutionAiDcSidebar",
          position: "left",
          label: "Solution AI DC",
        },
        // {
        //   type: "search",
        //   position: "right",
        // },
        {
          href: "https://github.com/opsmill/solution-ai-dc",
          position: "right",
          className: "header-github-link",
          "aria-label": "GitHub repository",
        },
      ],
    },
    footer: {
      copyright: `Copyright © ${new Date().getFullYear()} - <b>Infrahub</b> by OpsMill.`,
    },
    prism: {
      theme: prismThemes.oneDark,
      additionalLanguages: ["bash", "python", "markup-templating", "django", "json", "toml", "yaml"],
    },
  } satisfies Preset.ThemeConfig,
};

export default config;
