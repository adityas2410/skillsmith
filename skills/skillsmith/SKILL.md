---
name: skillsmith
description: Create portable Agent Skills from screen recording videos. Use when the user asks to turn a local video file of a browser, desktop app, or UI workflow into a reusable skill.
license: MIT
compatibility: Requires local filesystem access to the source video and to a writable skills directory. Intended for agents that support Agent Skills or compatible skill folders.
metadata:
  project: SkillSmith
  output: portable-agent-skill
---

# SkillSmith

Use SkillSmith to convert a user's screen recording into a new reusable Agent Skill.

The user may only provide a video path, for example:

```text
make C:\Recordings\create-invoice.mp4 into a skill
```

Infer reasonable defaults before asking follow-up questions. Ask only for information that cannot be inferred safely.

## Inputs

Required:

- `video`: Local path to the screen recording.

Infer when absent:

- `name`: Generated skill name. Derive it from the video filename unless the user provides a skill name.
- `out`: Parent directory where the generated skill folder should be created. Prefer the host agent's project-local skills directory, then the host agent's global skills directory. If no suitable skills directory is known, ask the user for the output parent directory.

The generated skill must be written to:

```text
<out>/<name>/
```

## Skill Name Rules

Normalize generated skill names to the Agent Skills naming rules:

- Use lowercase letters, numbers, and hyphens only.
- Keep the name under 64 characters.
- Do not start or end with a hyphen.
- Replace spaces, underscores, and punctuation with hyphens.
- Collapse repeated hyphens.
- Prefer concise action-oriented names derived from the demonstrated workflow.

Examples:

- `Create Invoice Flow.mp4` -> `create-invoice-flow`
- `browser checkout demo.mov` -> `browser-checkout-demo`
- `Update CRM Contact.webm` -> `update-crm-contact`

## Workflow

1. Confirm the source video exists and is readable.
2. Determine the generated skill name and output parent directory.
3. Create the generated skill folder at `<out>/<name>/`.
4. Analyze the screen recording for the demonstrated UI workflow.
5. Capture the operational steps an agent would need to repeat the workflow.
6. Write a valid `SKILL.md` for the generated skill.
7. Verify the generated skill folder follows the Agent Skills structure.

## Generated Skill Structure

Create generated skills using this default portable layout:

```text
skill-name/
+-- SKILL.md
```

Do not create `scripts/`, `references/`, or `assets/` by default. Add optional directories only when the user requests them or the generated workflow clearly requires bundled helpers, supporting documentation, or reusable resources.

## Generated SKILL.md Requirements

The generated `SKILL.md` must start with YAML frontmatter followed by Markdown instructions.

Required frontmatter:

```yaml
---
name: skill-name
description: Clear description of what the skill does and when an agent should use it.
---
```

The `name` field must match the generated skill folder name exactly.

The Markdown body should include:

- The purpose of the generated skill.
- Required user inputs and assumptions.
- Step-by-step operating procedure for the demonstrated UI workflow.
- How to handle common UI variations or missing state.
- Any bundled scripts, references, or assets if optional directories were created.
- Validation steps the agent should perform after completing the workflow.

Keep the generated skill portable. Do not hard-code behavior for one host agent unless the user's recording or request is specific to that environment.

## Output Behavior

If the host agent knows its skill directory, write directly there unless the user requested a different destination.

If the host agent supports both project-local and global skills:

- Prefer project-local output when the workflow is specific to the current repository, app, account, or team.
- Prefer global output when the workflow is broadly reusable.
- Ask the user when the scope is ambiguous and the choice would matter.

If the target skill folder already exists, do not overwrite it silently. Ask whether to replace it, update it, or choose another name.

## Current Implementation

Use `scripts/main.py` as the executable helper when available. Until the helper is fully implemented, perform the workflow manually: inspect the video with available local tools, extract representative observations, and write the generated skill files directly.
