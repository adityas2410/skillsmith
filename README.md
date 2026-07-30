# SkillSmith

SkillSmith is an Agent Skill that helps agents create new reusable skills from screen recordings.

The user provides a local video file showing a browser, desktop app, or UI workflow. The agent invokes SkillSmith, analyzes the recording, and writes a new portable skill folder that future agents can use to repeat or understand that workflow.

## What It Creates

SkillSmith generates a new skill folder with a `SKILL.md` file:

```text
skill-name/
+-- SKILL.md
```

Optional folders such as `scripts/`, `references/`, and `assets/` are not created by default. SkillSmith should add them only when the generated workflow explicitly needs executable helpers, supporting documentation, or bundled resources.

## How It Is Used

SkillSmith itself is installed as a skill in an agent's skills directory. A user can then ask naturally:

```text
make C:\Recordings\invoice-flow.mp4 into a skill
```

The agent should infer:

- the generated skill name from the video filename, unless the user provides one
- the output directory from the agent's known project-local or global skills directory
- whether the generated skill should be project-specific or broadly reusable

If the agent cannot determine a safe output location, it should ask the user for the parent directory where the new skill folder should be created.

## SkillSmith Layout

This repository currently contains the SkillSmith skill:

```text
skills/
+-- skillsmith/
    +-- SKILL.md
    +-- scripts/
        +-- main.py
```

The executable helper code is intentionally minimal while the project is being designed. The first priority is a clear, portable skill contract.

## Output Location

Generated skills are written to:

```text
<output-parent-directory>/<generated-skill-name>/
```

For example:

```text
C:\Users\you\agent-skills\invoice-flow\
```

or:

```text
./.agent-skills/invoice-flow/
```

SkillSmith does not assume one universal skills directory because each host agent may store skills differently.
