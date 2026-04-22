---
name: executing-plans
description: "Use when you have a written implementation plan to execute. Load plan, review critically, execute tasks step by step with progress tracking."
---

# Executing Plans

Load plan, review critically, execute all tasks, report when complete.

## The Process

### Step 1: Load and Review Plan

1. Read plan file
2. Review critically - identify any questions or concerns about the plan
3. If concerns: Raise them with your human partner before starting
4. If no concerns: Create TODO.md and proceed

### Step 2: Execute Tasks

For each task:
1. Update TODO.md marking the task as in-progress
2. Follow each step exactly (plan has bite-sized steps)
3. Run verifications as specified
4. Update TODO.md marking the task as completed
5. If a step reveals new work, add it to TODO.md

### Step 3: Verify and Complete

After all tasks complete:
1. Run all tests and verifications
2. Check TODO.md — every item should be `[x]`
3. Report summary to user

## When to Stop and Ask for Help

**STOP executing immediately when:**
- Hit a blocker (missing dependency, test fails, instruction unclear)
- Plan has critical gaps preventing starting
- You don't understand an instruction
- Verification fails repeatedly

**Ask for clarification rather than guessing.**

## When to Revisit Earlier Steps

**Return to Review (Step 1) when:**
- Partner updates the plan based on your feedback
- Fundamental approach needs rethinking

**Don't force through blockers** - stop and ask.

## Rules

- Review plan critically first
- Follow plan steps exactly
- Don't skip verifications
- Update TODO.md after each step, not at the end
- Stop when blocked, don't guess
- Never start implementation on main/master branch without explicit user consent

## Integration

- **writing-plans** — Creates the plan this skill executes
- **task-tracker** — Tracks progress via TODO.md during execution
- **verification-before-completion** — Final verification before claiming done
