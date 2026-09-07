# Archiver

**Beta — v0.7.0.** Working and used on real jobs, but not yet proven on
anybody else's machine or anybody else's projects. Read
[Before you try it](#before-you-try-it) first.

Scan a VFX or 3D project folder and work out what has to survive an archive,
what can go, and what only you can decide.

Standalone — no Houdini, no Cinema 4D, and nothing beyond PySide6 for the GUI.
It reads scene files straight off disk rather than opening the application.

---

## Install

**The easy way — no Python needed.** Grab the latest
[release](https://github.com/mariosundays/Archiver/releases) and take either:

| | |
|---|---|
| `Archiver_Setup_<version>.exe` | Installer. Per-user by default, so no admin prompt. Start Menu entry, optional desktop shortcut, proper uninstaller. |
| `Archiver_v<version>_portable.zip` | Unzip anywhere and run `Archiver.exe`. Nothing is installed and nothing is written outside the folder. |

The build is unsigned, so SmartScreen will warn on first run — *More info* →
*Run anyway*. That is what an unsigned binary from a small publisher looks
like; if you would rather not, run from source below.

### From source

Windows, Python 3.9 or newer. Nothing to compile.

```
git clone https://github.com/mariosundays/Archiver.git
cd Archiver
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Then:

```
python main.py                     # GUI, pick a folder from the toolbar
python main.py "D:/Projects/shot"  # GUI, scanning that folder
python archiver.py "D:/Projects/shot"              # CLI report
python archiver.py "D:/Projects/shot" --json out.json
```

Check it works before pointing it at anything you care about:

```
python tests/run_all.py            # 333 tests, ~2 seconds
```

The CLI needs nothing but the standard library, so if PySide6 will not install
you can still run `archiver.py`. The Qt-dependent tests skip themselves when
PySide6 is absent.

Developed and used on Windows 11. `core/` is pure standard library and should
behave anywhere, but the GUI's *Show in Explorer* and the C4D plugin installer
are Windows-only, and nothing has been tested on macOS or Linux.

---

## Before you try it

Please read this bit — it is a beta, and the failure mode is your files.

- **Steps 1 to 4 only read.** Scanning, the findings list and the review
  screen never write a byte. `test_scanner.TestReadOnly` snapshots the scanned
  tree and fails if a scan changed anything.
- **Nothing is ever deleted.** Approving *moves* your selection into
  `<project>/_toDelete` and writes a manifest so Restore works even after you
  close the app. You do the deleting yourself, once you are satisfied.
  Archiving *copies*; it never moves.
- **Start on a copy, or on a finished job you already have backed up.** Not on
  live work, and not on the only copy of anything.
- **Nothing is ticked by default.** You opt in to every folder, so an
  accidental Approve does nothing.
- **On a Cinema 4D project, read the C4D section below.** R20+ `.c4d` files
  cannot be read from outside, so a pure-C4D project gives no reference
  evidence at all and everything reference-based is held back to *review*.
  This is the tool's central limitation, not a bug.
- **The zip path is the least-exercised code here.** Folder-copy archiving has
  been run on real multi-gigabyte jobs; zip has mostly seen synthetic data.
  Prefer the folder mirror for now.

Found something wrong? Please open an issue with what you scanned (rough shape
of the project is enough), what it said, and what you expected. Every scan
writes a report to the project root as `.archiver_report.json` — that is the
most useful thing to attach.

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
- **"A newer version exists" means different things for different files.** A
  `render/v01` beside a `render/v03` is usually the largest reclaimable thing
  in a project. A `shot_v001.hip` beside a `shot_v003.hip` is not old, it is
  the only record of how the shot looked then. So the version drives the
  verdict only where it argues for one:

  | | Older version | Why |
  |---|---|---|
  | Renders | **drop** | Dead weight, and the biggest reclaim in most jobs. |
  | Caches | **drop**, if proven | Only when a readable scene names it, so it genuinely re-cooks. Otherwise review. |
  | Dailies / comps | **review** | A v001 cut is a record of what was shown on a date. Your call, so it waits to be ticked. |
  | Scenes | keep | Every version is kept. |
  | Source, geo | keep | A `tex/v01` may hold a map `v03` does not, and the loss is unrecoverable. |
  | Deliveries, docs | keep | What shipped, shipped. |
  | Backups | drop | Disposable either way — the version is beside the point, and the reason says so. |
- **A cache says which of three things it is.** *Proven* — a readable scene
  names it, so it re-cooks and the Used by column says from what. *Orphaned* —
  every scene was readable and none named it, so whatever made it is gone.
  *Unverified* — a scene could not be read, so nothing was checked. Only the
  first drops. On a mixed Houdini/C4D project that distinction is the whole
  decision.
- **Slow sims are flagged as slow.** A FLIP or pyro cache is regenerable and
  that is beside the point; those rows say "SLOW to re-cook" so Drop never
  reads as free to lose.
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

### Cinema 4D cannot be read from outside

Modern `.c4d` files (R20+) are a proprietary compressed container. Verified on
an R25 file: magic `QC4DC4D6`, entropy 7.19 bits/byte, and not one asset path
in plaintext.

**Nothing can be read from them**, which means a C4D project yields no
references at all and every cache looks unused. Archiver detects these by
magic, says so plainly at the top of the report, and holds every
reference-based verdict back to *review*. Without help, the verdicts on such
a project rest on file type and location alone.

### The fix: asset sidecars

Cinema 4D knows what its scenes load even though the file will not say. So it
writes the answer down: **Extensions → Archiver Asset Export** dumps each
scene's asset list to a JSON file beside it, and Archiver reads that instead
of scraping.

```
shot_010.c4d
shot_010.c4d.assets.json     <- what the scene actually loads
```

Pick a scope when you run it: this scene, every scene in its folder, or every
scene in a project folder you choose. A batch opens and closes each scene in
turn, so a sixty-scene job is one unattended pass.

Install with `c4d_plugin/sync_to_c4d.ps1`, then restart Cinema 4D.

**A sidecar older than its scene is evidence, not truth.** Somebody may have
added a cache since the export, so a stale sidecar's paths still protect what
they name — that direction cannot lose data — but the scene stays counted as
unreadable, and nothing is promoted to *drop* on the strength of old evidence.
The review screen and the report both say how many are stale.

| | Scene reads | Trust |
|---|---|---|
| Fresh sidecar | normally | full |
| Stale sidecar | paths still protect what they name | held back |
| No sidecar | nothing | held back |

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
│   ├── sidecar.py        the asset list a DCC writes beside a scene
│   ├── c4d_assets.py     the c4d-free half of the C4D export
│   ├── rules.py          categories, verdicts, heuristics
│   ├── scanner.py        the walk and the report model
│   ├── tree.py           rolled-up sizes for the birds-eye view
│   ├── selection.py      what the user chose
│   ├── backup.py         copying the project out
│   ├── actions.py        the ONLY module that writes
│   └── report.py         text and JSON rendering
├── app/                  PySide6 UI
├── c4d_plugin/           Cinema 4D asset export + sync_to_c4d.ps1
└── tests/                333 tests: python tests/run_all.py
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

333 tests, no Houdini, no Cinema 4D, no dependencies. The Qt-dependent ones
skip cleanly when PySide6 is absent. The staging tests are the most paranoid
in the suite: most of them assert what must NOT happen.

---

## Building the installer

```
pip install pyinstaller
build.bat
```

Produces `releases\Archiver_v<version>_portable.zip` and, if
[Inno Setup 6](https://jrsoftware.org/isdl.php) is installed,
`installer_out\Archiver_Setup_<version>.exe`. Without Inno Setup you still get
the zip. The version is read from `core/__init__.VERSION`, so it is never
typed twice, and the tests must pass before anything is packaged.

Pushing a `v*` tag builds both on GitHub Actions and attaches them to the
release; tags containing `-beta` are marked as prereleases automatically.

---

## Status

**Beta, v0.7.0.** All six steps of the wizard are built, plus the Cinema 4D
asset export that closes the `.c4d` blind spot. See
[CHANGELOG.md](CHANGELOG.md).

Built and validated against real archived jobs — the empty-folder prune,
staging, restore and a full archive have all been run on real work. The first
run on real data found five bugs, all fixed and all with regression tests.

What *beta* means here, honestly:

- It has only ever run on its author's machine, against his own projects,
  which are mostly Cinema 4D and Houdini. Other layouts and other DCCs are
  reasoned about but unproven.
- **The Cinema 4D plugin has never been run inside Cinema 4D.** The half that
  does not need `c4d` is tested; the plugin itself is written but unexercised.
- Zip archiving has mostly been run on synthetic data.
- Real projects have found bugs that 330 green tests did not, five separate
  times. Expect that to happen again.

## Related

`AssetCleaner` answers a narrower question from inside Houdini — "does the
open scene reference this file?". Archiver is the outside view: every scene,
every file type, and a verdict about the whole project.

## Licence

GPL-3.0.
