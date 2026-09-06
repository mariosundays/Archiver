# Archiver

Scan a VFX or 3D project folder and work out what has to survive an archive,
what can go, and what only you can decide.

Standalone — no Houdini, no Cinema 4D, and nothing beyond PySide6 for the GUI.
It reads scene files straight off disk rather than opening the application.

```
python main.py                     # GUI
python main.py "D:/Projects/shot"  # GUI, scanning that folder
python archiver.py "D:/Projects/shot" --json report.json
```

---

## What it does

Two independent questions, kept apart on purpose.

**Category** is what a thing *is* — source, cache, render, backup, delivery.
**Verdict** is whether it must survive.

| | |
|---|---|
| **Keep** | Cannot be regenerated. Source, scenes, deliveries. |
| **Review** | Could go either way. Renders you may still need, caches whose scene is gone. |
| **Drop** | Regenerable, superseded, or disposable. |

Splitting the two is what lets a sim cache whose scene still exists and one
whose scene has been deleted share a category but get different verdicts.

### The rules that matter

- **Nothing irreplaceable is ever dropped for being unreferenced.** An
  unreferenced texture is still a texture. Reference evidence can only move a
  verdict *toward* keep, never toward drop.
- **Superseded beats everything.** A `render/v01` sitting beside `render/v03`
  is usually the largest reclaimable thing in a project. It applies only to
  renders, comps and caches — never to source or scenes, where `v01` may hold
  something `v03` does not.
- **A cache is only droppable while its scene exists.** Nothing referencing it
  means re-cooking may be impossible, so it becomes *review*, not *drop*.
- **The folder decides ambiguous media.** An `.exr` means nothing on its own;
  `render/`, `tex/` and `plates/` are the whole signal. Unambiguous extensions
  win over their folder — unless that folder is `backup/` or `tmp/`.

Folder names match on whole segments with order prefixes stripped, so
`05_render`, `render_v02` and `Renders` all read as renders while
`rendering_notes` does not.

---

## Reading scenes

Scene files are scraped for the paths they name. Approximate by design, and
the error is one-sided: a path found that turns out to be dead costs nothing,
while a path missed could archive away a live asset.

Houdini `.hip .hiplc .hipnc` — `$HIP` and `$JOB` expanded, sequence and UDIM
patterns globbed against disk, and a File Cache's procedural output folder
recovered from its `basedir` string. Also Blender, Maya, Nuke, After Effects,
Fusion and Substance.

### Cinema 4D is a real limitation

Modern `.c4d` files (R20+) are a proprietary compressed container. Verified on
an R25 file: magic `QC4DC4D6`, entropy 7.19 bits/byte, and not one asset path
in plaintext.

**Nothing can be read from them**, which means a C4D project yields no
references at all and every cache looks unused. Archiver detects these by
magic, says so plainly at the top of the report, and holds every
reference-based verdict back to *review*. On such a project the verdicts rest
on file type and location alone.

A Cinema 4D-side script that exports each scene's asset list to JSON would
close this gap. Not built yet.

---

## The six steps

The GUI is a wizard, because there is a point of no return in the middle and
you should always know which side of it you are on.

| | Step | State |
|---|---|---|
| 1 | **Check project** — tree with inline size bars, summary strips | done |
| 2 | **What can go** — findings with reasons; delete empty folders | done |
| 3 | **Select** — folder-level tri-state, nothing ticked by default | done |
| 4 | **Review** — what you chose, and where you overrode the scan | done |
| 5 | **Approve** — move the selection to `_toDelete/`, with restore | done |
| 6 | **Archive** — copy the project out, as a folder or a zip | done |

Steps 1–4 are pure reads.

**Approving never deletes.** It *moves* the chosen folders into
`<project>/_toDelete`, keeping their relative path, and writes a manifest
recording where each came from. You then check the project still opens and
delete that folder yourself when satisfied — or press Restore, which reads the
manifest and puts everything back, so it works even after closing the app.

Staging refuses rather than guesses in four cases, each a real way to lose
work: a path outside the project, the project root itself, anything already
staged, and a path that vanished since the scan. A restore whose destination
has been filled again is refused too, never merged — silently combining two
versions of a cache is the damage this tool exists to prevent.

Deleting empty folders uses `os.rmdir` rather than `shutil.rmtree`, so a
folder that has gained a file since the scan makes the call fail loudly
instead of destroying it.

**Archiving copies, never moves**, so an interrupted archive costs time and
nothing else. `_toDelete` is excluded and its size reported, and everything
refusable — a destination inside the project, too little free space — is
checked before a byte moves. Verification compares every file's size at the
destination afterwards.

On the 3.4 GB test project a folder copy took 3 seconds and a zip took 99,
for 9% saved: EXR and MOV data barely compresses, and the dialog says so
before you choose.

### Reading the view

Each tree row carries a proportional bar: length is that folder's share of its
**parent** (against the whole project, everything below the top two rows is a
flat nothing), colour is the verdict. Two slim strips above give the
whole-project split by verdict and by category — double-click a segment, or
its legend entry, to list the files behind it in a pane below the tree, with
frame sequences collapsed to one row.

Right-click any row for *Show in Explorer* or *Copy path*.

---

## Layout

```
Archiver/
├── main.py               GUI entry point
├── archiver.py           CLI entry point
├── core/                 Qt-free and DCC-free throughout
│   ├── scene_parser.py   read scene references without the app
│   ├── rules.py          categories, verdicts, heuristics
│   ├── scanner.py        the walk and the report model
│   ├── tree.py           rolled-up sizes for the birds-eye view
│   ├── selection.py      what the user chose
│   ├── backup.py         copying the project out
│   ├── actions.py        the ONLY module that writes
│   └── report.py         text and JSON rendering
├── app/                  PySide6 UI
└── tests/                222 tests: python tests/run_all.py
```

`core/` never imports Qt, `hou`, or `c4d`, so the rules are testable without a
display. `actions.py` is kept separate so the read-only guarantee on
everything else stays easy to verify — `test_scanner.TestReadOnly` snapshots
the scanned tree and fails if a scan changed a single byte.

---

## Tests

```
python tests/run_all.py
```

222 tests, no Houdini, no Cinema 4D, no dependencies. The Qt-dependent ones
skip cleanly when PySide6 is absent. The staging tests are the most paranoid
in the suite: most of them assert what must NOT happen.

---

## Status

**v0.4.1** — all six steps of the wizard. See [CHANGELOG.md](CHANGELOG.md).

Built and validated against a real archived job (3.4 GB, 222 files, 62 C4D
scenes). The first run on real data found five bugs, all fixed and all with
regression tests.

## Related

`AssetCleaner` answers a narrower question from inside Houdini — "does the
open scene reference this file?". Archiver is the outside view: every scene,
every file type, and a verdict about the whole project.

## Licence

GPL-3.0.
