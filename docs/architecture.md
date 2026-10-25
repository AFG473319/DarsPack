# DarsPack Architecture (Phase B)

Status: **working v0.1** — core, desktop UI, LAN server + phone client, and the Windows build are implemented; 66 tests green (2026-10-24). Now in a real-use bug-fixing phase (the built exe is dogfooded and reports crashes via the in-app error dialog).
Stack and platform constraints are locked and documented below.

## 1. Design principles

1. **Offline-first, single user.** Nothing requires a network except the explicitly enabled LAN share.
2. **App-owned library (the Zotero/calibre model).** Files are *copied* into DarsPack's own folder at import time; the original is never touched. Organization lives in the database, not in folder trees.
3. **Flag, never touch.** Duplicates and conflicts are reported; no automatic deletion or overwrite, ever.
4. **Explainable in one sitting.** Every module is one concept; no clever tricks; the *why* is commented.
5. **Persian-first.** RTL everywhere; Persian/Latin digits accepted; ی/ي and ك/ک normalized; Jalali school years.

## 2. Module map

```
src/darspack/
├── core/                 # pure logic: no UI, no network → 100% unit-testable
│   ├── normalize.py      # Persian text + filename normalization, digit handling     
│   ├── db.py             # SQLite schema creation, migrations, row helpers           
│   ├── library.py        # Library: paths, seed subjects, health check, open/create  
│   ├── hashing.py        # streaming SHA-256 + progress callback                     
│   ├── importer.py       # copy-in + hash + import-time dedup + metadata suggestion  (uses the modules above)
│   ├── dedup.py          # duplicate groups + conflict rules R1–R3 + likely versions 
│   ├── search.py         # normalized multi-token search over the catalog            
│   ├── manifest.py       # درس‌پک manifest build + package export/verify/read        
│   ├── backup.py         # full-library backup ZIP (catalog snapshot + files)        
│   └── schoolyear.py     # Jalali school-year helpers (Mehr→Shahrivar span)          
├── ui/                   # PySide6 desktop client
│   ├── app.py            # QApplication wiring, language toggle, theme, fonts
│   ├── main_window.py    # library table, filters, search, empty states, row
│   │                     #   delete → files/.trash, share toggle, history/stats
│   ├── dialogs.py        # ALL dialogs in one file: classify (bulk actions,
│   │                     #   teacher/lesson/year, package prefill), metadata,
│   │                     #   export, verify, duplicates, settings, share (QR),
│   │                     #   history, stats
│   └── workers.py        # background import thread (own DB connection;
│                         #   carries درس‌پک manifest metas + subject/tags prefill)
├── web/                  # LAN web client + server
│   ├── server.py         # stdlib ThreadingHTTPServer, PIN gate, endpoints           
│   ├── sync.py           # manifest/diff logic shared with packaging                 
│   └── client/           # static RTL HTML/CSS/JS — no build step, no framework
└── i18n.py               # fa/en string dictionaries (plain dicts, no Qt Linguist)
tests/                    # one test file per core module
eval/make_testset.py      # generates the labelled synthetic set from eval/benchmark-plan.md
```

⚖️ Module count is deliberately small; merge/split only with the maintainer's approval.

## 3. Data model (SQLite, normalized)

```sql
CREATE TABLE subjects (      -- درس‌ها
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,             -- display name, e.g. «ریاضی»
  normalized TEXT NOT NULL UNIQUE        -- normalize(name), used for matching
);
CREATE TABLE teachers (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  normalized TEXT NOT NULL UNIQUE
);
CREATE TABLE files (
  id INTEGER PRIMARY KEY,
  stored_name TEXT NOT NULL DEFAULT '',     -- inside library: files/000123.pdf
  original_name TEXT NOT NULL,           -- as imported, never altered
  name_norm TEXT NOT NULL,               -- match key of original_name (search/conflicts)
  size_bytes INTEGER NOT NULL,
  sha256 TEXT NOT NULL,                  -- indexed; the dedup key
  imported_at TEXT NOT NULL,             -- ISO datetime
  subject_id INTEGER REFERENCES subjects(id),
  teacher_id INTEGER REFERENCES teachers(id),
  chapter INTEGER,                       -- فصل, nullable
  lesson INTEGER,                        -- درس, nullable — separate from فصل
  school_year TEXT,                      -- e.g. '1405-1406' (Mehr→Shahrivar span)
  kind TEXT CHECK (kind IN ('جزوه','نمونه‌سوال','کاربرگ','تکلیف','سایر')),
  note TEXT DEFAULT '',
  available INTEGER NOT NULL DEFAULT 1   -- 1 = present; the startup health check flips to 0
);
CREATE INDEX idx_files_sha ON files(sha256);
CREATE INDEX idx_files_name_norm ON files(name_norm);
CREATE TABLE tags (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, normalized TEXT NOT NULL UNIQUE
);
CREATE TABLE file_tags (
  file_id INTEGER REFERENCES files(id) ON DELETE CASCADE,
  tag_id INTEGER REFERENCES tags(id) ON DELETE CASCADE,
  PRIMARY KEY (file_id, tag_id)
);
CREATE TABLE activity_log (  -- user log: what the user did, when
  id INTEGER PRIMARY KEY, ts TEXT NOT NULL, action TEXT NOT NULL, detail TEXT DEFAULT ''
);
CREATE TABLE hint_rules (    -- learned token→subject memory (A4): pre-fill only
  token TEXT PRIMARY KEY, subject_id INTEGER REFERENCES subjects(id),
  hits INTEGER NOT NULL DEFAULT 0, last_used TEXT NOT NULL
);
```

**Schema versions:** the schema carries `PRAGMA user_version`. On every open, `db.migrate()` runs ordered migration steps (each in its own transaction, version bumped after success) — migration 1 added the `lesson` column to catalogs created before درس and فصل became separate columns. Fresh installs create the current shape directly.

Storage layout (⚖️ flat, no subject folders — the catalog *is* the organization; avoids renames/invalid chars):

```
<library root, default Documents\DarsPackLibrary, user-relocatable>
├── catalog.db
└── files/000001.pdf, 000002.docx, …     # id + original extension only
```

Import is crash-safe: copy to `files/tmp_…` → verify size → atomic rename → single DB transaction → activity-log entry.

## 4. Core algorithms

### 4.1 Normalization 
`normalize(s)`: map ي→ی, ك→ک, Arabic → Persian digits (and accept Latin), collapse ZWNJ-adjacent whitespace for matching (keep ZWNJ in display), strip diacritics, casefold Latin. Applied to: names, tags, subjects, search queries. Tests are a data table of input→expected pairs.

### 4.2 Filename heuristic 
Parse common Persian school patterns to *suggest* (never auto-apply without the import-review step): subject from a fixed list — canonical names only, e.g. «علوم تجربی» (the official textbook name), matched longest-first so the longer name always wins; chapter from «فصل ۳/فصل سه» into `chapter` and «درس ۳» into the separate `lesson` column; kind from keywords (نمونه سوال/سوالات/تست/بانک سوال→نمونه‌سوال، جزوه/مرور/جمع بندی/فرمول، کاربرگ، تکلیف/تمرین); grade word (نهم/هشتم/هفتم) as a display hint. The heuristic returns plain values, no confidence score — the review dialog is where the user reviews and confirms them.

**Import flow (revised 2026-10-24 — a deliberate architectural decision): categorizing is the app's main job, so the app asks.** Import copies + hashes + dedups silently, then a **classification review dialog** opens for every newly imported file, pre-filled from the filename heuristic — the user confirms or fixes subject/chapter/lesson/kind. The importer itself applies only chapter/lesson/kind hints; the **subject is never auto-applied**, so any file the user hasn't classified counts as unclassified. Unclassified files stay visible: a «بدون درس» filter in the subject dropdown plus a status-bar count keeps nudging until the catalog is complete. Phone uploads (no dialog on the phone) land unclassified and are completed on the desktop through the same filter.

**Library startup (open):** create tables → run migrations → seed the default subject list (only when the subjects table is empty, so an existing library is never touched) → sweep crash leftovers → **health check**: stat every stored file; missing or size-changed files get `available=0` (healed back to 1 once the file is restored). One stat per file — the full re-hash stays in package verify, on demand. A learned token→subject memory (`hint_rules`) feeds extra pre-fills to the heuristic once the user has confirmed the same token→subject pair twice; it changes suggestions only, never stored metadata.

### 4.3 Duplicate & conflict rules (core algorithm)
- **R1 — exact duplicate:** same `sha256`. Grouped; UI shows groups and total wasted bytes.
- **R2 — version conflict:** same normalized `original_name`, different `sha256` → «نسخه‌های متفاوت با نام یکسان» — flagged.
- **R3 — rename hint:** same `sha256`, different normalized names → «یک محتوا با نام‌های مختلف».
- **R4-lite — likely versions:** names differing only by re-download noise («x (1).pdf», «نسخه نهایی», «final», «v2») with different content → «نسخه‌های احتمالی» — a weak hint, flag-only; false positives are acceptable because nothing acts on the group automatically.
- Import-time check: an arriving sha256 that already exists is reported immediately — naming the file it duplicates («تکرارِ «X» است») — and skipped unless the user explicitly chooses «با وجود این نگه دار».

### 4.4 Search 
The query is normalized, split into tokens (a «فصل ۵»/«درس ۳» phrase stays atomic), and the tokens are AND-ed: every token must match somewhere among the filename, subject name, tags, the note, or the kind — and a فصل/درس phrase also matches the structured chapter/lesson columns, so classified files are found regardless of their filename. Ranking: a prefix match on the first token beats a contains match; ties by recency. Queries are capped at 8 tokens (a pasted paragraph can never hang the search). **Documented limitations:** the note is matched as stored (no `note_norm` column yet — typing-style differences inside a note don't match), and search covers names and metadata only — not the text *inside* PDFs (FTS5+Persian tokenization is future work).

### 4.5 درس‌پک package format v1 

```
package.zip
├── manifest.json    # {"format":"darspack-package","version":1,"created":"…",
│                    #  "files":[{"path":"files/000012.pdf","name":original,
│                    #            "sha256":"…","size":123,"subject":"ریاضی",
│                    #            "chapter":3,"lesson":null,"school_year":"…",
│                    #            "kind":"نمونه‌سوال","tags":[…]}]}
├── index.html       # offline RTL browsable index of the contents (works on any
│                    #  device with a browser — the package explains itself)
└── files/…
```
`verify(zip)`: for each manifest entry — member exists? size matches? recomputed SHA-256 matches? — producing an exact missing/corrupt list. Never repairs. The manifest's own SHA-256 is shown at export time for out-of-band comparison. `sync.py` reuses the same file-list/diff logic for the LAN protocol. Importing a package round-trips its metadata: chapter/lesson/kind/school_year are applied like import suggestions, while subject/tags come back as pre-fill for the classification dialog — never auto-applied. A full-library backup is the same package plus the catalog snapshot (`catalog.db`) and a restore guide; verify whitelists those two backup members.

### 4.6 Jalali school year
`school_year(jdate) → '1405-1406'` (Mehr 1 starts a year). Tests: year boundary on 1 Mehr, leap Esfand 29 (1399/1403), late-Shahrivar files.

## 5. Threading model (keeps the UI responsive)

- Import/hash: `QThreadPool` worker per batch, progress signals → progress bar; UI never blocks.
- Web server: its own `ThreadingHTTPServer` thread, started/stopped by the share toggle.
- SQLite: one connection per thread, WAL mode; writes serialized by a single `threading.Lock`. Simple, explainable, sufficient for one user.

## 6. LAN web client & sync (opt-in)

- **Server:** stdlib `http.server.ThreadingHTTPServer`, bound to all interfaces *only while* «اشتراک‌گذاری در شبکه» is on; off by default; never exposed beyond the LAN.
- **Auth:** 6-digit random PIN generated per session, shown in the desktop UI; every `/api/*` call requires it; `hmac.compare_digest` comparison; 5 failed attempts per IP → 30 s lockout. Plain HTTP on LAN is a documented limitation (no TLS on LAN; threat model = casual classmates, not attackers).
- **Endpoints:** `GET /` (RTL client), `GET /api/manifest` (catalog JSON), `GET /api/search?q=`, `GET /api/file/<id>` (download), `POST /api/upload?name=&subject=` with **raw body** (no multipart — avoids deprecated `cgi`; the browser client sends a File blob as the request body).
- **Model: hub-authoritative.** The phone browses/searches, downloads what it needs, and uploads picks which flow through the *same* importer (hash → dedup → suggestion → activity log). Full two-way device sync and offline PWA caching are documented v2.
- Demo fallback for isolated school Wi-Fi: phone hotspot with the laptop joined.

## 7. Internationalization
`i18n.py`: two plain dicts (`fa`, `en`) + `tr(key)`; language toggle in settings. The desktop app is fully bilingual; the **web client is Persian-only** (v1 scope — its classmates are Persian speakers, and one static RTL page needs no string table). Qt Linguist rejected — overkill, harder to explain (⚖️).

## 8. Security boundaries
No secrets exist pre-cloud (none stored, none asked). No telemetry, no auto network. Library and DB are user files; the only "protection" is OS user accounts. Cloud (if ever) = OAuth read-only + OS keyring, decided in the final days at the earliest.

## 9. Test strategy
| Test file | Covers |
|---|---|
| test_normalize.py | the normalization table; ي/ی, ك/ک, ZWNJ, ۰-۹/0-9, mixed |
| test_schoolyear.py | Mehr boundary, leap Esfand, Shahrivar tail |
| test_importer.py | copy-in, crash-safe rename, dedup-at-import, per-file error containment |
| test_dedup.py | R1/R2/R3 on the planted-labelled fixture set |
| test_manifest.py | export→verify round-trip; tamper (one flipped byte → exact file named); missing member |
| test_search.py | normalized matching, Persian/Latin digit queries, ranking, unclassified filter |
| test_classify.py | the classification flow: prefill from the heuristic / a package manifest / learned hints, bulk apply, teacher/lesson/year fields, unclassified tracking |
| test_server.py | PIN gate, lockout, upload→importer path, manifest endpoint, per-thread libraries |
| test_sync.py | catalog manifest + the pure diff |
| test_worker_errors.py | the import worker ALWAYS emits done; one bad file never hangs the UI |
| test_ui_dialogs.py | every dialog constructs offscreen; metadata/classify save paths; QR SVG; stats; history; button-wiring guards |
| test_web_client.py | phone client: JS parses (`node --check`), every `$('id')` exists, no implicit globals |

Lessons learned while dogfooding (all now test-enforced): background threads must always report completion even on failure; SQLite connections stay on their creating thread (server uses per-thread connections); Qt's `clicked` passes `checked` to plain-function slots (wire zero-arg lambdas); the browser client must not rely on implicit id-globals.

Every reported performance number (startup, RAM, export/verify time) is measured on the target laptop by an `eval/` script.

## 10. Trade-offs (chosen → rejected)

| Choice | Rejected | Why |
|---|---|---|
| stdlib `http.server` | Flask/aiohttp | zero new deps; 1–5 LAN clients don't need async |
| Flat `files/000123.ext` | subject folders | catalog is the organizer; avoids renames/invalid paths |
| `LIKE` search | SQLite FTS5 | Persian tokenization is weak; honest limitation instead |
| dict i18n | Qt Linguist | explainable in one sentence |
| raw-body upload | multipart | `cgi` is deprecated/removed; one less parser |
| QThreadPool hashing | single-thread | keeps the UI responsive with real speedup on large PDFs |
| PyInstaller onedir + Inno | onefile exe | faster startup, smaller installer — measure both before deciding |
