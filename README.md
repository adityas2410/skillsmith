# Skillsmith

Skillsmith is an Agent Skill that helps agents create new reusable skills from screen recordings.

The user provides a local video file showing a browser, desktop app, or UI workflow. The agent invokes Skillsmith, analyzes the recording, and writes a new portable skill folder that future agents can use to repeat or understand that workflow.

## What It Creates

Skillsmith generates a new skill folder with a `SKILL.md` file:

```text
skill-name/
+-- SKILL.md
```

Optional folders such as `scripts/`, `references/`, and `assets/` are not created by default. Skillsmith should add them only when the generated workflow explicitly needs executable helpers, supporting documentation, or bundled resources.

## Installing Skillsmith

Coding agents that support Agent Skills commonly provide a Skill Installer or
Skill Creator capability. Ask the agent to use either capability to add the
existing `skills/skillsmith/` folder from this repository to its known skills
directory. For example:

```text
Use your skill installer to install Skillsmith from
https://github.com/adityas2410/skillsmith/tree/main/skills/skillsmith
```

or:

```text
Use your skill creator to add the existing Skillsmith skill from
https://github.com/adityas2410/skillsmith/tree/main/skills/skillsmith
to your skills directory without changing its files.
```

The exact destination differs between coding agents, so let the agent choose
its supported project-local or global skills directory unless you require a
specific location.

## How It Is Used

Skillsmith itself is installed as a skill in an agent's skills directory. A user can then ask naturally:

```text
make C:\Recordings\invoice-flow.mp4 into a skill
```

The agent should infer:

- the generated skill name from the video filename, unless the user provides one
- the output directory from the agent's known project-local or global skills directory
- whether the generated skill should be project-specific or broadly reusable

If the agent cannot determine a safe output location, it should ask the user for the parent directory where the new skill folder should be created.

## Skillsmith Layout

This repository currently contains the Skillsmith skill:

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
full-color PNG keyframes, ordered contact sheets, and a JSON manifest.

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

Skillsmith does not impose a recording-duration limit. The recommendation to
use shorter demonstrations is about keeping each generated skill focused, not
about a processing limitation. Split a multi-feature application walkthrough
into separate recordings such as login, create invoice, update customer, and
export report. Include enough time to show each feature completely while
avoiding unrelated navigation, long idle periods, and repeated demonstrations
of the same state.

## Temporary Keyframes and Manifest

The video helper creates a unique temporary run directory:

```text
<system-temp>/skillsmith/<run-id>/
+-- manifest.json
+-- contact-sheets/
|   +-- 000001.png
|   +-- 000002.png
+-- frames/
    +-- 000001_00-00-00.000.png
    +-- 000002_00-00-03.500.png
    +-- 000003_00-00-08.000.png
```

The files under `frames/` are the final selected full-color keyframes after
visual-change selection and adjacent-duplicate removal. Intermediate candidates
and discarded frames are not saved. The files under `contact-sheets/` group up
to four selected frames in a 2-by-2 grid. Each tile shows its frame number and
timestamp, ordered from left to right and then top to bottom.

`manifest.json` records the source video metadata and lists every selected
keyframe in chronological order with its timestamp, absolute path, selection
reason, and visual-difference scores. It also lists contact sheets in order and
maps each sheet to its original frames. The helper prints the absolute manifest
path so the host AI agent knows where to begin.

The host agent reads the manifest and inspects contact sheets in ascending order,
reading each sheet from left to right and then top to bottom. It opens an
original full-resolution frame only when a tile does not show enough detail.
This reduces image-processing cost without discarding workflow information. The
agent then writes the generated skill to its own known skills directory. After
the new `SKILL.md` has been generated and validated, the agent must delete the
complete temporary `<run-id>` directory. Temporary files should be retained only
when the user requests debugging artifacts or more analysis is still required.

## When to Use Skillsmith

Use Skillsmith when a workflow is best communicated through a human
demonstration, especially for desktop applications, private or authenticated
systems, environments unavailable to the agent, and procedures that are
difficult to describe precisely.

For an accessible website, a browser automation tool such as Playwright can
provide more accurate information about controls, labels, URLs, and page
structure. The two approaches can also be combined: use the recording to
understand the intended workflow, then use browser automation to verify the
current interface and behavior.

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

Skillsmith does not assume one universal skills directory because each host agent may store skills differently.
