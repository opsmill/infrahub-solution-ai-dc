import type { SidebarsConfig } from '@docusaurus/plugin-content-docs';

const sidebars: SidebarsConfig = {
  solutionAiDcSidebar: [
    {
      type: 'category',
      label: 'Infrahub AI/DC Solution',
      link: {
        type: 'doc',
        id: 'solution-ai-dc/overview',
      },
      items: [
        'solution-ai-dc/installation-setup',
        'solution-ai-dc/design-driven-automation',
        'solution-ai-dc/demo-guide',
        'solution-ai-dc/modular-generator-architecture',
        'solution-ai-dc/generator-patterns',
      ],
    },
  ],
};

export default sidebars;
