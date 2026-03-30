import type { SidebarsConfig } from '@docusaurus/plugin-content-docs';

const sidebars: SidebarsConfig = {
  solutionAiDcSidebar: [
    {
      type: 'category',
      label: 'AI/DC Solution',
      link: {
        type: 'doc',
        id: 'overview',
      },
      items: [
        'installation-setup',
        'demo-guide',
        'design-driven-automation',
        'modular-generator-architecture',
        'generator-patterns',
      ],
    },
  ],
};

export default sidebars;
