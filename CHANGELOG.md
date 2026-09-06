# Changelog

## 0.2.0 -- 2026-09-06

Step 5: approving a selection now does something. It moves the chosen folders
into `<project>/_toDelete` and can put them back.

### Added

- **Staging.** Approve moves the selection into `_toDelete`, preserving each
  folder's relative path, and writes `archiver_manifest.json` recording where
  everything came from. Nothing is deleted -- you check the project still
  opens and remove that folder yourself.
- **Restore.** Reads the manifest rather than inferring from the layout, so it
  works after closing and reopening the app. The button appears only when
  something is actually staged.
- Staging refuses rather than guesses on: a path outside the project, the
  project root itself, anything already staged, and a path that vanished since
  the scan. Restore refuses a destination that has been filled again rather
  than merging into it.

### Fixed

- **A scene file inside `backup/` or `tmp/` was treated as a live scene**, so
  those folders came out *keep* and "tick all Drop" skipped them entirely --
  on a test project it selected 1 folder where it should have selected 2. A
  `.hip` in `backup/` is a backup copy of a scene; that is what the folder is
  for. The folder now outranks the extension for these two cases, as it
  already did for every other file type.

### Notes

- A move inside one filesystem is a rename: instant, and atomic per folder.
  That is why staging lives inside the project rather than on another drive,
  where it would be a copy-then-delete that can half-finish on a 200 GB cache.
- 166 tests. The staging suite is the most paranoid in the project -- most of
  its cases assert what must NOT happen, and each destructive path was also
  verified by hand against real files.

## 0.1.0 -- 2026-09-06

First release. Built and validated in one session against a real archived job
(`0091_BUCK_IBMThink`, 3.4 GB, 222 files, 62 Cinema 4D scenes). The first run
on real data found five bugs; everything under **Fixed** came out of that, and
most of it is about **not** recommending the deletion of files that matter.

### Added

- **Scan engine.** Walks a project, classifies every file, and reports a
  verdict per folder: keep, review, or drop. No Houdini, no Cinema 4D, no
  dependencies beyond the standard library.
- **Scene reading without the application.** `.hip`, `.hiplc`, `.hipnc`,
  `.c4d`, `.blend`, `.ma`, `.nk`, `.aep` and others are scraped for the asset
  paths they name. `$HIP` and `$JOB` are expanded, sequence and UDIM patterns
  are globbed against the disk, and a Houdini File Cache's procedural output
  folder is recovered from its `basedir` string.
- **Two independent axes.** *Category* is what a file is; *verdict* is whether
  it must survive. Keeping them apart is what lets a cache whose scene still
  exists and one whose scene is gone share a category but differ in verdict.
- **GUI** (PySide6): a folder tree with an inline proportional size bar per
  row, coloured by verdict, plus two slim summary strips for verdict and
  category. Double-clicking a strip segment opens a pane listing the files
  behind it, with frame sequences collapsed to one row.
- **Selection and review.** Folder-level tri-state selection, nothing ticked
  by default, and a review screen that leads with the folders you picked that
  the scan judged worth keeping.
- **Delete empty folders.** The one action this version performs. Uses
  `os.rmdir`, never `shutil.rmtree`, so a folder that gained a file since the
  scan makes the call fail loudly instead of destroying it.
- **CLI** (`archiver.py`) with a text report and JSON export.
- Right-click any row for *Show in Explorer* or *Copy path*.

### Fixed -- files that would have been archived away or wrongly kept

- **Cinema 4D scenes cannot be read at all.** Verified on an R25 file: magic
  `QC4DC4D6`, entropy 7.19 bits/byte, no zlib streams, and not one asset path
  in plaintext in either ASCII or UTF-16. It is a proprietary compressed
  container. The consequence is severe -- a C4D project yields *no* references,
  so every cache and every piece of geometry looks unused. The scan now
  detects these by magic, says so plainly, and holds every reference-based
  verdict back to *review*. Without that gate the tool confidently recommended
  deleting a 3 GB Alembic cache that an unreadable scene almost certainly
  loads.
- **`.abc` in a cache folder was treated as irreplaceable source.** An
  interchange format means nothing on its own: an Alembic in `models/` is
  bought geometry, one in `alembic/` or `cache/` is an export. A 2.8 GB
  `xpTrail.abc` -- 88% of the whole project -- was marked *keep* on that
  mistake.
- **`$HIP` resolved against the wrong folder.** It was expanded only against
  the scene's own directory, but a project with its scenes in a subfolder
  means `$HIP/tex/x.exr` may mean either `scenes/tex` or the project's `tex`.
  Both readings are now resolved and the disk decides, because a missed
  reference is far worse than a spurious one.
- **Empty folders never appeared.** A `defaultdict` silently omitted every
  folder with no files, so 40 of them in the test project were invisible.
- **The treemap hid them again.** Zero bytes means zero area, so empty folders
  vanished from the layout -- exactly the thing you are looking for. Giving
  them a fake weight produced cells of the right area but 275x8 pixels in
  shape, unreadable and unclickable; they are now laid out separately.
- **Compound folder names matched on any word.** Reading every word of a name
  turned `rendering_notes` into documents and `shot_01_anim` into scenes. Only
  the last word is the noun, and a small set of tails (`cache_old`,
  `render_notes`) are refused outright.
- **A small summary segment was invisible.** 2 MB of backups inside 3.4 GB is
  0.06% -- a third of a pixel -- so the bar implied there was nothing to
  clean. Segments now have a minimum width, paid for pro-rata by the large
  ones.
- **Deselecting inside a selected parent lost a sibling.** Unticking
  `render/v01` inside a selected project removed `render` entirely and never
  re-selected `render/v02`, silently shrinking the selection to less than what
  was asked for.
- **Selecting the whole project totalled zero bytes**, because the root node
  is not among its own descendants.

### Notes on what it deliberately will not do

- Nothing irreplaceable is ever dropped for being unreferenced. Reference
  evidence may only move a verdict *toward* keep.
- Folder-level supersede (`render/v01` next to `render/v03`) applies only to
  renders, comps and caches -- never to source or scenes, where `v01` may hold
  something `v03` does not.
- The scan is read-only, and a test asserts the scanned tree is byte-identical
  afterwards.
