// SQLite schema and connection helpers (پایگاه داده).
//
// Port of Windows `core/db.py`. The schema is copied VERBATIM — same
// tables, columns and indexes as the Windows catalog, so a catalog.db
// written by either app opens in the other. WAL mode, foreign keys ON,
// `PRAGMA user_version = 1` (migration 1 added the `lesson` column).

import 'package:path/path.dart' as p;
import 'package:sqflite/sqflite.dart';

import 'normalize.dart';
import 'suggest.dart';

/// The full schema, verbatim from Windows `core/db.py` (SCHEMA).
const String schema = '''
CREATE TABLE IF NOT EXISTS subjects (
  id          INTEGER PRIMARY KEY,
  name        TEXT NOT NULL UNIQUE,
  normalized  TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS teachers (
  id          INTEGER PRIMARY KEY,
  name        TEXT NOT NULL,
  normalized  TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS files (
  id           INTEGER PRIMARY KEY,
  stored_name  TEXT NOT NULL DEFAULT '',
  original_name TEXT NOT NULL,
  name_norm    TEXT NOT NULL,
  size_bytes   INTEGER NOT NULL,
  sha256       TEXT NOT NULL,
  imported_at  TEXT NOT NULL,
  subject_id   INTEGER REFERENCES subjects(id),
  teacher_id   INTEGER REFERENCES teachers(id),
  chapter      INTEGER,
  lesson       INTEGER,
  school_year  TEXT,
  kind         TEXT CHECK (kind IN ('جزوه','نمونه‌سوال','کاربرگ','تکلیف','سایر')),
  note         TEXT DEFAULT '',
  available    INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_files_sha       ON files(sha256);
CREATE INDEX IF NOT EXISTS idx_files_name_norm ON files(name_norm);
CREATE TABLE IF NOT EXISTS tags (
  id         INTEGER PRIMARY KEY,
  name       TEXT NOT NULL,
  normalized TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS file_tags (
  file_id INTEGER REFERENCES files(id) ON DELETE CASCADE,
  tag_id  INTEGER REFERENCES tags(id)  ON DELETE CASCADE,
  PRIMARY KEY (file_id, tag_id)
);
CREATE TABLE IF NOT EXISTS activity_log (
  id     INTEGER PRIMARY KEY,
  ts     TEXT NOT NULL,
  action TEXT NOT NULL,
  detail TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS hint_rules (
  token      TEXT PRIMARY KEY,
  subject_id INTEGER REFERENCES subjects(id),
  hits       INTEGER NOT NULL DEFAULT 0,
  last_used  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS import_skips (
  id            INTEGER PRIMARY KEY,
  ts            TEXT NOT NULL,
  sha256        TEXT NOT NULL,
  size_bytes    INTEGER NOT NULL,
  original_name TEXT NOT NULL
);
''';

/// Schema version: migration 1 added the `lesson` column.
const int schemaVersion = 1;

/// Open the catalog with the Windows pragmas (WAL, foreign keys ON).
///
/// Seeding is NOT done here — call [seedSubjects] after opening, or use
/// [openCatalog] which does the full open sequence.
Future<Database> openDatabaseAt(String dbPath) async {
  return openDatabase(
    dbPath,
    version: schemaVersion,
    onConfigure: (db) async {
      await db.execute('PRAGMA journal_mode=WAL');
      await db.execute('PRAGMA foreign_keys=ON');
    },
    onCreate: (db, version) async {
      await _execSchema(db);
      await db.execute('PRAGMA user_version = 1');
    },
    onUpgrade: (db, oldVersion, newVersion) async {
      // Migration 1: add the `lesson` column to catalogs created by an
      // older build (guarded, so it is safe on fresh catalogs too).
      if (oldVersion < 1) {
        final cols = await db.rawQuery('PRAGMA table_info(files)');
        final names = {for (final c in cols) c['name'] as String};
        if (!names.contains('lesson')) {
          await db.execute('ALTER TABLE files ADD COLUMN lesson INTEGER');
        }
        await db.execute('PRAGMA user_version = 1');
      }
    },
    onOpen: (db) async {
      await _execSchema(db);
      // A catalog copied in from Windows (or an older build) may predate
      // the lesson column even though its user_version is already 1;
      // the guarded ALTER below keeps such catalogs opening.
      final cols = await db.rawQuery('PRAGMA table_info(files)');
      final names = {for (final c in cols) c['name'] as String};
      if (!names.contains('lesson')) {
        await db.execute('ALTER TABLE files ADD COLUMN lesson INTEGER');
      }
      await db.execute('PRAGMA user_version = 1');
    },
  );
}

Future<void> _execSchema(DatabaseExecutor db) async {
  for (final statement in schema.split(';')) {
    final sql = statement.trim();
    if (sql.isEmpty) continue;
    await db.execute(sql);
  }
}

/// Pre-fill the subjects table on a brand-new library only.
///
/// An existing library is never touched: the user's own subjects are
/// authoritative.
Future<void> seedSubjects(Database db) async {
  final count = Sqflite.firstIntValue(
    await db.rawQuery('SELECT COUNT(*) FROM subjects'),
  );
  if (count != null && count > 0) return;
  await db.transaction((txn) async {
    for (final name in defaultSubjects) {
      await getOrCreate(txn, 'subjects', name);
    }
    await log(txn, 'seed_subjects', '${defaultSubjects.length} درس پیش‌فرض');
  });
}

/// Append one row to the user-activity log.
Future<void> log(
  DatabaseExecutor db,
  String action, [
  String detail = '',
]) async {
  final now = DateTime.now().toIso8601String().substring(0, 19);
  await db.rawInsert(
    'INSERT INTO activity_log(ts, action, detail) VALUES (?,?,?)',
    [now, action, detail],
  );
}

/// Return the id of a subjects/teachers/tags row [name], creating it if new.
///
/// Matching uses the normalized key, so «رياضي» (Arabic ي) finds «ریاضی».
Future<int?> getOrCreate(DatabaseExecutor db, String table, String name) async {
  assert(
    table == 'subjects' || table == 'teachers' || table == 'tags',
    'unknown table $table',
  );
  final key = matchKey(name);
  if (key.isEmpty) return null;
  final rows = await db.query(
    table,
    columns: ['id'],
    where: 'normalized = ?',
    whereArgs: [key],
    limit: 1,
  );
  if (rows.isNotEmpty) return rows.first['id'] as int;
  return db.rawInsert('INSERT INTO $table(name, normalized) VALUES (?,?)', [
    name.trim(),
    key,
  ]);
}

/// Convenience: open the catalog at [root]/catalog.db and seed subjects.
Future<Database> openCatalog(String rootPath) async {
  final db = await openDatabaseAt(p.join(rootPath, 'catalog.db'));
  await seedSubjects(db);
  return db;
}
