export interface ScaledPrompt {
  id: string
  title: string
  category: 'Coding' | 'Reasoning' | 'Product' | 'Systems' | 'Creative'
  description: string
  tags: string[]
  template: string
  parameters?: Array<{ key: string; label: string; placeholder: string; defaultValue?: string }>
}

export const SCALED_PROMPTS: ScaledPrompt[] = [
  {
    id: 'artifact-master',
    title: 'Claude Artifact Application Master',
    category: 'Coding',
    description: 'Generates self-contained, interactive web apps and dashboards ready for instant split-screen preview.',
    tags: ['Artifacts', 'Frontend', 'Tailwind', 'Interactive'],
    parameters: [
      { key: 'APP_DESCRIPTION', label: 'App Concept', placeholder: 'e.g. A real-time crypto portfolio tracker with charts' },
      { key: 'TECH_STACK', label: 'Tech Stack', placeholder: 'HTML5, Tailwind CDN, Lucide Icons, Canvas' },
    ],
    template: `You are an elite Frontend Architect and UI Master. Build a fully functional, highly polished, self-contained interactive web application for:
{{APP_DESCRIPTION}}

Constraints & Quality Standards:
1. Deliver the entire application as a single self-contained deliverable code block using {{TECH_STACK}}.
2. Include the Tailwind CSS CDN (<script src="https://cdn.tailwindcss.com"></script>) and FontAwesome/Lucide icons.
3. Ensure fluid responsive behavior across Desktop, Tablet, and Mobile views.
4. Implement realistic interactive states: form inputs, live calculations, filtering, tab navigation, and responsive modals.
5. Provide a sleek obsidian/dark aesthetic with subtle glowing accents and micro-animations.`,
  },
  {
    id: 'deep-thinking-reasoner',
    title: 'Extended Analytical Thinking & Synthesis',
    category: 'Reasoning',
    description: 'Enforces rigorous Claude 3.7-grade extended thinking, first-principles logic, and structured proofs.',
    tags: ['Thinking', 'Logic', 'First-Principles', 'Analysis'],
    parameters: [
      { key: 'PROBLEM_STATEMENT', label: 'Problem or Query', placeholder: 'Describe the complex decision or challenge' },
      { key: 'CONSTRAINTS', label: 'Key Constraints', placeholder: 'e.g. Budget, latency < 50ms, backward compatibility' },
    ],
    template: `Perform an exhaustive, first-principles analysis on the following problem:
{{PROBLEM_STATEMENT}}

Constraints & Context:
{{CONSTRAINTS}}

Execution Protocol:
1. Internal Reasoning & Exploration:
   - Break down core assumptions and identify potential points of failure or hidden trade-offs.
   - Formulate at least 3 distinct conceptual approaches with trade-off matrices.
2. Structured Synthesis:
   - Present the mathematically or logically superior recommendation.
   - Include concrete proofs, algorithmic complexity analysis (time & space), and edge-case guardrails.
   - Conclude with a battle-tested step-by-step roadmap for execution.`,
  },
  {
    id: 'fullstack-deep-module',
    title: 'Deep Module & High-Cohesion Architect',
    category: 'Coding',
    description: 'Designs deep modules with minimal interfaces, hidden complexity, and testable seams.',
    tags: ['Architecture', 'Clean Code', 'Modular', 'Backend'],
    parameters: [
      { key: 'MODULE_GOAL', label: 'Module Goal', placeholder: 'e.g. High-throughput distributed rate limiter' },
      { key: 'LANGUAGE_FRAMEWORK', label: 'Framework & Lang', placeholder: 'e.g. TypeScript / Node.js or Python / FastAPI' },
    ],
    template: `Act as a Principal Software Engineer specializing in Deep Module Design (Ousterhout philosophy).
Design and implement the module for:
{{MODULE_GOAL}}

Target Stack: {{LANGUAGE_FRAMEWORK}}

Architecture Guidelines:
1. Deep Interface: The public API must be radically simple and concise, hiding substantial internal complexity.
2. Zero Leaky Abstractions: Internal state machines, caching, and serialization nuances must stay internal.
3. Error Boundaries: Define explicit, typed failure modes rather than bubbling raw runtime exceptions.
4. Provide production-grade, type-safe implementation code followed by comprehensive unit tests.`,
  },
  {
    id: 'tdd-verification',
    title: 'TDD Red-Green-Refactor Specialist',
    category: 'Coding',
    description: 'Guides strict Test-Driven Development with edge-case invariant testing before implementation.',
    tags: ['TDD', 'Testing', 'Unit Tests', 'Quality'],
    parameters: [
      { key: 'FEATURE_SPEC', label: 'Feature Spec', placeholder: 'e.g. Token bucket rate limiter with sliding window' },
      { key: 'TEST_RUNNER', label: 'Test Framework', placeholder: 'e.g. Jest, Vitest, Pytest' },
    ],
    template: `Execute a rigorous Test-Driven Development (TDD) workflow for:
{{FEATURE_SPEC}}
Testing Engine: {{TEST_RUNNER}}

Phases:
1. RED: Write exhaustive test suites covering:
   - Happy path behaviors and invariants
   - Boundary conditions (empty inputs, maximum limits, off-by-one errors)
   - Concurrency, error handling, and timeout scenarios
2. GREEN: Implement the minimal, clean code required to pass all tests.
3. REFACTOR: Eliminate redundancy, enhance readability, and benchmark performance.`,
  },
  {
    id: 'bug-forensics',
    title: 'Root Cause & Crash Forensics Investigator',
    category: 'Reasoning',
    description: 'Diagnoses complex race conditions, memory leaks, and mysterious production exceptions.',
    tags: ['Debugging', 'RCA', 'Forensics', 'Production'],
    parameters: [
      { key: 'ERROR_LOGS', label: 'Error / Stack Trace', placeholder: 'Paste error message or unexpected behavior' },
      { key: 'REPRODUCTION_STEPS', label: 'Reproduction', placeholder: 'How and when does this happen?' },
    ],
    template: `Investigate and resolve the following production defect with forensic precision:

Observed Error / Stack Trace:
{{ERROR_LOGS}}

Reproduction Context:
{{REPRODUCTION_STEPS}}

Diagnostic Procedure:
1. Differential Diagnosis: List the top 3 plausible root causes ranked by likelihood.
2. Causal Chain: Trace the execution flow from the initial trigger to the point of failure.
3. Proof & Verification: Explain how to deterministically verify the hypothesis.
4. Minimal Surgical Fix: Provide the exact code diff that eliminates the bug without side effects.
5. Regression Prevention: Provide an automated test case that reliably fails before the fix and passes after.`,
  },
  {
    id: 'executive-prd-author',
    title: 'Executive PRD & Technical Spec Engineer',
    category: 'Product',
    description: 'Authors high-impact Product Requirement Documents with user journeys and technical seams.',
    tags: ['PRD', 'Product', 'Specs', 'Strategy'],
    parameters: [
      { key: 'PRODUCT_VISION', label: 'Product Vision', placeholder: 'e.g. Collaborative AI code reviewer for pull requests' },
      { key: 'TARGET_AUDIENCE', label: 'Audience', placeholder: 'Engineering teams, CTOs, open-source maintainers' },
    ],
    template: `Draft an executive-grade Product Requirement Document (PRD) and Technical Specification for:
{{PRODUCT_VISION}}

Audience: {{TARGET_AUDIENCE}}

Structure:
1. Executive Summary & Problem Validation
2. Core User Personas & Detailed User Journeys
3. Functional Requirements (P0, P1, P2 prioritization)
4. Non-Functional Requirements (Latency, Security, Availability, WCAG Accessibility)
5. Architecture Blueprint & Entity Relationships
6. Launch Metrics & Key Performance Indicators (KPIs)`,
  },
  {
    id: 'katex-scientific-synthesizer',
    title: 'KaTeX Mathematical & Scientific Synthesizer',
    category: 'Reasoning',
    description: 'Formulates multi-term KaTeX formulas, statistical proofs, and rigorous formal derivations.',
    tags: ['Math', 'KaTeX', 'LaTeX', 'Science'],
    parameters: [
      { key: 'MATH_TOPIC', label: 'Topic / Derivation', placeholder: 'e.g. Bayesian parameter estimation or Transformer attention mechanism' },
    ],
    template: `Provide a rigorous mathematical formulation and derivation for:
{{MATH_TOPIC}}

Formatting Standards:
- Use KaTeX math blocks: display math with $$ ... $$ on separate lines, and inline math with $ ... $.
- Define every variable and parameter upon first appearance.
- Detail the foundational equations, intermediate algebraic steps, and final closed-form expression.
- Provide a concise Python/NumPy reference implementation demonstrating the math in action.`,
  },
  {
    id: 'security-pentester',
    title: 'Zero-Trust Security & Threat Modeler',
    category: 'Systems',
    description: 'Audits systems against OWASP Top 10, privilege escalation, and auth vulnerabilities.',
    tags: ['Security', 'Auth', 'Pen-Testing', 'OWASP'],
    parameters: [
      { key: 'SYSTEM_DETAILS', label: 'System / API Spec', placeholder: 'e.g. JWT-based multi-tenant SaaS API' },
    ],
    template: `Perform a comprehensive Threat Model and Security Review for:
{{SYSTEM_DETAILS}}

Audit Methodology (STRIDE & OWASP):
1. Attack Surface Enumeration: Entry points, external boundaries, and authorization checkpoints.
2. Threat Scenarios:
   - Broken Object Level Authorization (BOLA / IDOR)
   - Token forgery, replay attacks, and session fixation
   - Injection vulnerabilities (SQLi, command injection, SSRF)
3. Hardening Blueprint: Concrete code fixes, secure header policies, and rate-limiting guardrails.`,
  },
]
