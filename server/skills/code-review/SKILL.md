---
name: code-review
description: "Use when completing tasks, implementing major features, or before merging to verify work meets requirements. Structured code review process."
---

# Code Review

Perform structured code review to verify quality before merging.

## Review Checklist

### Correctness
- [ ] Code does what the spec/requirements say
- [ ] Edge cases handled (empty input, null, large values)
- [ ] Error handling is appropriate (not too broad, not too narrow)
- [ ] No off-by-one errors or boundary issues

### Quality
- [ ] Functions are small and do one thing
- [ ] Naming is clear and consistent
- [ ] No duplicated logic (DRY)
- [ ] No dead code or commented-out code
- [ ] No hardcoded values that should be configurable

### Security
- [ ] No secrets or credentials in code
- [ ] Input validation on user-facing endpoints
- [ ] No SQL injection / XSS vulnerabilities
- [ ] File paths are validated (no path traversal)

### Performance
- [ ] No N+1 queries
- [ ] No unnecessary loops or recursive calls
- [ ] Large data sets handled efficiently
- [ ] Resources (connections, files) properly closed

## Rules

- Review for correctness FIRST, style SECOND
- Every "I think" must become "I verified by..."
- Flag security issues immediately
- Don't approve if tests are missing
