import type {
  AgentDetail,
  ChatMessage,
  ManagementCard,
  TeamDetail,
  WorkflowDetail,
  WorkerSummary
} from '../types';

export const workers: WorkerSummary[] = [
  {
    id: 'code-agent-1',
    name: 'Code Agent',
    type: 'Agent',
    description: 'Handles coding and debugging tasks',
    status: 'Ready',
    recent: 'Last session: frontend layout prototype'
  },
  {
    id: 'review-agent-1',
    name: 'Review Agent',
    type: 'Agent',
    description: 'Reviews code and suggests improvements',
    status: 'Ready',
    recent: 'Last session: PR review feedback'
  },
  {
    id: 'product-rd-team-1',
    name: 'Product R&D Team',
    type: 'Team',
    description: 'Coordinates planning, implementation, architecture review, and research',
    status: '5 members',
    recent: 'Last session: delivery planning review'
  },
  {
    id: 'pr-workflow-1',
    name: 'PR Workflow',
    type: 'Workflow',
    description: 'Spec -> prototype -> review -> ship',
    status: '4 stages',
    recent: 'Last run: yesterday'
  }
];

export const agentDetails: AgentDetail[] = [
  {
    id: 'code-agent-1',
    name: 'Code Agent',
    description: 'Handles implementation and debugging tasks.',
    workspaces: [
      { path: 'D:\\work\\frontend', permission: 'read-write' },
      { path: 'D:\\docs', permission: 'read' }
    ],
    knowledge: ['Product Docs', 'Support Cases'],
    model: { provider: 'OpenAI Compatible', model: 'gpt-4.1', temperature: 0.2 }
  },
  {
    id: 'review-agent-1',
    name: 'Review Agent',
    description: 'Reviews code and suggests improvements.',
    workspaces: [
      { path: 'D:\\work\\frontend', permission: 'read' }
    ],
    knowledge: ['Product Docs'],
    model: { provider: 'Qwen', model: 'qwen-max', temperature: 0.3 }
  }
];

export const teamDetails: TeamDetail[] = [
  {
    id: 'product-rd-team-1',
    name: 'Product R&D Team',
    description: 'Coordinates planning, implementation, architecture review, and research.',
    members: [
      { agentId: 'code-agent-1', agentName: 'Code Agent', inheritTeamWorkspace: true, role: 'Developer' },
      { agentId: 'review-agent-1', agentName: 'Review Agent', inheritTeamWorkspace: false, role: 'Reviewer' }
    ],
    teamWorkspaces: [
      { path: 'D:\\release\\staging', permission: 'read-write' }
    ],
    teamKnowledge: ['Product Docs'],
    model: { provider: 'OpenAI Compatible', model: 'gpt-4.1', temperature: 0.2 }
  }
];

export const workflowDetails: WorkflowDetail[] = [
  {
    id: 'pr-workflow-1',
    name: 'PR Workflow',
    description: 'Spec -> prototype -> review -> ship.',
    nodes: ['Spec', 'Prototype', 'Review', 'Ship'],
    trigger: 'Manual launch',
    outputs: ['Spec', 'UI prototype', 'QA summary']
  }
];

export const chatMessages: ChatMessage[] = [
  { id: 'm1', role: 'system', content: 'Session created', meta: '09:20' },
  { id: 'm2', role: 'user', content: 'Please build a multi-page prototype first.', meta: '09:21' },
  {
    id: 'm3',
    role: 'worker',
    content: 'I will start with the chat page and the management page frames, then refine the details.',
    meta: '09:21'
  }
];

export const managementCards: Record<string, ManagementCard[]> = {
  Skills: [
    { title: 'filesystem-skill', description: 'Local file browsing skill bundle', meta: '3 files' },
    { title: 'release-skill', description: 'Release checklist and packaging notes', meta: '2 files' }
  ],
  Extensions: [
    { title: 'Git Helper', description: 'Surface git operations in the UI', meta: 'Enabled' },
    { title: 'Web Search', description: 'Connect web search providers', meta: 'Disabled' }
  ],
  MCP: [
    { title: 'Context7', description: 'Library documentation server', meta: 'Connected' },
    { title: 'Playwright', description: 'Browser automation service', meta: 'Idle' }
  ],
  Knowledge: [
    { title: 'Product Docs', description: 'D:\\docs\\product', meta: 'Indexed 126 files' },
    { title: 'Support Cases', description: 'D:\\kb\\support', meta: 'Pending scan' }
  ],
  Models: [
    { title: 'OpenAI Compatible', description: 'vLLM / sglang / custom base URL', meta: '4 endpoints' },
    { title: 'Qwen', description: 'Dedicated provider credentials', meta: '2 models' }
  ],
  Settings: [
    { title: 'Appearance', description: 'Theme, density, language', meta: 'Modern / zh-CN' },
    { title: 'Storage Paths', description: 'Config path and db path', meta: 'Custom' }
  ]
};
