---
title: New Experiment Workflow
type: workflow
model: gpt-4o
version: 1.0
date: 2026-04-05
tags: [workflow, experiment, creation]
status: active
supersedes: null
---

This workflow scaffolds a new experiment end-to-end, from idea to working experiment.

## Step 1: Define the Experiment
Create the experiment directory and basic structure:
```
experiments/{{experiment-name}}/
├── README.md
├── hypothesis.md
└── results.md
```

## Step 2: Write README.md
Create a comprehensive README with:
- Experiment name and date
- Clear hypothesis statement
- Approach and methodology
- Success criteria
- Required resources

## Step 3: Detail the Hypothesis
In `hypothesis.md`, expand on:
- What you're testing and why
- Expected outcomes
- Assumptions and constraints
- Risk factors

## Step 4: Plan the Approach
Outline the specific steps:
- Setup requirements
- Test procedures
- Data collection methods
- Analysis approach

## Step 5: Prepare for Results
Set up `results.md` with sections for:
- Observations and data
- Analysis and insights
- Lessons learned
- Next steps

## Step 6: Initial Setup
Create any necessary files, scripts, or configurations needed to run the experiment.

## Step 7: Review and Refine
Review the complete experiment structure and make sure it's ready to execute.

## Output
A complete experiment directory that's ready to run, with clear documentation and success criteria.

## Next Steps After This Workflow
- Execute the experiment using the Programmer agent
- Document results and observations
- Evaluate success against criteria
- Consider promotion to project if successful
