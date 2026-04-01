import type { SidebarsConfig } from '@docusaurus/plugin-content-docs';

const sidebars: SidebarsConfig = {
  solutionAiDcSidebar: [
    {
      type: 'category',
      label: 'Infrahub AI/DC Solution',
      link: {
        type: 'doc',
        id: 'overview',
      },
      items: [
        'installation-setup',
        'design-driven-automation',
        'demo-guide',
        'modular-generator-architecture',
        'generator-patterns',
      ],
    },
  ],
};

export default sidebars;
