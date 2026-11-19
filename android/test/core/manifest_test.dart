// Tests for درس‌پک packages — port of Windows tests/test_manifest.py
// (verify half) and tests/test_backup.py (filename half). The export
// half needs a database, so it lives in the skipped database_test.dart;
// here packages are built by hand with the `archive` package and only
// the pure verify/read paths are exercised.
import 'dart:convert';
import 'dart:io';

import 'package:archive/archive.dart';
import 'package:crypto/crypto.dart';
import 'package:darspack/core/backup.dart';
import 'package:darspack/core/manifest.dart';
import 'package:flutter_test/flutter_test.dart';

String sha(List<int> bytes) => sha256.convert(bytes).toString();

/// Build a package ZIP in memory from manifest entries + member bytes.
List<int> buildZip({
  required List<Map<String, dynamic>> entries,
  Map<String, List<int>> members = const {},
  Set<String> omitMembers = const {},
  bool includeManifest = true,
  bool includeIndex = true,
}) {
  final archive = Archive();
  for (final entry in entries) {
    final path = entry['path'] as String;
    if (omitMembers.contains(path)) continue;
    final data = members[path] ?? <int>[];
    archive.addFile(ArchiveFile(path, data.length, data));
  }
  if (includeManifest) {
    final manifestBytes = utf8.encode(
      jsonEncode({
        'format': 'darspack-package',
        'version': 1,
        'created': '2026-11-19T09:00:00',
        'files': entries,
      }),
    );
    archive.addFile(
      ArchiveFile('manifest.json', manifestBytes.length, manifestBytes),
    );
  }
  if (includeIndex) {
    final html = utf8.encode('<html dir="rtl"></html>');
    archive.addFile(ArchiveFile('index.html', html.length, html));
  }
  return ZipEncoder().encode(archive);
}

Future<File> writeZip(Directory dir, String name, List<int> bytes) async {
  final f = File('${dir.path}/$name');
  await f.writeAsBytes(bytes);
  return f;
}

Map<String, dynamic> entry({
  required String path,
  required String name,
  required List<int> bytes,
  String? subject,
  int? chapter,
  String? kind,
}) => {
  'name': name,
  'sha256': sha(bytes),
  'size': bytes.length,
  'subject': subject,
  'chapter': chapter,
  'lesson': null,
  'school_year': '1405-1406',
  'kind': kind,
  'tags': <String>[],
  'path': path,
};

void main() {
  late Directory dir;
  setUp(() async {
    dir = await Directory.systemTemp.createTemp('darspack-pkg-');
  });
  tearDown(() async {
    await dir.delete(recursive: true);
  });

  test('backup filename is Jalali dated', () {
    // 2026-10-25 falls on 1405-08-03 (Aban).
    expect(
      backupFilename(DateTime(2026, 10, 25)),
      'darspack-backup-1405-08-03.zip',
    );
  });

  test('safeName replaces every unsafe character, keeps Persian', () {
    for (final bad in ['\\', '/', ':', '*', '?', '"', '<', '>', '|', '\n']) {
      expect(safeName('a${bad}b'), 'a_b', reason: 'safeName with $bad');
    }
    expect(safeName('نمونه سوال.pdf'), 'نمونه سوال.pdf');
    expect(safeName(''), 'file');
    expect(safeName('   '), 'file');
  });

  test('verify ok on an intact package', () async {
    final bytes = utf8.encode('content of file one');
    final entries = [
      entry(path: 'files/001 - جزوه.pdf', name: 'جزوه.pdf', bytes: bytes),
    ];
    final zip = await writeZip(
      dir,
      'ok.zip',
      buildZip(entries: entries, members: {'files/001 - جزوه.pdf': bytes}),
    );
    final report = await verifyPackage(zip);
    expect(report.ok, isTrue, reason: report.problems.join('; '));
    expect(report.problems, isEmpty);
  });

  test('verify detects a corrupted byte', () async {
    final bytes = utf8.encode('content of file one');
    final entries = [
      entry(path: 'files/001 - جزوه.pdf', name: 'جزوه.pdf', bytes: bytes),
    ];
    final tampered = List<int>.from(bytes)..[0] ^= 0xFF;
    final zip = await writeZip(
      dir,
      'bad.zip',
      buildZip(entries: entries, members: {'files/001 - جزوه.pdf': tampered}),
    );
    final report = await verifyPackage(zip);
    expect(report.ok, isFalse);
    expect(report.problems.length, 1);
    expect(report.problems.single, contains('خراب یا تغییرکرده'));
  });

  test('verify detects a missing member', () async {
    final bytes = utf8.encode('content of file one');
    final entries = [
      entry(path: 'files/001 - جزوه.pdf', name: 'جزوه.pdf', bytes: bytes),
    ];
    final zip = await writeZip(
      dir,
      'missing.zip',
      buildZip(entries: entries, omitMembers: {'files/001 - جزوه.pdf'}),
    );
    final report = await verifyPackage(zip);
    expect(report.ok, isFalse);
    expect(report.problems.any((p) => p.contains('گم‌شده')), isTrue);
  });

  test('verify detects a truncated member (size mismatch)', () async {
    final bytes = utf8.encode('content of file one');
    final entries = [
      entry(path: 'files/001 - جزوه.pdf', name: 'جزوه.pdf', bytes: bytes),
    ];
    final zip = await writeZip(
      dir,
      'trunc.zip',
      buildZip(
        entries: entries,
        members: {'files/001 - جزوه.pdf': bytes.sublist(0, bytes.length - 5)},
      ),
    );
    final report = await verifyPackage(zip);
    expect(report.ok, isFalse);
    expect(
      report.problems.any((p) => p.contains('اندازه‌ی فایل متفاوت است')),
      isTrue,
    );
  });

  test('verify flags extra files', () async {
    final bytes = utf8.encode('content');
    final entries = [
      entry(path: 'files/001 - x.pdf', name: 'x.pdf', bytes: bytes),
    ];
    final archive = Archive();
    archive.addFile(ArchiveFile('files/001 - x.pdf', bytes.length, bytes));
    archive.addFile(
      ArchiveFile('files/999 - extra.pdf', 9, utf8.encode('sneaked in')),
    );
    final manifestBytes = utf8.encode(
      jsonEncode({
        'format': 'darspack-package',
        'version': 1,
        'created': '2026-11-19T09:00:00',
        'files': entries,
      }),
    );
    archive.addFile(
      ArchiveFile('manifest.json', manifestBytes.length, manifestBytes),
    );
    final zip = await writeZip(dir, 'extra.zip', ZipEncoder().encode(archive));
    final report = await verifyPackage(zip);
    expect(report.ok, isFalse);
    expect(report.problems.any((p) => p.contains('فایل اضافه')), isTrue);
  });

  test('verify rejects a ZIP without a manifest', () async {
    final archive = Archive();
    final data = utf8.encode('data');
    archive.addFile(ArchiveFile('files/001 - x.pdf', data.length, data));
    final zip = await writeZip(dir, 'bare.zip', ZipEncoder().encode(archive));
    final report = await verifyPackage(zip);
    expect(report.ok, isFalse);
    expect(report.problems, ['manifest.json در بسته نیست — بسته معتبر نیست']);
  });

  test('verify ignores backup members (catalog.db, RESTORE guide)', () async {
    final bytes = utf8.encode('content');
    final entries = [
      entry(path: 'files/000001.pdf', name: 'جزوه.pdf', bytes: bytes),
    ];
    final archive = Archive();
    archive.addFile(ArchiveFile('files/000001.pdf', bytes.length, bytes));
    final manifestBytes = utf8.encode(
      jsonEncode({
        'format': 'darspack-package',
        'version': 1,
        'created': '2026-11-19T09:00:00',
        'files': entries,
      }),
    );
    archive.addFile(
      ArchiveFile('manifest.json', manifestBytes.length, manifestBytes),
    );
    final dbBytes = utf8.encode('fake-sqlite');
    archive.addFile(ArchiveFile('catalog.db', dbBytes.length, dbBytes));
    final guide = utf8.encode('guide');
    archive.addFile(ArchiveFile('RESTORE-راهنما.txt', guide.length, guide));
    final zip = await writeZip(dir, 'backup.zip', ZipEncoder().encode(archive));
    final report = await verifyPackage(zip);
    expect(report.ok, isTrue, reason: report.problems.join('; '));
  });

  test('readManifest returns entries; rejects a wrong format', () async {
    final bytes = utf8.encode('content');
    final entries = [
      entry(
        path: 'files/001 - x.pdf',
        name: 'x.pdf',
        bytes: bytes,
        subject: 'ریاضی',
        chapter: 3,
        kind: 'نمونه‌سوال',
      ),
    ];
    final zip = await writeZip(
      dir,
      'read.zip',
      buildZip(entries: entries, members: {'files/001 - x.pdf': bytes}),
    );
    final read = await readManifest(zip);
    expect(read.length, 1);
    expect(read.single['subject'], 'ریاضی');
    expect(read.single['chapter'], 3);
    expect(read.single['kind'], 'نمونه‌سوال');
    expect(read.single['path'], 'files/001 - x.pdf');

    final bad = Archive();
    final badManifest = utf8.encode(
      jsonEncode({'format': 'something-else', 'version': 1, 'files': []}),
    );
    bad.addFile(ArchiveFile('manifest.json', badManifest.length, badManifest));
    final badZip = await writeZip(dir, 'badfmt.zip', ZipEncoder().encode(bad));
    expect(() => readManifest(badZip), throwsArgumentError);
  });

  test('makeIndexHtml is RTL and lists files', () {
    final html = makeIndexHtml({
      'created': '2026-11-19T09:00:00',
      'files': [
        {
          'name': 'جزوه ریاضی.pdf',
          'subject': 'ریاضی',
          'chapter': 3,
          'kind': 'جزوه',
        },
        {'name': 'x.pdf', 'subject': null, 'chapter': null, 'kind': null},
      ],
    });
    expect(html, contains('dir="rtl"'));
    expect(html, contains('جزوه ریاضی.pdf'));
    expect(html, contains('فصل 3'));
    expect(html, contains('2 فایل'));
  });
}
