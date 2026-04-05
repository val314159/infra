---
title: Research to Experiment Workflow
type: workflow
model: gpt-4o
version: 1.0
date: 2026-04-05
tags: [workflow, research, experiment]
status: active
supersedes: null
---

This workflow converts research findings into a testable experiment plan.

## Step 1: Review Research
Read through the research directory and identify:
- Key findings and insights
- Testable hypotheses from the research
- Gaps that need practical validation
- Promising approaches worth trying

## Step 2: Identify Experiment Candidates
From the research, list 2-3 potential experiments:
- What each would test
- Why it's worth testing
- Expected outcomes based on research
- Resource requirements

## Step 3: Select Best Candidate
Choose the most promising experiment based on:
- Clear testable hypothesis
- Feasibility and resources
- Potential impact
- Connection to research findings

## Step 4: Create Experiment Structure
Set up the experiment directory:
```
experiments/{{experiment-name}}/
├── README.md
├── hypothesis.md
├── research-links.md
└── results.md
```

## Step 5: Link to Research
Create `research-links.md` documenting:
- Which research findings inform this experiment
- Key sources and citations
- How research led to this hypothesis

## Step 6: Write Experiment Plan
Create comprehensive README with:
- Hypothesis grounded in research
- Approach based on research insights
- Success criteria that validate research findings

## Step 7: Setup Requirements
Prepare any files, scripts, or configurations needed.

## Output
An experiment that directly tests findings from research, with clear links back to source material.

## Success Criteria
- Experiment hypothesis is directly supported by research
- Approach is informed by research insights
- Success criteria will validate or refute research findings
- Clear documentation of research-to-experiment connection

## Next Steps
- Execute the experiment
- Compare results with research expectations
- Update research based on experimental findings
