---
title: Lab Curation Workflow
type: workflow
model: gpt-4o
version: 1.0
date: 2026-04-05
tags: [workflow, curation, organization]
status: active
supersedes: null
---

This workflow finds orphaned work, suggests promotions, and improves lab organization.

## Step 1: Scan All Directories
Systematically review each lab area:
- `ideas/` - old ideas that never moved forward
- `research/` - completed research not acted on
- `experiments/` - successful experiments not promoted
- `projects/` - inactive or completed projects
- `notes/` - notes that should be structured
- `writing/` - drafts that need completion

## Step 2: Identify Orphaned Work
Look for work that's been abandoned:
- Files with old modification dates
- Incomplete experiments with clear results
- Research with actionable findings
- Ideas that keep recurring
- Notes that should be formalized

## Step 3: Find Promotion Candidates
Identify work ready for the next stage:
**Ideas → Research:**
- Recurring themes in ideas
- Ideas with clear questions to investigate
- Concepts that need systematic study

**Research → Experiments:**
- Research with testable hypotheses
- Findings that need practical validation
- Research suggesting specific approaches

**Experiments → Projects:**
- Successful experiments with proven value
- Experiments solving real problems
- Work that needs ongoing maintenance

## Step 4: Detect Organization Issues
Look for structural problems:
- Duplicate or redundant work
- Poorly named directories
- Missing README files
- Work in wrong locations
- Broken symlinks or references

## Step 5: Generate Curation Report
Create a detailed curation report:
```
# Lab Curation Report - [Date]

## Promotions Recommended
- [item] → [stage] because [reason]

## Archival Suggestions
- [item] - archive because [reason]

## Organization Improvements
- [improvement] - [benefit]

## Cross-Cutting Themes
- [theme]: [related items]

## Action Items
- [specific actions with priorities]
```

## Step 6: Create Action Plan
Generate specific next steps:
- Promotion tasks with required actions
- Archival tasks with cleanup steps
- Organization improvements with implementation steps
- Priority ordering based on impact

## Step 7: Save Report
Save curation report to `notes/curation-2026-04-05.md`

## Output
A comprehensive curation report with actionable recommendations for lab improvement.

## Frequency
Run this workflow quarterly or when the lab feels cluttered.

## Success Criteria
- All orphaned work identified and addressed
- Clear promotion pipeline established
- Organization improved and documented
- Actionable priorities created

## Next Steps
- Execute high-priority actions
- Promote identified candidates
- Archive dead-end work
- Improve organization structure
