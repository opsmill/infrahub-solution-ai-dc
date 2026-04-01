import React from 'react';
import ComponentCreator from '@docusaurus/ComponentCreator';

export default [
  {
    path: '/solution-ai-dc',
    component: ComponentCreator('/solution-ai-dc', '5f2'),
    routes: [
      {
        path: '/solution-ai-dc',
        component: ComponentCreator('/solution-ai-dc', '740'),
        routes: [
          {
            path: '/solution-ai-dc',
            component: ComponentCreator('/solution-ai-dc', '2bf'),
            routes: [
              {
                path: '/solution-ai-dc/demo-guide',
                component: ComponentCreator('/solution-ai-dc/demo-guide', '6e2'),
                exact: true,
                sidebar: "solutionAiDcSidebar"
              },
              {
                path: '/solution-ai-dc/design-driven-automation',
                component: ComponentCreator('/solution-ai-dc/design-driven-automation', '511'),
                exact: true,
                sidebar: "solutionAiDcSidebar"
              },
              {
                path: '/solution-ai-dc/generator-patterns',
                component: ComponentCreator('/solution-ai-dc/generator-patterns', '6e2'),
                exact: true,
                sidebar: "solutionAiDcSidebar"
              },
              {
                path: '/solution-ai-dc/installation-setup',
                component: ComponentCreator('/solution-ai-dc/installation-setup', '33f'),
                exact: true,
                sidebar: "solutionAiDcSidebar"
              },
              {
                path: '/solution-ai-dc/modular-generator-architecture',
                component: ComponentCreator('/solution-ai-dc/modular-generator-architecture', 'e50'),
                exact: true,
                sidebar: "solutionAiDcSidebar"
              },
              {
                path: '/solution-ai-dc/overview',
                component: ComponentCreator('/solution-ai-dc/overview', 'ffb'),
                exact: true,
                sidebar: "solutionAiDcSidebar"
              }
            ]
          }
        ]
      }
    ]
  },
  {
    path: '*',
    component: ComponentCreator('*'),
  },
];
