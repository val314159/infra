---
title: Infrastructure Audit Workflow
type: workflow
model: gpt-4o
version: 1.0
date: 2026-04-05
tags: [workflow, infrastructure, audit]
status: active
supersedes: null
---

This workflow reviews the lab infrastructure for drift, debt, and improvement opportunities.

## Step 1: Review CLI Tool
Check the chat CLI implementation:
- Are all slash commands working?
- Are conversation files being created properly?
- Are permissions being set correctly?
- Are symlinks being managed properly?

## Step 2: Audit Prompt Library
Review all prompts in `infra/prompts/`:
- Check frontmatter consistency
- Verify all prompts have proper status
- Look for outdated or superseded prompts
- Identify missing prompt types

## Step 3: Check Configuration
Review configuration files:
- Is `config.yaml` complete and correct?
- Are all endpoints configured properly?
- Are environment variables documented?
- Are secrets properly excluded?

## Step 4: Validate Directory Structure
Check the lab directory structure:
- Are all required directories present?
- Does each directory have a README.md?
- Are permissions set according to conventions?
- Is the organization logical and discoverable?

## Step 5: Review Conversation Storage
Audit the conversation system:
- Are conversation files being created with proper UUIDs?
- Are files being chmod 444 after writing?
- Are symlinks working properly?
- Is the file format consistent?

## Step 6: Check Dependencies
Review technical dependencies:
- Are Python packages up to date?
- Are there security vulnerabilities?
- Are all dependencies necessary?
- Are versions pinned appropriately?

## Step 7: Generate Audit Report
Create a comprehensive audit report:
```
# Infrastructure Audit - [Date]

## Issues Found
- [critical issues]
- [minor issues]

## Improvements Needed
- [structural improvements]
- [documentation updates]
- [process improvements]

## Recommendations
- [priority recommendations]
- [long-term suggestions]

## Health Score
- Overall: [score/10]
- CLI: [score/10]
- Prompts: [score/10]
- Structure: [score/10]
```

## Step 8: Save Audit
Save audit to `infra/audit-2026-04-05.md`

## Output
A comprehensive infrastructure audit with actionable recommendations.

## Frequency
Run this workflow monthly or when infrastructure issues are suspected.

## Success Criteria
- All critical issues identified and documented
- Clear improvement roadmap provided
- Infrastructure health assessed objectively
- Recommendations prioritized by impact
