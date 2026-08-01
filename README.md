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
        +-- run.py
        +-- main.py
        +-- requirements.txt
```

The helper samples candidate frames from the recording, scores meaningful layout,
pixel-area, and color-state changes, removes adjacent near-duplicates, and writes
full-color PNG keyframes plus a JSON manifest in chronological order.

Process a recording through the bootstrapper:

```powershell
python skills\skillsmith\scripts\run.py C:\Recordings\invoice-flow.mp4
```

The bootstrapper creates or reuses a `.venv` inside the installed `skillsmith`
folder, installs `scripts/requirements.txt` when needed, and runs the video
helper. The command prints the absolute path to `manifest.json`. By default,
artifacts are created under the system temporary directory in `skillsmith/<run-id>/`.

## Recording Recommendations

Record one focused UI feature or workflow per video. Short demonstrations make
it easier for the agent to identify the navigation steps and produce a precise
skill.

A 30-minute or one-hour recording can be processed, but it is not recommended
as one SkillSmith input. Processing time grows with the video length, long
recordings can produce many keyframes, and unrelated workflows make the final
skill harder for the agent to infer. Split a long application walkthrough into
separate recordings such as login, create invoice, update customer, and export
report.

There is no fixed short-video duration limit. Include enough time to show the
complete feature, while avoiding unrelated navigation, long idle periods, and
repeated demonstrations of the same state.

## Temporary Keyframes and Manifest

The video helper creates a unique temporary run directory:

```text
<system-temp>/skillsmith/<run-id>/
+-- manifest.json
+-- frames/
    +-- 000001_00-00-00.000.png
    +-- 000002_00-00-03.500.png
    +-- 000003_00-00-08.000.png
```

The PNG files are the final selected full-color keyframes after visual-change
selection and adjacent-duplicate removal. Intermediate candidates and discarded
frames are not saved.

`manifest.json` records the source video metadata and lists every selected
keyframe in chronological order with its timestamp, absolute path, selection
reason, and visual-difference scores. The helper prints the absolute manifest
path so the host AI agent knows where to begin.

The host agent reads the manifest, inspects only the listed keyframes, infers the
demonstrated UI navigation, and writes the generated skill to its own known
skills directory. After the new `SKILL.md` has been generated and validated, the
agent must delete the complete temporary `<run-id>` directory. Temporary files
should be retained only when the user requests debugging artifacts or more
analysis is still required.

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
