// Import pipeline (وارد کردن فایل): copy into the library and catalog it.
//
// Port of Windows `core/importer.py`. Per file: hash the source →
// duplicate check → copy to a tmp name → atomic rename → single DB
// transaction. If anything fails before the commit, the row rolls back
// and the leftover tmp file is swept the next time the library opens.
// An identical hash already in the library is *reported and skipped* —
// the user can override with keepDuplicate («با وجود این نگه دار»);
// nothing is ever overwritten.

import 'dart:io';

import 'package:path/path.dart' as p;
import 'package:sqflite/sqflite.dart';

import 'database.dart';
import 'hashing.dart';
import 'models.dart';
import 'normalize.dart';
import 'schoolyear.dart';
import 'suggest.dart';

String _now() => DateTime.now().toIso8601String().substring(0, 19);

/// Import one file into the library.
///
/// [db] is the open catalog, [filesDir] the library's files/ folder.
///
/// [displayName]: what the file should be called in the catalog. It
/// differs from [src] for web uploads, which arrive as temporary files
/// with a random name.
///
/// [meta] may carry "kind", "chapter", "lesson", "school_year" — applied
/// like the filename suggestions — plus "subject" and "tags" from a
/// درس‌پک manifest. Those two are NEVER stored (the subject is never
/// auto-applied); they travel back on the result as `prefill` so the
/// classify dialog can offer them for review.
Future<ImportResult> importFile(
  Database db,
  Directory filesDir,
  File src, {
  String? displayName,
  Map<String, dynamic>? meta,
  bool keepDuplicate = false,
  void Function(int done, int total)? onProgress,
}) async {
  if (!await src.exists()) {
    return ImportResult(
      status: 'error',
      messageFa: 'فایل پیدا نشد: ${src.path}',
    );
  }
  final size = await src.length();
  final sha = await sha256File(src, onProgress: onProgress, size: size);

  final shownName = displayName ?? p.basename(src.path);
  final suggestion = suggest(_stem(shownName));
  meta ??= {};
  final kind = meta['kind'] as String? ?? suggestion.kind;
  // The SUBJECT is deliberately NOT auto-applied: categorizing is the
  // app's main job and belongs to the user. Suggestions only pre-fill
  // the classification dialog; until then the file counts as
  // unclassified («بدون درس») so the app keeps asking.
  Map<String, dynamic>? prefill;
  if (meta['subject'] != null || meta['tags'] != null) {
    prefill = {
      'subject': meta['subject'],
      'tags': List<String>.from((meta['tags'] as List?) ?? const []),
    };
  }

  final ext = p.extension(src.path);
  return db.transaction<ImportResult>((txn) async {
    final dup = await txn.query(
      'files',
      columns: ['id', 'original_name'],
      where: 'sha256 = ?',
      whereArgs: [sha],
      limit: 1,
    );
    if (dup.isNotEmpty && !keepDuplicate) {
      // Remember what the skip saved: bytes that never entered the
      // library. History, not a running counter.
      await txn.rawInsert(
        'INSERT INTO import_skips(ts, sha256, size_bytes, original_name) '
        'VALUES (?,?,?,?)',
        [_now(), sha, size, shownName],
      );
      // Name the twin: «از قبل در کتابخانه هست» without the name is a
      // dead end; naming it answers «این همانی که...؟».
      return ImportResult(
        status: 'duplicate',
        messageFa: '«$shownName» تکرارِ «${dup.first['original_name']}» است',
        existingId: dup.first['id'] as int,
        prefill: prefill,
      );
    }

    final fileId = await txn.rawInsert(
      'INSERT INTO files(stored_name, original_name, name_norm, '
      'size_bytes, sha256, imported_at, subject_id, chapter, '
      'lesson, school_year, kind) '
      'VALUES (\'\', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
      [
        shownName,
        matchKey(shownName),
        size,
        sha,
        _now(),
        null,
        meta?['chapter'] as int? ?? suggestion.chapter,
        meta?['lesson'] as int? ?? suggestion.lesson,
        meta?['school_year'] as String? ?? currentSchoolYear(),
        kind,
      ],
    );

    final tmp = File(p.join(filesDir.path, 'tmp_$fileId$ext'));
    final finalFile = File(
      p.join(filesDir.path, '${fileId.toString().padLeft(6, '0')}$ext'),
    );
    try {
      await src.copy(tmp.path);
      await tmp.rename(finalFile.path); // atomic rename on the same volume
    } catch (_) {
      // The row rolls back with the transaction; drop the tmp leftover
      // now so the next open's orphan sweep has less to do.
      try {
        if (await tmp.exists()) await tmp.delete();
      } catch (_) {}
      rethrow;
    }
    await txn.rawUpdate('UPDATE files SET stored_name = ? WHERE id = ?', [
      p.basename(finalFile.path),
      fileId,
    ]);
    await log(txn, 'import', '$shownName → ${p.basename(finalFile.path)}');
    return ImportResult(
      status: 'imported',
      messageFa: '«$shownName» وارد شد',
      fileId: fileId,
      prefill: prefill,
    );
  });
}

/// Import many files; one [ImportResult] per file.
///
/// A file that raises (locked by another program, unreadable) becomes
/// an 'error' result — one bad file must not abort the whole batch.
Future<List<ImportResult>> importFiles(
  Database db,
  Directory filesDir,
  List<File> srcs, {
  bool keepDuplicates = false,
}) async {
  final results = <ImportResult>[];
  for (final src in srcs) {
    try {
      results.add(
        await importFile(db, filesDir, src, keepDuplicate: keepDuplicates),
      );
    } catch (e) {
      results.add(
        ImportResult(
          status: 'error',
          messageFa: '${p.basename(src.path)}: ${e.runtimeType}',
        ),
      );
    }
  }
  return results;
}

String _stem(String filename) {
  final base = p.basename(filename);
  final ext = p.extension(base);
  return ext.isEmpty ? base : base.substring(0, base.length - ext.length);
}
