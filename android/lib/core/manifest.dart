// Portable learning packages (بسته‌ی درس‌پک).
//
// Port of Windows `core/manifest.py`. A package is a plain ZIP with
// three parts:
//
//     manifest.json   machine-readable list: every file's original name,
//                     subject/chapter/kind, size and SHA-256
//     files/…         the files themselves
//     index.html      a Persian RTL list that opens in any browser —
//                     the package explains itself without DarsPack
//
// verifyPackage() re-hashes every member and reports exactly what is
// missing or changed. It never repairs anything — the recipient decides
// what to do.
//
// The manifest format is shared with the Windows app: a package written
// by either app verifies and imports in the other.

import 'dart:convert';
import 'dart:io';

import 'package:archive/archive.dart';
import 'package:path/path.dart' as p;
import 'package:sqflite/sqflite.dart';

import 'hashing.dart';
import 'models.dart';

const String packageFormat = 'darspack-package';
const int packageVersion = 1;

/// Members that belong to a full-library backup, not to a plain درس‌پک —
/// verify ignores them instead of reporting them as extras (additive: a
/// backup therefore verifies as a package too).
const Set<String> knownExtraMembers = {'catalog.db', 'RESTORE-راهنما.txt'};

final RegExp _unsafeChars = RegExp(r'[\\/:*?"<>|\r\n]+');

/// Turn a filename into a safe ZIP member name (Persian kept).
String safeName(String name) {
  final cleaned = name.replaceAll(_unsafeChars, '_').trim();
  return cleaned.isEmpty ? 'file' : cleaned;
}

String _now() => DateTime.now().toIso8601String().substring(0, 19);

Future<Map<String, dynamic>> _fetchEntry(Database db, int fileId) async {
  final rows = await db.rawQuery(
    'SELECT f.*, s.name AS subject_name '
    'FROM files f LEFT JOIN subjects s ON s.id = f.subject_id '
    'WHERE f.id = ?',
    [fileId],
  );
  if (rows.isEmpty) throw ArgumentError('file id $fileId not found in catalog');
  final row = rows.first;
  final tagRows = await db.rawQuery(
    'SELECT t.name FROM tags t '
    'JOIN file_tags ft ON ft.tag_id = t.id '
    'WHERE ft.file_id = ?',
    [fileId],
  );
  return {
    'name': row['original_name'],
    'sha256': row['sha256'],
    'size': row['size_bytes'],
    'subject': row['subject_name'],
    'chapter': row['chapter'],
    'lesson': row['lesson'],
    'school_year': row['school_year'],
    'kind': row['kind'],
    'tags': [for (final t in tagRows) t['name']],
    'stored_name': row['stored_name'], // internal; removed from manifest
  };
}

/// Write a درس‌پک ZIP for the given catalog ids.
/// Returns {'path', 'count', 'manifestSha256'}.
///
/// By default each member is filed under a friendly «NNN - name» label,
/// which keeps a shipped package browsable. A full-library backup passes
/// [storedNames] true: it keeps the catalog's own internal names
/// (files/000001.pdf) instead — that matters because the backup ALSO
/// carries a catalog.db snapshot whose rows point at those stored names.
Future<Map<String, dynamic>> exportPackage(
  Database db,
  Directory filesDir,
  List<int> fileIds,
  File outFile, {
  bool storedNames = false,
}) async {
  final entries = <Map<String, dynamic>>[];
  for (final id in fileIds) {
    entries.add(await _fetchEntry(db, id));
  }
  final manifest = {
    'format': packageFormat,
    'version': packageVersion,
    'created': _now(),
    'files': entries,
  };

  final archive = Archive();
  for (var i = 0; i < entries.length; i++) {
    final entry = entries[i];
    final stored = entry.remove('stored_name') as String;
    final arc = storedNames
        ? 'files/$stored'
        : 'files/${(i + 1).toString().padLeft(3, '0')} - ${safeName(entry['name'] as String)}';
    final data = await File(p.join(filesDir.path, stored)).readAsBytes();
    archive.addFile(ArchiveFile(arc, data.length, data));
    entry['path'] = arc;
  }
  final manifestBytes = utf8.encode(jsonEncode(manifest));
  archive.addFile(
    ArchiveFile('manifest.json', manifestBytes.length, manifestBytes),
  );
  final indexBytes = utf8.encode(makeIndexHtml(manifest));
  archive.addFile(ArchiveFile('index.html', indexBytes.length, indexBytes));

  await outFile.writeAsBytes(ZipEncoder().encode(archive));
  return {
    'path': outFile.path,
    'count': entries.length,
    'manifestSha256': sha256Bytes(manifestBytes),
  };
}

/// Small RTL HTML table so any browser can list the package contents.
String makeIndexHtml(Map<String, dynamic> manifest) {
  final rows = <String>[];
  for (final e in (manifest['files'] as List)) {
    final entry = e as Map<String, dynamic>;
    final chapter = entry['chapter'] != null ? 'فصل ${entry['chapter']}' : '—';
    rows.add(
      '<tr><td>${_escape(entry['name'])}</td>'
      '<td>${_escape(entry['subject'] ?? '—')}</td>'
      '<td>${_escape(chapter)}</td>'
      '<td>${_escape(entry['kind'] ?? '—')}</td></tr>',
    );
  }
  final created = _escape(manifest['created'] as String? ?? '');
  return '''<!doctype html>
<html lang="fa" dir="rtl"><head><meta charset="utf-8">
<title>درس‌پک — فهرست بسته</title>
<style>
 body { font-family: Tahoma, sans-serif; direction: rtl; margin: 2rem; }
 table { border-collapse: collapse; width: 100%; }
 td, th { border: 1px solid #ccc; padding: 0.4rem 0.6rem; text-align: right; }
</style></head><body>
<h1>درس‌پک</h1>
<p>${rows.length} فایل — ساخته‌شده در $created</p>
<table><tr><th>نام فایل</th><th>درس</th><th>فصل</th><th>نوع</th></tr>
${rows.join()}
</table></body></html>''';
}

String _escape(Object? value) {
  final text = value?.toString() ?? '';
  return const HtmlEscape().convert(text);
}

/// Parse a package's manifest.json back into its entry list.
///
/// Pure function: it touches nothing outside the ZIP. The caller matches
/// entries to extracted files by the arc `path` — unique even when two
/// files share a display name — and feeds each entry to the importer as
/// `meta`, with subject/tags kept as pre-fill only.
/// Throws [ArgumentError] on a ZIP without a darspack manifest.
Future<List<Map<String, dynamic>>> readManifest(File zipFile) async {
  final archive = ZipDecoder().decodeBytes(await zipFile.readAsBytes());
  final manifestFile = archive.findFile('manifest.json');
  if (manifestFile == null) {
    throw ArgumentError('not a darspack package manifest');
  }
  final manifest =
      jsonDecode(utf8.decode(manifestFile.content as List<int>))
          as Map<String, dynamic>;
  if (manifest['format'] != packageFormat) {
    throw ArgumentError('not a darspack package manifest');
  }
  return [
    for (final e in (manifest['files'] as List? ?? []))
      Map<String, dynamic>.from(e as Map),
  ];
}

/// Check a package against its manifest: missing / size / SHA-256.
///
/// Returns a [VerifyReport]; never throws for a readable ZIP whose
/// manifest is present but bad. A non-ZIP file throws [FormatException]
/// (from the ZIP decoder) — callers should catch it around the picker.
Future<VerifyReport> verifyPackage(File zipFile) async {
  final problems = <String>[];
  final archive = ZipDecoder().decodeBytes(await zipFile.readAsBytes());
  final names = {for (final f in archive.files) f.name};
  final manifestFile = archive.findFile('manifest.json');
  if (manifestFile == null) {
    return const VerifyReport(
      ok: false,
      problems: ['manifest.json در بسته نیست — بسته معتبر نیست'],
    );
  }
  Map<String, dynamic> manifest;
  try {
    manifest =
        jsonDecode(utf8.decode(manifestFile.content as List<int>))
            as Map<String, dynamic>;
  } catch (_) {
    return const VerifyReport(
      ok: false,
      problems: ['manifest.json مخدوش است — بسته معتبر نیست'],
    );
  }

  final listed = <String>{};
  for (final entry in (manifest['files'] as List? ?? [])) {
    final e = entry as Map<String, dynamic>;
    final arc = e['path'] as String?;
    if (arc == null || !names.contains(arc)) {
      problems.add('گم‌شده: ${e['name']} ($arc)');
      continue;
    }
    listed.add(arc);
    final member = archive.findFile(arc)!;
    final data = member.content as List<int>;
    if (data.length != e['size']) {
      problems.add('اندازه‌ی فایل متفاوت است: ${e['name']}');
      continue;
    }
    if (sha256Bytes(data) != e['sha256']) {
      problems.add('خراب یا تغییرکرده: ${e['name']}');
    }
  }

  final extras =
      names
          .difference(listed)
          .difference({'manifest.json', 'index.html'})
          .difference(knownExtraMembers)
          .toList()
        ..sort();
  for (final extra in extras) {
    problems.add('فایل اضافه در بسته: $extra');
  }
  return VerifyReport(ok: problems.isEmpty, problems: problems);
}
