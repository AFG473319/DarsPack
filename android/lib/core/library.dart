// The DarsPack library: one folder holding catalog.db + files/ (کتابخانه).
//
// Port of Windows `core/library.py`. Files are *copied* in at import
// time; originals are never touched. The files/ folder is deliberately
// flat (files/000123.pdf): the database is the organizer, so no folder
// tree can drift out of sync with the metadata, and renaming a subject
// never moves a byte on disk.
//
// Layout:
//
//     <app documents>/DarsPackLibrary/
//     ├── catalog.db
//     ├── files/000001.pdf …
//     └── files/.trash/ (+ files/.trash_meta/ sidecars)
//
// Use [Library.open] to get a usable instance. The default constructor
// exists so test fakes can subclass Library (an unopened instance throws
// on use — it has no catalog).

import 'dart:convert';
import 'dart:io';

import 'package:archive/archive.dart';
import 'package:path/path.dart' as p;
import 'package:path_provider/path_provider.dart';
import 'package:sqflite/sqflite.dart';

import 'backup.dart' as backup;
import 'database.dart';
import 'dedup.dart' as dedup;
import 'hashing.dart';
import 'importer.dart' as importer;
import 'manifest.dart' as manifest;
import 'models.dart';
import 'normalize.dart';
import 'search.dart' as search;
import 'suggest.dart' as suggest;

String _now() => DateTime.now().toIso8601String().substring(0, 19);

class Library {
  /// Unopened instance (for subclasses/fakes). Use [Library.open].
  Library();

  late final Directory _root;
  late final Database _db;

  /// Open the library at `<app documents>/DarsPackLibrary`.
  ///
  /// Pass [root] to open a library elsewhere (tests, the screenshot
  /// harness, a restored backup) instead of the app documents folder.
  static Future<Library> open({Directory? root}) async {
    final dir =
        root ??
        Directory(
          p.join(
            (await getApplicationDocumentsDirectory()).path,
            'DarsPackLibrary',
          ),
        );
    await dir.create(recursive: true);
    final filesDir = Directory(p.join(dir.path, 'files'));
    await filesDir.create(recursive: true);
    final lib = Library();
    lib._root = dir;
    lib._db = await openCatalog(dir.path);
    await lib._sweepOrphans();
    await lib._healthCheck();
    return lib;
  }

  Future<void> close() async => _db.close();

  Directory get filesDir => Directory(p.join(_root.path, 'files'));
  String get rootPath => _root.path;

  Directory get _trashDir => Directory(p.join(filesDir.path, '.trash'));
  Directory get _trashMetaDir =>
      Directory(p.join(filesDir.path, '.trash_meta'));

  // --- maintenance (run on open, as in Windows) ---------------------------

  /// Verify every stored file is still on disk — return how many are not.
  /// A row whose file is missing or whose size no longer matches gets
  /// available=0; a row whose file is fine gets reset to 1.
  Future<int> _healthCheck() async {
    final rows = await _db.query(
      'files',
      columns: ['id', 'stored_name', 'size_bytes', 'available'],
    );
    final missing = <int>[];
    for (final row in rows) {
      final path = File(p.join(filesDir.path, row['stored_name'] as String));
      var ok = false;
      try {
        ok =
            await path.exists() &&
            await path.length() == (row['size_bytes'] as int);
      } catch (_) {
        ok = false;
      }
      if (!ok) {
        missing.add(row['id'] as int);
      } else if (row['available'] != 1) {
        missing.add(-(row['id'] as int)); // negative id = "flag to clear"
      }
    }
    if (missing.isEmpty) return 0;
    await _db.transaction((txn) async {
      for (final value in missing) {
        if (value > 0) {
          await txn.rawUpdate('UPDATE files SET available=0 WHERE id=?', [
            value,
          ]);
        } else {
          await txn.rawUpdate('UPDATE files SET available=1 WHERE id=?', [
            -value,
          ]);
        }
      }
      await log(txn, 'healthcheck', 'missing=${missing.length}');
    });
    return missing.length;
  }

  /// Reconcile files/ with the catalog after an interrupted import.
  /// Unknown files are first offered a rescue by SHA-256 (see
  /// [_rescueUnknowns]); anything with no catalog row waiting for its
  /// content is deleted — the catalog is the source of truth.
  Future<void> _sweepOrphans() async {
    final known = {
      for (final r in await _db.query('files', columns: ['stored_name']))
        r['stored_name'] as String,
    };
    final unknown = <File>[];
    await for (final entity in filesDir.list()) {
      if (entity is File) {
        final name = p.basename(entity.path);
        if (!known.contains(name)) unknown.add(entity);
      }
    }
    if (unknown.isNotEmpty) {
      await _rescueUnknowns(unknown);
      for (final f in unknown) {
        try {
          if (await f.exists()) await f.delete();
        } catch (_) {}
      }
    }
  }

  /// Rename files the catalog doesn't know into rows that lost their file.
  /// Matches by SHA-256: an unknown file whose hash equals a catalog row
  /// whose own file is missing is renamed to that row's stored name.
  /// This is what makes a backup made before 2026-11-17 (members filed
  /// under friendly «NNN - name» labels) safe to restore.
  Future<int> _rescueUnknowns(List<File> paths) async {
    final missing = <String, List<String>>{};
    for (final row in await _db.query(
      'files',
      columns: ['stored_name', 'sha256'],
    )) {
      final stored = row['stored_name'] as String;
      if (await File(p.join(filesDir.path, stored)).exists()) continue;
      missing.putIfAbsent(row['sha256'] as String, () => []).add(stored);
    }
    if (missing.isEmpty) return 0;
    var rescued = 0;
    for (final file in paths) {
      String digest;
      try {
        digest = await sha256File(file);
      } catch (_) {
        continue; // unreadable: not rescuable today
      }
      final storedNames = missing[digest];
      if (storedNames == null || storedNames.isEmpty) continue;
      final storedName = storedNames.removeAt(0);
      if (storedNames.isEmpty) missing.remove(digest);
      await file.rename(p.join(filesDir.path, storedName));
      rescued++;
      await log(_db, 'rescue', '${p.basename(file.path)} → $storedName');
    }
    return rescued;
  }

  // --- search / lists ------------------------------------------------------

  Future<Map<int, List<String>>> _tagsForIds(List<int> ids) async {
    final out = <int, List<String>>{};
    if (ids.isEmpty) return out;
    final placeholders = List.filled(ids.length, '?').join(',');
    final rows = await _db.rawQuery(
      'SELECT ft.file_id AS file_id, t.name AS name FROM file_tags ft '
      'JOIN tags t ON t.id = ft.tag_id '
      'WHERE ft.file_id IN ($placeholders) ORDER BY t.name',
      ids,
    );
    for (final row in rows) {
      out
          .putIfAbsent(row['file_id'] as int, () => [])
          .add(row['name'] as String);
    }
    return out;
  }

  Future<List<LibraryFile>> searchFiles({
    String query = '',
    int? subjectId,
    String? kind,
    String? schoolYear,
    int limit = 200,
    bool unclassifiedOnly = false,
  }) async {
    final rows = await search.searchDb(
      _db,
      query: query,
      subjectId: subjectId,
      kind: kind,
      schoolYear: schoolYear,
      limit: limit,
      unclassifiedOnly: unclassifiedOnly,
    );
    final ids = [for (final r in rows) r['id'] as int];
    final tags = await _tagsForIds(ids);
    return [
      for (final row in rows)
        LibraryFile.fromRow(row, tags: tags[row['id'] as int] ?? const []),
    ];
  }

  Future<List<Subject>> subjectsWithCounts() async {
    final rows = await _db.rawQuery(
      'SELECT s.id, s.name, s.normalized, COUNT(f.id) AS file_count '
      'FROM subjects s LEFT JOIN files f ON f.subject_id = s.id '
      'GROUP BY s.id ORDER BY s.id',
    );
    return [for (final row in rows) Subject.fromRow(row)];
  }

  Future<int> unclassifiedCount() => search.unclassifiedCountDb(_db);

  // --- import --------------------------------------------------------------

  Future<ImportResult> importFile(
    File src, {
    String? displayName,
    Map<String, dynamic>? meta,
    bool keepDuplicate = false,
  }) => importer.importFile(
    _db,
    filesDir,
    src,
    displayName: displayName,
    meta: meta,
    keepDuplicate: keepDuplicate,
  );

  Future<List<ImportResult>> importFiles(List<File> srcs) =>
      importer.importFiles(_db, filesDir, srcs);

  // --- single file -----------------------------------------------------------

  Future<LibraryFile?> getFile(int id) async {
    final rows = await _db.rawQuery(
      'SELECT f.*, s.name AS subject_name '
      'FROM files f LEFT JOIN subjects s ON s.id = f.subject_id '
      'WHERE f.id = ?',
      [id],
    );
    if (rows.isEmpty) return null;
    final tags = await _tagsForIds([id]);
    return LibraryFile.fromRow(rows.first, tags: tags[id] ?? const []);
  }

  /// Update a file's metadata. Null means "no change" for every field
  /// except [clearSubject], which clears the subject. [tags], when given,
  /// replaces the file's tag set entirely.
  Future<void> updateFileMeta(
    int id, {
    int? subjectId,
    int? chapter,
    int? lesson,
    String? kind,
    String? note,
    List<String>? tags,
    bool clearSubject = false,
  }) async {
    await _db.transaction((txn) async {
      final sets = <String>[];
      final args = <Object?>[];
      if (clearSubject) {
        sets.add('subject_id = NULL');
      } else if (subjectId != null) {
        sets.add('subject_id = ?');
        args.add(subjectId);
      }
      if (chapter != null) {
        sets.add('chapter = ?');
        args.add(chapter);
      }
      if (lesson != null) {
        sets.add('lesson = ?');
        args.add(lesson);
      }
      if (kind != null) {
        sets.add('kind = ?');
        args.add(kind);
      }
      if (note != null) {
        sets.add('note = ?');
        args.add(note);
      }
      if (sets.isNotEmpty) {
        args.add(id);
        await txn.rawUpdate(
          'UPDATE files SET ${sets.join(', ')} WHERE id = ?',
          args,
        );
      }
      if (tags != null) {
        await txn.delete('file_tags', where: 'file_id = ?', whereArgs: [id]);
        for (final tag in tags) {
          if (tag.trim().isEmpty) continue;
          final tagId = await getOrCreate(txn, 'tags', tag.trim());
          if (tagId != null) {
            await txn.rawInsert(
              'INSERT OR IGNORE INTO file_tags (file_id, tag_id) VALUES (?, ?)',
              [id, tagId],
            );
          }
        }
      }
      await log(txn, 'update', 'file id=$id');
    });
  }

  /// Move a file to .trash (with a JSON sidecar in .trash_meta) and
  /// remove its catalog row. Throws [StateError] if the id is unknown.
  Future<void> deleteFile(int id) async {
    final rows = await _db.rawQuery(
      'SELECT f.*, s.name AS subject_name FROM files f '
      'LEFT JOIN subjects s ON s.id = f.subject_id WHERE f.id = ?',
      [id],
    );
    if (rows.isEmpty) throw StateError('File id $id not found in catalog');
    final row = rows.first;

    await _trashDir.create(recursive: true);
    await _trashMetaDir.create(recursive: true);

    final storedName = row['stored_name'] as String;
    final stem = p.basenameWithoutExtension(storedName);
    final ext = p.extension(storedName);
    var dest = File(p.join(_trashDir.path, storedName));
    var n = 0;
    while (await dest.exists()) {
      n++;
      dest = File(p.join(_trashDir.path, '$stem~$n$ext'));
    }

    final srcFile = File(p.join(filesDir.path, storedName));
    try {
      await srcFile.rename(dest.path);
      final tagRows = await _db.rawQuery(
        'SELECT t.name FROM tags t JOIN file_tags ft ON ft.tag_id = t.id '
        'WHERE ft.file_id = ?',
        [id],
      );
      final meta = {
        'original_name': row['original_name'],
        'stored_name': storedName,
        'subject_id': row['subject_id'],
        'subject_name': row['subject_name'],
        'chapter': row['chapter'],
        'lesson': row['lesson'],
        'kind': row['kind'],
        'school_year': row['school_year'],
        'sha256': row['sha256'],
        'size': row['size_bytes'],
        'imported_at': row['imported_at'],
        'deleted_at': _now(),
        'note': row['note'],
        'tags': [for (final t in tagRows) t['name']],
      };
      await File(
        p.join(_trashMetaDir.path, '${p.basename(dest.path)}.json'),
      ).writeAsString(jsonEncode(meta), encoding: utf8);
    } catch (_) {
      // File already gone from disk: the row still goes, as in Windows
      // (FileNotFoundError is swallowed there too).
    }

    await _db.transaction((txn) async {
      await txn.delete('files', where: 'id = ?', whereArgs: [id]);
      await log(txn, 'delete', row['original_name'] as String);
    });
  }

  // --- trash ---------------------------------------------------------------

  Future<List<TrashEntry>> listTrash() async {
    if (!await _trashDir.exists()) return [];
    final items = <TrashEntry>[];
    await for (final entity in _trashDir.list()) {
      if (entity is! File) continue;
      final trashName = p.basename(entity.path);
      Map<String, dynamic> meta = {};
      final metaFile = File(p.join(_trashMetaDir.path, '$trashName.json'));
      if (await metaFile.exists()) {
        try {
          meta =
              jsonDecode(await metaFile.readAsString()) as Map<String, dynamic>;
        } catch (_) {}
      }
      final size = await entity.length();
      items.add(
        TrashEntry(
          trashName: trashName,
          originalName: (meta['original_name'] as String?) ?? trashName,
          storedName: (meta['stored_name'] as String?) ?? trashName,
          subjectName: (meta['subject_name'] as String?) ?? '?',
          size: size,
          deletedAt:
              (meta['deleted_at'] as String?) ??
              (await entity.stat()).modified.toIso8601String(),
          kind: (meta['kind'] as String?) ?? '',
          tags: [for (final t in (meta['tags'] as List? ?? [])) t.toString()],
        ),
      );
    }
    items.sort((a, b) => b.deletedAt.compareTo(a.deletedAt));
    return items;
  }

  /// Restore one file from .trash back into files/ and the catalog.
  /// The restored row gets a new id; the stored name is kept when free.
  Future<void> restoreTrash(String trashName) async {
    final cleanName = p.basename(trashName);
    final src = File(p.join(_trashDir.path, cleanName));
    if (!await src.exists()) {
      throw StateError('Trash file not found: $trashName');
    }
    Map<String, dynamic> meta = {};
    final metaFile = File(p.join(_trashMetaDir.path, '$cleanName.json'));
    if (await metaFile.exists()) {
      try {
        meta =
            jsonDecode(await metaFile.readAsString()) as Map<String, dynamic>;
      } catch (_) {}
    }

    final originalName = (meta['original_name'] as String?) ?? cleanName;
    final baseStored = (meta['stored_name'] as String?) ?? cleanName;
    final stem = p.basenameWithoutExtension(baseStored);
    final ext = p.extension(baseStored);
    var dest = File(p.join(filesDir.path, baseStored));
    var n = 0;
    while (await dest.exists()) {
      n++;
      dest = File(p.join(filesDir.path, '$stem~$n$ext'));
    }

    var sha = meta['sha256'] as String?;
    final size = await src.length();
    sha ??= await sha256File(src);

    var subjectId = meta['subject_id'] as int?;
    final subjectName = meta['subject_name'] as String?;
    if (subjectId == null && subjectName != null) {
      final subRows = await _db.query(
        'subjects',
        columns: ['id'],
        where: 'name = ?',
        whereArgs: [subjectName],
        limit: 1,
      );
      if (subRows.isNotEmpty) subjectId = subRows.first['id'] as int;
    }

    final importedAt =
        (meta['imported_at'] as String?) ?? DateTime.now().toIso8601String();
    final tags = [for (final t in (meta['tags'] as List? ?? [])) t.toString()];

    await _db.transaction((txn) async {
      final newId = await txn.rawInsert(
        'INSERT INTO files'
        '(stored_name, original_name, name_norm, sha256, size_bytes, '
        'imported_at, subject_id, chapter, lesson, kind, '
        'school_year, available, note) '
        'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)',
        [
          p.basename(dest.path),
          originalName,
          normalize(originalName),
          sha,
          size,
          importedAt,
          subjectId,
          meta['chapter'],
          meta['lesson'],
          meta['kind'],
          meta['school_year'],
          meta['note'] ?? '',
        ],
      );
      for (final tag in tags) {
        if (tag.trim().isEmpty) continue;
        final tagId = await getOrCreate(txn, 'tags', tag.trim());
        if (tagId != null) {
          await txn.rawInsert(
            'INSERT OR IGNORE INTO file_tags (file_id, tag_id) VALUES (?, ?)',
            [newId, tagId],
          );
        }
      }
      await log(txn, 'restore', '$originalName (id=$newId)');
      await src.rename(dest.path);
      try {
        await metaFile.delete();
      } catch (_) {}
    });
  }

  /// Permanently delete everything in .trash/. Returns the file count.
  Future<void> emptyTrash() async {
    var count = 0;
    if (await _trashDir.exists()) {
      await for (final entity in _trashDir.list()) {
        if (entity is File) {
          await entity.delete();
          count++;
        }
      }
    }
    if (await _trashMetaDir.exists()) {
      await for (final entity in _trashMetaDir.list()) {
        if (entity is File) await entity.delete();
      }
    }
    await log(_db, 'empty_trash', '$count files permanently deleted');
  }

  // --- backup / packages ---------------------------------------------------

  /// One-click full-library backup ZIP, written next to the library
  /// folder (`<docs>/darspack-backup-<Jalali YYYY-MM-DD>.zip`).
  Future<File> exportBackup() async {
    final out = File(p.join(p.dirname(_root.path), backup.backupFilename()));
    await backup.backupLibrary(_db, filesDir, out);
    await log(_db, 'export', 'backup ${p.basename(out.path)}');
    return out;
  }

  /// Export a plain درس‌پک package (same ZIP as a backup, without
  /// catalog.db) for the given file ids.
  Future<File> exportPackage(List<int> ids) async {
    final now = DateTime.now();
    final jalaliDate = backup
        .backupFilename(now)
        .replaceFirst('darspack-backup-', '')
        .replaceFirst('.zip', '');
    final stamp =
        '${now.hour.toString().padLeft(2, '0')}'
        '${now.minute.toString().padLeft(2, '0')}'
        '${now.second.toString().padLeft(2, '0')}';
    final out = File(
      p.join(p.dirname(_root.path), 'darspack-package-$jalaliDate-$stamp.zip'),
    );
    await manifest.exportPackage(_db, filesDir, ids, out);
    await log(
      _db,
      'export',
      'package ${p.basename(out.path)} (${ids.length} files)',
    );
    return out;
  }

  Future<VerifyReport> verifyPackage(File zip) => manifest.verifyPackage(zip);

  /// Import a درس‌پک package (or a full backup — its catalog.db member
  /// is ignored here). Metadata from the manifest round-trips: subject
  /// and tags arrive as pre-fill only, chapter/lesson/kind/school_year
  /// are stored. A package that fails verification imports nothing and
  /// yields a single error result listing the problems.
  Future<List<ImportResult>> importPackage(File zip) async {
    final report = await manifest.verifyPackage(zip);
    if (!report.ok) {
      return [
        ImportResult(
          status: 'error',
          messageFa: 'بسته معتبر نیست: ${report.problems.join('؛ ')}',
        ),
      ];
    }
    final entries = await manifest.readManifest(zip);
    final tmpDir = await Directory.systemTemp.createTemp('darspack-import-');
    try {
      final archive = ZipDecoder().decodeBytes(await zip.readAsBytes());
      final results = <ImportResult>[];
      for (final entry in entries) {
        final arc = entry['path'] as String?;
        final member = arc == null ? null : archive.findFile(arc);
        if (member == null) {
          results.add(
            ImportResult(
              status: 'error',
              messageFa: 'گم‌شده: ${entry['name']} ($arc)',
            ),
          );
          continue;
        }
        final staged = File(p.join(tmpDir.path, p.basename(arc!)));
        await staged.writeAsBytes(member.content as List<int>);
        final meta = <String, dynamic>{
          'chapter': entry['chapter'],
          'lesson': entry['lesson'],
          'kind': entry['kind'],
          'school_year': entry['school_year'],
          'subject': entry['subject'],
          'tags': entry['tags'],
        };
        try {
          results.add(
            await importer.importFile(
              _db,
              filesDir,
              staged,
              displayName: entry['name'] as String?,
              meta: meta,
            ),
          );
        } catch (e) {
          results.add(
            ImportResult(
              status: 'error',
              messageFa: '${entry['name']}: ${e.runtimeType}',
            ),
          );
        }
      }
      return results;
    } finally {
      try {
        await tmpDir.delete(recursive: true);
      } catch (_) {}
    }
  }

  // --- duplicates ------------------------------------------------------------

  Future<List<DuplicateGroup>> duplicateGroups() => dedup.duplicateGroups(_db);
  Future<List<VersionConflict>> versionConflicts() =>
      dedup.versionConflicts(_db);
  Future<List<RenameHint>> renameHints() => dedup.renameHints(_db);

  // --- stats / activity --------------------------------------------------------

  /// Library statistics. Keys: totalFiles, totalSizeBytes, unclassified,
  /// subjects, duplicates, wastedBytes, trashCount, skippedBytes
  /// (bytes import-time dedup saved, from import_skips).
  Future<Map<String, dynamic>> stats() async {
    final total = await _db.rawQuery(
      'SELECT COUNT(*) AS n, COALESCE(SUM(size_bytes), 0) AS bytes '
      'FROM files',
    );
    final unclassified = await unclassifiedCount();
    final subjects =
        Sqflite.firstIntValue(
          await _db.rawQuery('SELECT COUNT(*) FROM subjects'),
        ) ??
        0;
    final groups = await dedup.duplicateGroups(_db);
    var wasted = 0;
    for (final g in groups) {
      wasted += (g.files.length - 1) * g.files.first.sizeBytes;
    }
    final skipped =
        Sqflite.firstIntValue(
          await _db.rawQuery(
            'SELECT COALESCE(SUM(size_bytes), 0) FROM import_skips',
          ),
        ) ??
        0;
    var trashCount = 0;
    if (await _trashDir.exists()) {
      await for (final e in _trashDir.list()) {
        if (e is File) trashCount++;
      }
    }
    return {
      'totalFiles': total.first['n'],
      'totalSizeBytes': total.first['bytes'],
      'unclassified': unclassified,
      'subjects': subjects,
      'duplicates': groups.length,
      'wastedBytes': wasted,
      'trashCount': trashCount,
      'skippedBytes': skipped,
    };
  }

  Future<List<ActivityEntry>> activityLog({int limit = 100}) async {
    final rows = await _db.query(
      'activity_log',
      orderBy: 'id DESC',
      limit: limit,
    );
    return [for (final row in rows) ActivityEntry.fromRow(row)];
  }

  Future<void> logActivity(String action, String detail) =>
      log(_db, action, detail);

  // --- misc ------------------------------------------------------------------

  File storedFileFor(LibraryFile f) =>
      File(p.join(filesDir.path, f.storedName));

  Future<Map<String, suggest.LearnedHint>> loadHints() =>
      suggest.loadHints(_db);

  Future<void> learnHint(String token, String subjectName) =>
      suggest.learnHint(_db, token, subjectName);
}
