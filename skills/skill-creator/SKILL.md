---
name: skill-creator
description: Create or update Ferryman skills by drafting a skill in the current session workspace, validating its structure, and publishing it into the user's installed skills directory when ready.
version: 0.1.0
author: Ferryman
---

# Skill Creator

You create or update Ferryman skills.

Your default workflow is:

1. Understand the requested skill and pick a short hyphen-case name.
2. Create or update the skill draft inside the current session workspace.
3. Use `run_skill_script` to initialize the draft structure when helpful.
4. Edit `SKILL.md` and any needed `scripts/`, `references/`, or `assets/`.
5. Run `run_skill_script(script_name="quick_validate.py", args=[draft_dir])`.
6. If validation passes and the user wants the skill installed, call `publish_skill(draft_path=draft_dir)`.

## Directory Rules

- Always build draft skills inside the current session workspace first.
- Do not write a new skill directly into the installed user skills directory.
- Keep the skill folder name exactly equal to the skill name.
- Use only lowercase letters, digits, and hyphens in skill names.

## Required Files

Every skill must contain:

- `SKILL.md`

Optional directories:

- `scripts/`
- `references/`
- `assets/`

Do not add extra documentation files such as `README.md`, `CHANGELOG.md`, or install guides unless the user explicitly asks for them.

## SKILL.md Guidance

`SKILL.md` must include YAML frontmatter with at least:

- `name`
- `description`

Prefer concise instructions. Only include information the model truly needs at runtime.

When a skill supports multiple variants or large references:

- keep the core workflow in `SKILL.md`
- move detailed material into `references/`
- mention those reference files explicitly from `SKILL.md`

## When to Add Scripts

Add scripts only when one of these is true:

- the same code would otherwise be rewritten repeatedly
- the operation is fragile and benefits from deterministic execution
- validation or packaging is easier as a script than as prompt-only logic

## Validation

Before publishing a new skill:

- ensure `SKILL.md` exists
- ensure frontmatter parses
- ensure `name` and `description` are present
- ensure the folder name matches the skill name
- ensure referenced local files exist when they are required for the workflow

Use `quick_validate.py` for the default fast check. If validation fails, fix the draft before publishing.

## Publishing

Only publish after:

- the draft exists in the current workspace
- validation passes
- the user asked to install it or the task clearly requires installation

Publishing must happen through the `publish_skill` tool, not by manually moving files with scripts.
