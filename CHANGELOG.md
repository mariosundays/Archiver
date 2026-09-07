# Changelog

## 0.8.0 -- 2026-09-07

### Added

- **"Never delete" marks, on folders AND files.** Right-click anything in the
  tree or the findings tab and mark it keep-forever. A verdict is what the
  scan worked out; a mark is what you KNOW, and it outranks the scan
  permanently -- so it does not overwrite the verdict, which would lose why
  the thing looked droppable in the first place.

  Saved to `.archiver_protected.json` beside the project, as RELATIVE paths,
  so marks survive rescans, restarts and reinstalls, and keep working when
  the project is moved or renamed. A marked folder covers everything under
  it; a marked file covers exactly itself, which is the case folder-only
  marks cannot express -- one irreplaceable file in an otherwise disposable
  folder.

  Enforced in two independent places, on purpose: the selection will not tick
  a protected thing, and staging refuses it again having read the marks off
  disk itself. A protection that only greyed out a checkbox would be a
  suggestion.

- **Shift-click and drag-to-paint on the checkboxes.** Shift-click a box to
  fill the range from the last one you touched; press and drag across boxes
  to paint them all to the state of the first. Both work on the visible order
  and leave collapsed branches alone -- a range that silently ticked things
  hidden inside a folded branch would be a selection nobody could check
  before approving it.

### Fixed

- **Staging a folder used to move a protected file inside it.** Folders are
  moved whole, so checking only the path handed to `stage()` let a mark
  deeper down travel with its parent -- protection bypassed silently, which
  is the one outcome it exists to prevent. Both the subtree and the path
  itself are checked now, and the refusal names the mark responsible.
- "Tick all Drop" skips anything staging would refuse, rather than queueing
  failures for approve time.

## 0.7.1 -- 2026-09-07

### Added

- **Selecting a folder in the tree lists its files in the panel below.**
  Before this the panel could only be opened by double-clicking a bar
  segment, so clicking through the tree was a dead end -- the tree and the
  bars are two ways of asking about the same rows, and only one of them
  could reach the answer.

- **"Limit to selected folder", in the panel header.** The bars ask WHAT (a
  category or a verdict) and the tree asks WHERE (a folder); this decides
  whether the two compose. Off, a bar segment answers for the whole project
  as before. On, it answers only for the selected folder and everything
  under it -- and moving the selection re-asks the same question somewhere
  else, so a standing filter follows you around the tree.

  Scope matches on whole path segments, so selecting `E_OUTPUT` never
  swallows a sibling called `E_OUTPUT_OLD`.

### Changed

- The panel keeps the QUESTION rather than a finished list, so any change of
  scope re-answers it instead of going stale.
- An empty result now says why -- "Nothing with that verdict in E_OUTPUT" --
  rather than showing a bare empty table, which reads as a broken panel.
- Closing the panel forgets the standing filter, so the next folder click
  does not silently re-open it on a question you just dismissed.

## 0.7.0 -- 2026-09-07

### Changed

- **"A newer version exists" now means different things for different kinds
  of file.** It used to force DROP for every category, which offered scenes,
  textures, deliveries and briefs for deletion purely for carrying a version
  number -- and in the case of source material broke the tool's own cardinal
  rule, that nothing irreplaceable is dropped for being unreferenced. The
  folder-level rule had always been careful here; the file-level one was not,
  and they contradicted each other.

  What each category does with a newer version now:

  | Category | Older version | Why |
  |---|---|---|
  | Renders | **drop** | Dead weight, and usually the biggest reclaim in a job. |
  | Caches | **drop**, if proven | Only when a readable scene names it, so it genuinely re-cooks. Otherwise review. |
  | Dailies / comps | **review** | A v001 cut is a record of what was shown on a date, not a draft. Your call. |
  | Scenes | keep | Every version is kept. shot_v001.hip is the only record of how the shot looked then. |
  | Source / geo | keep | A tex_v01 may hold a map tex_v03 does not. Unrecoverable. |
  | Deliveries | keep | What shipped, shipped. |
  | Docs | keep | A superseded brief is a few KB of history. |
  | Backups | drop | Already disposable. The version is irrelevant, and the reason now says so honestly rather than blaming it. |

  On the WhiskeyBottle job this moves 6 folders and 1.4 GB of dailies out of
  Drop and into Review, where they wait to be ticked rather than being
  offered up.

### Fixed

- **Superseded no longer inflates confidence where it carries no verdict.**
  `drop_signals` counted "a newer version sits alongside it" for every
  category, so a scene or texture could reach STRONG on evidence that did not
  support its verdict.

## 0.6.5 -- 2026-09-07

### Fixed

- **The drill-down panel kept the PREVIOUS project's files after a rescan.**
  Scanning a new project rebuilt the tree, the strips, the findings and the
  summary, but the panel under the tree is only ever filled by a double-click,
  so no refill path touched it -- it stayed open beneath the new project's
  tree, still listing the old one's files under a header reading "Drop
  folders -- 1.4 GB in 559 files" while the summary above said "Drop 0 B".
  It mattered because those rows carry real paths and a Show in Explorer:
  the panel was inviting decisions about a job that had already been
  archived. It is now emptied and closed on every scan -- closed rather than
  refilled, because the bar segment that opened it may not exist in the new
  project. Every mutating action (prune, stage, restore) rescans, so all of
  them are covered.

### Changed

- **The style is applied by `main.apply_style(app)` instead of inline in
  `main()`.** A screenshot rig that built a window without going through
  `main()` missed the pinned palette and rendered the Windows accent over
  the size bars -- the exact bug 0.2.x fixed, resurrected as a false alarm.
  Anything that builds a window can now apply the real style.

## 0.6.4 -- 2026-09-06

### Changed

- **The Why column is short now.** Every reason carries two forms: a few
  words for the column and the full argument for the detail strip and
  tooltip. The old single form ran to 70 characters -- "Comp / flipbooks —
  Superseded -- a higher version of this folder exists alongside it" -- of
  which the first half repeated the category the row already showed and the
  rest was truncated away. Rows now read "a newer version exists",
  "re-cookable", "orphaned — no scene reads it".

- **The detail strip and the selection bar belong to the window, not to a
  tab.** Both describe the same selection, and having them appear and vanish
  as you switched tabs meant the reason for a row was only readable on one of
  the two places that shows rows.

### Fixed

- **The Why column could not be resized.** It was set to Stretch, and Qt
  locks a stretched section so the divider beside it will not drag. Every
  column is Interactive with `setStretchLastSection` filling the leftover
  width, so all of them resize.

## 0.6.3 -- 2026-09-06

### Added

- **The headline shows what the project WAS against what it is now**, once
  anything has been staged: "was 17.0 GB → now 12.7 GB (4.3 GB already set
  aside)". The plain total answers the wrong question after a round of
  cleaning -- it says how big the project is, when what you want is how much
  you have taken off it and how much further you could go. Both numbers were
  already known; they are now side by side rather than arithmetic.

- The staging note no longer repeats the size that is in the headline. It
  says what to DO instead: delete the folder when satisfied, or restore.

## 0.6.2 -- 2026-09-06

### Fixed

- **The drill-down panel and the findings tab described the same folders
  differently.** Double-clicking a Drop or Review segment gave a bare list --
  file, size, folder, age -- while the findings tab showed the verdict, the
  confidence and the reason for exactly the same folders. The same question
  had two different answers depending on where it was asked, which is how a
  tool stops being trusted.

  The panel now carries Verdict, Confidence and Why, matching the findings
  tab, and is sortable like it. Every file entry keeps a back-reference to
  its FolderReport so the verdict travels with it.

## 0.6.1 -- 2026-09-06

### Fixed

- **The confidence words were invisible.** They were appended to the end of
  the reason, which put them past where the Why column truncates -- so every
  STRONG was computed correctly and never shown. Confidence now has its own
  column, coloured by strength, with the signals in its tooltip and spelled
  out in full in the detail strip.

### Added

- **Click a column header to sort**, on both the findings table and the
  overview tree. Sizes, file counts, verdicts, confidence and age sort by
  VALUE, not by their text -- "1.9 GB" would otherwise sort above "293.2 MB"
  because "1" precedes "2", and a size column that lies about order is worse
  than no sorting at all.

## 0.6.0 -- 2026-09-06

### Fixed -- an entire project of dailies had no detectable version

- **A version with more name after it was invisible.** `VERSION_RE` ended in
  ``, which never matches between "2" and "_" because underscore is a word
  character -- so `ROD_WHISKEY_BOTTLE_SH050_v006_SH050` parsed as having NO
  version. On a real project that meant 13 shot folders, 1.4 GB of superseded
  dailies, were never seen as superseded at all.
- **Version folders were grouped by parent alone.** Once the versions were
  visible, all seven shots in one `SEQUENCES/` folder pooled together, so
  `SH070_v001` -- the only version of that shot -- was compared against
  `SH050_v006` and would have been called superseded. Grouping is now by
  (parent, versionless stem), which is what says two folders are versions of
  the SAME thing.

### Added

- **Confidence on every Drop**, as a word and the signals behind it:
  "STRONG -- 2 signals agree: a newer version sits alongside it; it is
  output, re-makeable from the scene."

  Deliberately not a percentage. A number like "87% likely unused" would be
  invented -- there is no calibration data behind it -- and false precision on
  a tool that deletes things invites acting without checking. Each signal is
  instead a claim you can go and verify.

### Notes

- Verified on a real project (176_Omnicom_WiskeyBottle): every older shot
  version drops with STRONG confidence, every newest version reviews, and the
  single-version shot is untouched.
- 327 tests.

## 0.5.0 -- 2026-09-06

### Added

- **Cinema 4D asset export — the `.c4d` blind spot is closed.** Modern `.c4d`
  is a proprietary compressed container with not one asset path in plaintext,
  so Archiver could read nothing from it. On a real 14 GB job that meant **38
  of 63 scenes were unreadable**, every cache in the project reported as
  UNVERIFIED, and no way to tell a re-cookable sim from a 3 GB `.abc` that a
  scene still needs.

  Cinema 4D knows the answer even though the file will not say it, so it now
  writes it down. `c4d_plugin/ArchiverExport` adds **Extensions → Archiver
  Asset Export**, which dumps each scene's asset list to a JSON sidecar beside
  the scene; the scanner reads that instead of scraping.

  ```
  shot_010.c4d
  shot_010.c4d.assets.json
  ```

  Three scopes: this scene, every scene in its folder, or every scene under a
  chosen project folder. A batch opens and closes each scene in turn, so a
  63-scene job is one unattended pass. Install with
  `c4d_plugin/sync_to_c4d.ps1`, then restart C4D.

  Verified end to end against the real project's own opaque scene bytes: a
  cache that read *"UNVERIFIED — a scene here could not be read"* becomes
  *"Regenerable — a scene in this project reads it, so it can be re-cooked"*,
  naming the scene in the Used by column.

- **One sidecar per scene, not one index per project.** Staleness becomes a
  per-scene fact that can actually be checked, the data travels with a scene
  that gets copied elsewhere, and re-exporting one scene does not rewrite the
  other sixty-two.

- **A stale sidecar is evidence, not truth** — the safety rule the whole
  feature rests on. A scene saved since its export may have gained a cache the
  list does not name. So a stale sidecar's paths still protect what they name
  (that direction cannot lose data), but the scene stays counted as unreadable
  and **nothing is promoted to Drop on old evidence**. A cache added since the
  export therefore stays REVIEW rather than being confidently dropped — which
  is exactly the failure that would delete live work.

  Staleness is checked two ways, because either alone has a hole. The recorded
  scene mtime catches a scene *rolled back* to an older version — older than
  its sidecar, so a file-time comparison alone would wrongly call it fresh.
  The file comparison catches a sidecar copied in from another machine whose
  recorded mtime happens to match.

- Review screen and report **split the warning in two**: how many scenes could
  not be read at all, and how many have been saved since their export. Both
  now name the fix instead of only stating the problem. `stale_sidecars` is in
  the JSON report.

### Notes

- **A malformed or truncated sidecar reads as absent, never as empty.** Those
  mean opposite things — "no evidence" versus "this scene references nothing"
  — and confusing them makes every cache in the project look orphaned. The
  sidecar is written to a temp file and moved into place for the same reason.
- **The plugin is a thin shell over tested code.** Claude cannot drive C4D's
  UI or read its console, so every decision worth getting wrong lives in
  `core/c4d_assets.py` and `core/sidecar.py` — plain modules with tests. The
  `.pyp` is exercised too, by executing it against a stand-in `c4d` module:
  that it loads, that a document's assets reach a sidecar, that one corrupt
  scene in sixty does not stop the run and every document is still closed.
- **`sync_to_c4d.ps1` copies Archiver's own `core/` modules** rather than
  shipping a rewritten copy, so the writer and the reader cannot drift. That
  drift is a live problem in the Iris bridge, whose hand-maintained copy of a
  pattern list has fallen out of step with the original.
- 313 tests (was 243).

## 0.4.6 -- 2026-09-06

### Added

- **Every scan drops `.archiver_report.json` at the project root.** A record
  of what the project held and why each folder was judged as it was, living
  with the project rather than only in a window that gets closed. Leading dot
  so it stays out of the way; hidden on macOS and Linux.

  It is written by an explicit call AFTER the scan, never by the scan itself,
  so "scanning costs you nothing" stays true and stays testable -- a test
  asserts a scan alone writes no report.

  Written to a temporary file and moved into place, so an interrupted write
  cannot replace a good report with a truncated one. A failure is reported in
  the status bar and never interrupts.

- The report **travels with an archive** rather than being skipped as junk:
  it is exactly what someone opening the archive in two years wants to find.

### Notes

- The report is excluded from the scan itself, so it does not report on
  itself or grow the file count by one every run.
- 243 tests.

## 0.4.5 -- 2026-09-06

### Fixed

- **`_toDelete` was being scanned like any other folder.** It holds decisions
  already made, so re-scanning it re-judged settled choices, inflated every
  total, and put the staging folder in the report -- on a real project it
  appeared as a 2.8 GB row marked *Keep*, which is exactly backwards for
  files chosen for removal.

  The walk now skips it and measures it instead. The scan reports
  `staged_bytes` and `staged_files` separately, and the window says "2.8 GB in
  10 files is staged in _toDelete, waiting for you to delete or restore it.
  It is not counted above."

  On the test project the reported size fell from 16.9 GB to 14.1 GB, which
  is the live project rather than the project plus its own discard pile.

- The manifest is excluded from the staged count -- it is Archiver's own
  bookkeeping, not the user's data.

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
