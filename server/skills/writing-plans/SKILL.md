---
name: writing-plans
description: "Use when you have a spec or requirements for a multi-step task, before touching code. Write bite-sized implementation plans."
---

# Writing Implementation Plans

Write comprehensive implementation plans before coding multi-step tasks.

## Plan Structure

Every plan must have:
1. **Goal** — One sentence describing what it builds
2. **Architecture** — 2-3 sentences about approach
3. **File Structure** — Which files to create or modify
4. **Tasks** — Bite-sized steps with exact code

## Task Granularity

Each step should be 2-5 minutes:
- Write the failing test
- Run it to verify it fails
- Write minimal implementation
- Run tests to verify it passes
- Commit

## Rules

- Exact file paths always
- Complete code in every step
- Exact commands with expected output
- No placeholders ("TBD", "TODO", "implement later")
- DRY. YAGNI. Frequent commits.

## Checklist

- [ ] Spec/requirements reviewed
- [ ] File structure mapped
- [ ] Tasks decomposed into bite-sized steps
- [ ] Each step has actual code (not placeholders)
- [ ] No step depends on undefined types/functions
