---
name: systematic-debugging
description: "Use when encountering any bug, test failure, or unexpected behavior, before proposing fixes. Systematic approach to root cause analysis."
---

# Systematic Debugging

Follow this disciplined process when debugging any issue.

## Process

1. **Reproduce** — Confirm the exact steps to reproduce the issue. If you can't reproduce it, you can't fix it.
2. **Observe** — Gather all relevant information: error messages, stack traces, logs, input data.
3. **Hypothesize** — Form a specific hypothesis about the root cause. Write it down.
4. **Test** — Design the smallest possible experiment to confirm or refute the hypothesis.
5. **Fix** — Only fix after confirming the root cause. Write the minimal fix.
6. **Verify** — Run the tests. Confirm the fix works and doesn't break anything else.

## Rules

- NEVER propose a fix before identifying the root cause.
- NEVER make more than one change at a time during debugging.
- ALWAYS check logs, error messages, and stack traces first.
- If the hypothesis is wrong, form a new one. Don't patch on top of a wrong assumption.
- Use binary search (comment out half the code) to isolate the problem area.

## Checklist

- [ ] Issue is reproducible
- [ ] Error messages and logs collected
- [ ] Root cause identified (not just symptoms)
- [ ] Minimal fix applied
- [ ] Tests pass
- [ ] No regressions introduced
