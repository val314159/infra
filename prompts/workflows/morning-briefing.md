---
title: Morning Briefing Workflow
type: workflow
model: gpt-4o
version: 1.0
date: 2026-04-05
tags: [workflow, daily, briefing]
status: active
supersedes: null
---

This workflow provides a daily lab status summary and identifies priorities for the day.

## Step 1: Scan Recent Activity
Review what happened in the last 24 hours:
- New experiments started
- Research progress made
- Conversations and insights
- Files created or modified

## Step 2: Check Active Work
Review current active items:
- Experiments in progress
- Research topics being explored
- Projects needing attention
- Ongoing conversations

## Step 3: Identify Blockers
Look for anything blocking progress:
- Stuck experiments
- Unanswered research questions
- Missing resources or information
- Technical issues

## Step 4: Review Pipeline Health
Check the ideas→research→experiments→projects pipeline:
- Ideas ready for research
- Research ready for experiments
- Experiments ready for promotion
- Projects needing maintenance

## Step 5: Surface Opportunities
Identify potential opportunities:
- Related work that could be connected
- Experiments that should be promoted
- Research that's ready for the next stage
- Cross-cutting themes emerging

## Step 6: Generate Daily Summary
Create a structured briefing:
```
# Lab Briefing - [Date]

## Recent Activity
- [key activities from last 24h]

## Active Work
- [experiments, research, projects in progress]

## Today's Priorities
- [top 3 priorities for today]

## Blockers
- [anything preventing progress]

## Opportunities
- [connections, promotions, next steps]
```

## Step 7: Save Briefing
Save the briefing to `notes/` with timestamp: `briefing-2026-04-05.md`

## Output
A daily lab status summary that provides context and identifies priorities.

## Frequency
Run this workflow daily to maintain lab awareness and continuity.

## Next Steps
- Address identified priorities
- Resolve blockers
- Pursue opportunities
- Continue with planned work
