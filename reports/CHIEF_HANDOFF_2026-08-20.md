# Chief Handoff — AI Agent Production Acceptance

Date: 2026-08-20  
Repository: `/workspace/scratch/83859ab3650c/repos/ai-agent-production-acceptance`  
State: planning and public framing complete; no experiment run started

## 1. Chief's assignment

Take over Phase 0 execution for a public AI Agent acceptance-system experiment.

The project is time-sensitive. The goal is to publish an early, concrete and reproducible method before institutional approaches fully consolidate. It is not a startup validation exercise and does not require customer discovery.

The preferred upside is that the work demonstrates the author's ability to identify and define an emerging product problem and leads to recruitment by a leading model company, Agent company, or enterprise-AI product/strategy team.

## 2. Core thesis

Primary claim to investigate:

> The first problem for many enterprises deploying Agents is not knowing which Agent is strongest, but not knowing what should be accepted and tested in the first place.

Capability signal hierarchy:

1. Primary: identify and define a product problem before consensus forms.
2. Evidence: translate an ambiguous enterprise task into an executable acceptance system.
3. Method: organize a rigorous and reproducible public experiment.

## 3. Non-negotiable scope boundaries

This project does:

- delivery and pre-deployment acceptance;
- frozen acceptance specifications;
- evidence capture;
- delivery-health profiles;
- blocking-defect diagnosis;
- conditional acceptance verdicts;
- public, reproducible cases.

This project does not:

- rank Agents or publish an overall leaderboard;
- crown a winning system;
- evaluate foundation models as if they were enterprise products;
- provide certification, warranty or a `Production Ready` claim;
- build continuous production monitoring;
- operate or manage Agents on behalf of enterprises;
- validate a commercial business model in Phase 0;
- compete directly with standards or certification institutions.

Continuous health monitoring is explicitly out of scope. It would require a separate system and would move the work toward managed operations.

Multiple Agent systems are calibration samples for the acceptance framework. They are not competitors in a benchmark tournament.

## 4. Public-positioning logic

The project identity remains a general Agent acceptance framework. “Public experiment” describes the current validation environment and distribution path, not the ultimate subject of the project.

The project cannot outspend or out-authorize NIST, BSI, the EU standards ecosystem, MIIT, CAICT or established testing institutions. Its possible advantage is:

- earlier problem definition;
- faster publication;
- operational specificity;
- an inspectable worked example;
- open reuse and criticism;
- a dated record of independent judgment.

Institutional signals already found:

- NIST launched an AI Agent Standards Initiative in February 2026:  
  https://www.nist.gov/news-events/news/2026/02/announcing-ai-agent-standards-initiative-interoperable-and-secure
- NIST CAISI and GSA are developing evaluation methods for performance, security and functionality in real federal user workflows:  
  https://www.nist.gov/news-events/news/2026/03/caisi-signs-mou-gsa-boost-ai-evaluation-science-federal-procurement-through
- The EU AI Act is converging on conformity assessment, risk management, logs, documentation, human oversight, accuracy, robustness and cybersecurity:  
  https://digital-strategy.ec.europa.eu/en/policies/regulatory-framework-ai
- EU harmonized standards remain under development:  
  https://digital-strategy.ec.europa.eu/en/policies/ai-act-standardisation
- MIIT solicited a 2026 standards project for `人工智能 产品服务 搜索智能体能力技术要求`:  
  https://www.miit.gov.cn/jgsj/kjs/jscx/bzgf/art/2026/art_98230cfc25a6417fad5512136d21bef2.html
- MIIT also solicited `办公智能体应用接口规范`:  
  https://www.miit.gov.cn/jgsj/kjs/jscx/bzgf/art/2026/art_5450afc3d84b44c18272afaf6270de07.html

Interpretation: the trend is real, but `Agent Acceptance Specification` is not yet a mature unified category. The public opportunity is to make the requirements-to-evidence layer concrete before terminology and institutional ownership harden.

## 5. Phase 0 objective

Phase 0 must test whether a frozen acceptance framework can identify:

- blocking defects;
- required human rework;
- decision-support candidates;
- information that conventional report-quality scores alone do not express.

Allowed verdicts:

- `Blocked`;
- `Human rework required`;
- `Decision-support candidate`.

Forbidden Phase 0 verdict:

- `Production Ready`.

Strongest intended publication claim:

> On one benchmark-derived industrial decision task, the proposed acceptance framework identified evidence-backed blocking defects, human-rework needs and decision-support candidates that conventional report-quality scores alone did not express.

## 6. Case 001

Vertical: Deep Research Agents.

Task source: DeepResearch Bench, Task 86, Industrial.

Frozen official task:

> Conduct a research report on the manufacturing technology options for hollow motor shafts used in New Energy Vehicle (NEV) electric drive units. List all current forming techniques, compare them based on criteria such as suitable materials, cost-effectiveness, required subsequent processing steps, and other relevant factors. Finally, identify the most suitable manufacturing routes for this specific application.

Source:

https://github.com/Ayanami0730/deep_research_bench/blob/main/data/prompt_data/query.jsonl

Why it was selected:

- traditional industrial decision rather than an AI-native demo;
- requires inventory, comparison and recommendation;
- produces a preserved, auditable artifact;
- inherits a public benchmark task rather than a favorable custom prompt;
- can be run at low cost without production-system access.

Claim limitation: Case 001 tests Agent-deliverable acceptance. It cannot validate a complete general Agent health system because it does not exercise production authorization, live side effects, human handoff, long-run stability or drift.

## 7. Frozen systems and run design

### D1 — GPT Researcher

- Repository: https://github.com/assafelovic/gpt-researcher
- Commit: `5d84d2f5553e70a2765a8ff3a0d2672d60437ce8`
- Default fast model: `openai:gpt-5.4-mini`
- Default smart/strategic model: `openai:gpt-5.4`
- Default retriever: Tavily

### D2 — Open Deep Research

- Repository: https://github.com/langchain-ai/open_deep_research
- Commit: `1b7d2e80db9faa586165c60e09096dbbfd483a64`
- Default summarization model: `openai:gpt-4.1-mini`
- Default research/compression/report model: `openai:gpt-4.1`
- Default search: Tavily

### D3 — dzhng/deep-research

- Repository: https://github.com/dzhng/deep-research
- Commit: `1f8f3e285bbc23e80b98a66a64effab9069f3ad4`
- Default model: `o3-mini`, medium reasoning
- Default search/extraction: Firecrawl
- Default exploration: breadth 4, depth 2

Reserve: Tongyi DeepResearch. Do not add it to the required run under the CNY 100 cap.

Conditional same-model controls, only after all required default runs and only if budget permits:

- GPT Researcher with all LLM roles set to `gpt-5.4-mini-2026-03-17`;
- dzhng/deep-research with `gpt-5.4-mini-2026-03-17`.

## 8. Budget and run rules

Total hard ceiling: CNY 100.

- CNY 60: D1–D3 required default runs;
- CNY 20: evaluation and citation checks;
- CNY 15: same-model controls;
- CNY 5: transient-failure reserve.

Rules:

- record measured usage after every run;
- do not silently reduce default depth, breadth or iteration limits;
- do not improve prompts after seeing output;
- do not inject sources manually;
- do not edit generated reports;
- do not rerun merely because a result looks weak;
- one retry is allowed only for a clearly transient provider/network failure;
- drop both same-model controls if the shared control budget is insufficient.

## 9. Acceptance architecture

Inherited research layer:

- DeepResearch Bench RACE-style report assessment;
- FACT-style citation completeness/correctness;
- DeepResearch Bench II only as a rubric-design reference unless its matching official pipeline is actually run.

Production-acceptance profile:

1. requirement fulfilment;
2. evidence traceability;
3. analytical synthesis;
4. decision usability;
5. risk and uncertainty;
6. operational efficiency.

Blocking defects override high dimension scores.

Severity:

- `B0 Critical`: invalidates the run as a decision artifact;
- `B1 Major`: substantial analyst rework required;
- `B2 Minor`: local defect that does not change the main decision.

Every B0/B1 finding must cite an exact output passage and the relevant source or run evidence.

## 10. Existing repository artifacts

- `README.md` — Phase 0 thesis, boundaries, landscape and candidate set.
- `docs/PHASE0_EXPERIMENT_DESIGN_V0_1.md` — frozen task, systems, budget, protocol and verdict language.
- `docs/PUBLIC_EXPERIMENT_CHARTER_V0_1.md` — explicit public/non-leaderboard charter.
- `reports/BILINGUAL_REPORT_SKELETON_V0_1.md` — Chinese/English report structure.
- `.gitignore` — secret and local-environment exclusions.

Recent corrections already applied:

- replaced ranking language with independent health/acceptance summaries;
- clarified that multiple systems calibrate the framework;
- made commercialization explicitly non-required for Phase 0;
- removed winner-oriented threshold wording;
- reframed the first report around blocking defects and rework conditions.

## 11. Current execution state

No experiment has run.

No API cost has been incurred.

No candidate repository has been cloned into the project.

No dependency has been installed for candidate systems.

No commit or push has been made in the local project repository. Current project files are untracked.

Preflight environment observed:

- Python `3.12.13`;
- Node `v24.19.0`;
- npm `11.9.0`;
- git `2.51.1`.

Missing environment variables at handoff:

- `OPENAI_API_KEY`;
- `TAVILY_API_KEY`;
- `FIRECRAWL_API_KEY` / `FIRECRAWL_KEY`.

A read-only `git ls-remote` check against GPT Researcher completed with exit code 0, but nothing was cloned.

Never print or commit secret values. Credentials must be supplied through an approved local secret mechanism before paid runs.

## 12. Chief execution order

1. Read the four existing project documents completely.
2. Preserve the non-leaderboard, acceptance-only boundary.
3. Create the machine-readable Case 001 acceptance specification before seeing any system output.
4. Create evidence directories, run manifests and cost ledgers.
5. Resolve credentials securely; stop rather than substituting unapproved providers or models.
6. Clone and pin D1–D3 at the frozen commits.
7. Install and smoke-test without scored task runs; record every compatibility patch.
8. Execute D1–D3 in the frozen order under the hard budget.
9. Preserve raw outputs and run evidence without edits.
10. Blind system identity during first-pass human acceptance scoring.
11. Produce three independent health/acceptance summaries; do not calculate an overall rank.
12. Publish the method, case, raw evidence, limitations and bilingual report only after citation and claim-boundary review.

## 13. Missing artifacts Chief should create

Suggested minimum structure:

```text
framework/
  AGENT_ACCEPTANCE_SPEC_V0_1.md
  ACCEPTANCE_SPEC_TEMPLATE.yaml
  BLOCKING_DEFECTS.md
cases/
  case-001-deep-research/
    business-requirement.md
    acceptance-spec.yaml
    run-manifest.yaml
    test-scenarios.md
    cost-ledger.csv
    evidence/
    verdicts/
```

The exact public author name/byline, repository license and citation metadata are not yet frozen. Because recruitment is the preferred outcome, Chief must preserve visible, user-approved authorship and add citation metadata before publication. Ask once before publishing if the public identity is still unresolved.

## 14. Stop conditions

Stop and report rather than improvise if:

- the frozen commit cannot be executed without material behavior changes;
- a required provider credential is unavailable;
- projected cost would exceed the predeclared cap;
- the benchmark evaluator cannot be run as documented;
- a proposed claim exceeds the evidence;
- publication would expose secrets, private data or unapproved personal identity.

Do not restart product-positioning discovery. The project thesis and Phase 0 boundary are sufficiently defined; the next work is experimental execution.
