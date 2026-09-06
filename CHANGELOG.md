# Changelog

## 0.4.4 -- 2026-09-06

### Changed

- **Category glyphs removed.** The verdict badges stay; the per-type symbols
  in the Folder column added noise without adding meaning -- the category is
  already named in the detail strip.
- **The detail strip names the scenes that read a folder.** The proven-cache
  reason said "check the Used by column", but that column only exists in the
  file panel on tab 1, so on the findings tab it pointed at something that was
  not on screen. The strip now shows "Read by: <scene names>" directly, with
  the full list on hover, and the reason no longer refers to a column at all.
  A test asserts no reason mentions one.

## 0.4.3 -- 2026-09-06

### Added

- **A detail strip under the findings table.** The "Why" column truncated
  every row, and the reasons are whole sentences -- no column wide enough to
  hold one leaves room for the table. The column now gives the gist and the
  strip gives the complete answer for whichever row has focus: what it is,
  the verdict, size, age, how many files are referenced, the full reason, and
  the full path. Text is selectable, because these are paths people paste
  into a shell.

  A fixed strip rather than a hover popup on purpose: a verdict you have to
  hover to read is a verdict that gets acted on unread.

- **Icons.** A round badge per verdict, marked so the three are told apart
  without relying on colour -- a tick for keep, a question for review, a
  cross for drop -- and a glyph per category in the Folder column. Both are
  painted rather than shipped as image files: they need no assets, scale with
  the font, and cannot go missing from a build.

## 0.4.2 -- 2026-09-06

### Changed

- **A cache now says WHICH of three things it is**, because on a mixed
  Houdini/Cinema 4D project the difference is the whole decision:

  - *Proven* -- a readable scene names it, so it can be re-cooked and the
    Used by column says by what. Drops.
  - *Orphaned* -- every scene was readable and none named it. Whatever made
    it is gone, so "regenerable" may be false. Reviews.
  - *Unverified* -- a scene could not be read, so nothing was checked against
    it. On a C4D project that is every scene. Reviews, and says so.

  Previously the last two collapsed into one "unreferenced" verdict, which is
  what makes a tool untrustworthy on a mixed project: a 40-minute sim whose
  C4D scene cannot be read read exactly like genuine junk.

- **Slow simulations are flagged as slow.** A FLIP, pyro, vellum, RBD or
  crowd cache is regenerable and that is beside the point -- re-running one is
  an afternoon. Those rows now carry "SLOW to re-cook", so Drop never reads as
  "free to lose". Matched on any word in a folder name, so `pyro_sim` and
  `SHOT_v002.RBD_SIM` both catch.

- More simulation folder names recognised: whitewater, spray, foam, bubbles,
  smoke, fire, cloth, crowd.

### Notes

- 229 tests. Verified on a real mixed project (25 readable .hip, 38 unreadable
  .c4d): all three caches proven by a Houdini file, and the two `_SIM` folders
  carrying the slow warning.
- The Cinema 4D asset bridge remains the real fix for the unverified case.

## 0.4.1 -- 2026-09-06

### Fixed

- **Textures were being flagged as backups on their names.** Seen on a live
  project: `leather (32) copy.jpg` and
  `GSG_..._KnittedCheckerFabricWhiteandNavy_preview.jpg` both came back as
  backups -- the second because the hint `_prev` matched inside the word
  `_preview`. Name hints now apply to SCENE files only. A `.hip` called
  `shot_old.hip` really is an old scene and the applications write autosaves
  by mangling the name, but a texture called `leather_old.jpg` is just a
  texture, and reading its name as evidence offered live source material for
  deletion. For assets the FOLDER decides: a backup lives in a folder called
  backup.
- The remaining hints matched anywhere in a name; `_prev` and a few others are
  now matched at the end only, so a marker cannot fire from mid-word.

### Changed

- **Every verdict now carries a reason, and names the category.** A folder
  where everything genuinely dropped came out with an empty "Why" -- the row
  most in need of an explanation. The verdict loop started at Drop and only
  recorded a reason when a safer verdict won. Rows now read
  "Caches — Regenerable by re-cooking the scene."

### Notes

- 222 tests. Verified on the same real project: backup-flagged files fell from
  13 to 11, and the only one outside a backup folder is a `.hip`, which is
  exactly where a name hint should still apply.

## 0.4.0 -- 2026-09-06

Two changes from using it on real projects.

### Added

- **"Used by" column** in the file panel: which scenes actually name a file.
  Knowing something is referenced is much less useful than knowing what would
  break if it went, and that is the question you ask before deleting a cache.
  Direct references, folder references and sequence patterns all attribute;
  the tooltip lists every scene. An empty cell is honest ambiguity -- no
  READABLE scene named it -- not a verdict.

### Fixed

- **`.obj`, `.fbx` and `.mtl` in a cache folder were called caches.** The rule
  that turns geometry into a cache was written for `.abc` and swept these up
  with it. But those are how models ARRIVE -- bought, scanned, or sent by a
  client -- and if the original is gone they cannot be re-exported from
  anything. Only `.abc` and `.usd`, which a DCC writes out in bulk, become
  caches by folder now. A `.mtl` follows its `.obj` rather than its folder.
- Added `.3ds`, `.dae`, `.lwo`, `.step`, `.iges`, `.sldprt`, `.x3d` and `.3mf`
  as imported geometry.

### Notes

- A near miss while doing this: `.blend`, `.ma` and `.mb` were briefly added
  to the geometry list, which shadowed the scene formats and made a project's
  scenes stop being detected entirely. Caught by scanning a real project,
  where the scene count dropped to zero.
- Verified on a real 28,768-file Houdini library: 95 scenes read, and a cache
  sequence correctly attributed to the two scenes sharing it.

## 0.3.2 -- 2026-09-06

A second review of the archive code. 0.3.1 set out to close the "reports
success while incomplete" class of bug and left three instances of it in the
zip path -- so this fixes those, plus three smaller ones.

### Fixed

- **The zip free-space check reserved 10% LESS than the input.** "A zip is
  never larger than its input" is simply false: deflate on already-compressed
  data -- EXR and MOV, which is most of what this archives -- adds a little
  rather than removing any. Measured: 900,000 bytes of incompressible data
  produces a 900,409-byte zip. The check now requires the full size plus
  headroom, so an archive can no longer start and then run out of room.
- **A cancelled zip verified clean.** `testzip()` only checks the CRC of the
  entries that ARE present, so a half-written archive passed. Verification now
  compares the entry list and the stored sizes against the plan, which is what
  makes it a completeness check rather than a corruption check.
- **A cancelled worker still reported to the closed dialog.** Cancelling does
  not stop `finished` being emitted, so an orphaned "Archive stopped" box
  appeared over whatever the user had moved on to, and widget state was
  written to a dead window. The signals are disconnected before cancelling.
- **Verification was skipped after a cancel** -- the case that leaves a
  partial copy behind, and so the one it exists for. It now runs, and reports
  the missing files as a count rather than listing thousands of names that
  restate what the line above already said.
- **The dialog previewed a zip path the write would not use.** After a
  same-day archive it showed `proj_20260906.zip` while the write produced
  `proj_20260906_2.zip`, pointing the user at the file holding the OLDER
  archive.
- **`SKIP_NAMES` was applied only outside staging**, so a `Thumbs.db` in
  `_toDelete` counted toward "leaving behind" while the same file elsewhere
  was excluded -- the mirror image of the undercount fixed in 0.3.1.

### Notes

- 215 tests. The three serious fixes were each verified by running the code:
  a cancelled zip now fails verification, closing mid-copy produces no orphan
  dialog, and a zip is refused when free space is below its input size.

## 0.3.1 -- 2026-09-06

Eight fixes from a code review of the step 6 archive code. The first three
together meant a user could cancel an archive, or have it fail entirely, and
still be told it succeeded -- dangerous in a tool whose next step deletes the
source.

### Fixed

- **Archiving into the project's PARENT wrote over the live project.** The
  guard checked the folder you chose, but the copy writes to
  `<destination>/<name>`, and for `C:/Work/Proj` into `C:/Work` that resolves
  straight back onto the source. Every file failed with a sharing violation
  while the module claimed never to touch the original. The check now tests
  the resolved target, not the chosen folder.
- **Close did not stop a running copy.** Cancellation hung off `closeEvent`,
  but Close called `reject()`, which raises no close event -- so the copy kept
  running against a dead window with nothing waiting on it. Both routes now go
  through one handler that confirms, cancels, and waits for the worker.
  Verified: stopped at 101 of 400 files with nothing written afterwards.
- **A cancelled archive reported success.** Breaking out of the loop returned
  an empty `failed` list, so a clean run and a cancelled one were
  indistinguishable. Cancellation is now an explicit flag on the plan, and the
  dialog says the copy is partial.
- **Partial archives overstated what arrived**, pairing the real copied count
  with the planned total. Reported bytes are now summed from the files that
  actually copied.
- **Verification was skipped when every file failed** -- exactly the case the
  checkbox exists to catch.
- **A second zip of the same project on the same day silently destroyed the
  first**: a date-only stamp opened in mode `"w"`. A numbered suffix is added
  when the name is taken.
- **The free-space check blocked zips that would fit**, demanding the full
  uncompressed size for an archive that is never larger than its input.
- **`SKIP_DIRS` pruning applied inside `_toDelete`**, so a `__pycache__` in
  there was dropped from `skipped_bytes` -- the same undercount the staging
  branch was written to avoid.

### Notes

- 207 tests, 15 of them new and each pinned to one of the findings above.

## 0.3.0 -- 2026-09-06

Step 6, and with it the whole wizard. Archiver now takes a project from
"what is in here?" to a verified copy at its archive home.

### Added

- **Archive.** Copies the project to a destination as either a plain folder
  mirror or a single zip -- your choice at run time. It COPIES, never moves:
  the original survives an interrupted archive, which is the opposite trade
  from staging, where a same-filesystem move was the safe one.
- `_toDelete` is excluded, and its size reported, so the dialog can say what
  is being left behind rather than silently dropping it.
- **Everything refusable is checked before a byte moves** -- a destination
  inside the project (which would copy the archive into itself until the disk
  filled), the project itself, an empty project, and not enough free space.
  The size, file count and any objection are all on screen before you start.
- **Verify afterwards**, on by default: every file's size is compared at the
  destination, and a zip is tested by reading it back. Not a checksum --
  hashing 200 GB doubles the time, and the failure worth catching is a
  truncated or missing file, which a size comparison catches.
- Copies preserve mtimes, so an archive still looks like the project rather
  than like the day it was archived.

### Fixed

- **The "leaving behind" figure counted only the manifest.** Pruning the walk
  at the top of `_toDelete` meant `os.walk` never descended into it, so a
  staged 500 MB cache was reported as a few hundred bytes.

### Notes

- Measured on the 3.4 GB test project: a folder copy takes **3 seconds**, a
  zip takes **99** and saves 9%. EXR and MOV data barely compresses. The
  dialog says so before you choose, rather than after a silent wait.
- 192 tests.

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
