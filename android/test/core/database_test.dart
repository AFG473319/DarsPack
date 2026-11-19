// DB-backed behaviour — port of the Windows expectations for
// import/search/backup/trash/dedup.
//
// SKIPPED under `flutter test` on this Linux VM: sqflite has no
// Linux-desktop engine, so any sqflite call throws
// MissingPluginException on the host. These tests are written to run
// unchanged on a real Android device (or via integration_test, where
// the platform channel exists). Nothing here is faked: the skipped
// paths are exactly the ones listed as untested in the data-layer
// report — Library open/seed, import + duplicate detection, DB search,
// trash round-trip, backup round-trip + verify, dedup groups, stats,
// activity log and learned hints.
import 'dart:io';

import 'package:archive/archive.dart';

import 'package:darspack/core/library.dart';
import 'package:darspack/core/normalize.dart';
import 'package:flutter_test/flutter_test.dart';

Future<Library> openTempLib(Directory dir) =>
    Library.open(root: Directory('${dir.path}/lib'));

Future<File> sample(Directory dir, String name, List<int> bytes) async {
  final f = File('${dir.path}/$name');
  await f.writeAsBytes(bytes);
  return f;
}

void main() {
  group(
    'db-backed library behaviour',
    skip:
        'sqflite needs a real Android/iOS platform channel; unavailable under flutter test on Linux',
    () {
      late Directory tmp;

      setUp(() async {
        tmp = await Directory.systemTemp.createTemp('darspack-db-');
      });

      tearDown(() async {
        await tmp.delete(recursive: true);
      });

      test(
        'open seeds the 14 default subjects only on a fresh library',
        () async {
          final lib = await openTempLib(tmp);
          try {
            final subjects = await lib.subjectsWithCounts();
            expect(subjects.length, 14);
            expect(subjects.map((s) => s.name), contains('ریاضی'));
            expect(subjects.map((s) => s.name), contains('علوم تجربی'));
            expect(await lib.unclassifiedCount(), 0);
          } finally {
            await lib.close();
          }
          // Reopen: no duplicate seeds.
          final lib2 = await openTempLib(tmp);
          try {
            expect((await lib2.subjectsWithCounts()).length, 14);
          } finally {
            await lib2.close();
          }
        },
      );

      test('import stores the file, stamps name_norm + school year', () async {
        final lib = await openTempLib(tmp);
        try {
          final src = await sample(
            tmp,
            'كاربرگ فيزيك.pdf', // Arabic ك and ي on purpose
            ascii('lesson-content'),
          );
          final r = await lib.importFile(src);
          expect(r.status, 'imported');
          expect(r.fileId, 1);
          final f = await lib.getFile(1);
          expect(f, isNotNull);
          expect(f!.storedName, '000001.pdf');
          expect(f.nameNorm, matchKey('كاربرگ فيزيك.pdf'));
          expect(f.schoolYear, isNotNull);
          expect(f.subjectId, isNull); // NEVER auto-applied
          expect(f.kind, 'کاربرگ'); // kind hint IS applied
          expect(await lib.storedFileFor(f).exists(), isTrue);
          expect(await lib.unclassifiedCount(), 1);
        } finally {
          await lib.close();
        }
      });

      test('duplicate is reported, names the twin, and is skipped', () async {
        final lib = await openTempLib(tmp);
        try {
          final a = await sample(tmp, 'a.pdf', ascii('same-bytes'));
          final b = await sample(tmp, 'b.pdf', ascii('same-bytes'));
          final results = await lib.importFiles([a, b]);
          expect(results.map((r) => r.status), ['imported', 'duplicate']);
          expect(results[1].existingId, 1);
          expect(results[1].messageFa, contains('a.pdf'));
          // keepDuplicate override imports it anyway.
          final kept = await lib.importFile(b, keepDuplicate: true);
          expect(kept.status, 'imported');
          expect((await lib.searchFiles()).length, 2);
        } finally {
          await lib.close();
        }
      });

      test('one bad file never aborts a batch', () async {
        final lib = await openTempLib(tmp);
        try {
          final ok = await sample(tmp, 'ok.pdf', ascii('data'));
          final results = await lib.importFiles([
            ok,
            File('${tmp.path}/gone.pdf'),
          ]);
          expect(results.map((r) => r.status), ['imported', 'error']);
        } finally {
          await lib.close();
        }
      });

      test('DB search: digits, فصل phrases, subject, tags, ranking', () async {
        final lib = await openTempLib(tmp);
        try {
          await lib.importFile(
            await sample(tmp, 'نمونه سوال ریاضی فصل 3.pdf', ascii('one')),
          );
          await lib.importFile(
            await sample(tmp, 'کاربرگ ریاضی فصل دو.pdf', ascii('two')),
          );
          await lib.importFile(
            await sample(tmp, 'summary.PDF', ascii('three')),
          );
          expect(
            (await lib.searchFiles(query: 'فصل 3')).map((f) => f.originalName),
            ['نمونه سوال ریاضی فصل 3.pdf'],
          );
          expect(
            (await lib.searchFiles(query: 'فصل ۳')).map((f) => f.originalName),
            ['نمونه سوال ریاضی فصل 3.pdf'],
          );
          expect(
            (await lib.searchFiles(query: 'فصل دو')).map((f) => f.originalName),
            ['کاربرگ ریاضی فصل دو.pdf'],
          );
          expect((await lib.searchFiles(query: 'ریاضی')).length, 2);
          expect(
            (await lib.searchFiles(
              query: 'SUMMARY',
            )).map((f) => f.originalName),
            ['summary.PDF'],
          );
          expect((await lib.searchFiles(query: '')).length, 3);
          // Prefix rank: جزوه-prefixed name first.
          await lib.importFile(
            await sample(tmp, 'جزوه علوم تجربی.pdf', ascii('four')),
          );
          expect(
            (await lib.searchFiles(query: 'جزوه')).first.originalName,
            'جزوه علوم تجربی.pdf',
          );
          // Structured chapter column: a classified file whose name lacks فصل.
          final summary = (await lib.searchFiles(query: 'summary')).single;
          await lib.updateFileMeta(summary.id, chapter: 5);
          expect((await lib.searchFiles(query: 'فصل 5')).map((f) => f.id), [
            summary.id,
          ]);
          expect((await lib.searchFiles(query: '', limit: 2)).length, 2);
        } finally {
          await lib.close();
        }
      });

      test('classify: subject + tags + clearSubject', () async {
        final lib = await openTempLib(tmp);
        try {
          final r = await lib.importFile(
            await sample(tmp, 'جزوه ریاضی فصل 3.pdf', ascii('x')),
          );
          final subjects = await lib.subjectsWithCounts();
          final math = subjects.firstWhere((s) => s.name == 'ریاضی');
          await lib.updateFileMeta(
            r.fileId!,
            subjectId: math.id,
            chapter: 3,
            kind: 'جزوه',
            note: 'یادداشت مهم',
            tags: ['امتحان', 'مهم'],
          );
          final f = await lib.getFile(r.fileId!);
          expect(f!.subjectName, 'ریاضی');
          expect(f.tags, ['امتحان', 'مهم']);
          expect((await lib.searchFiles(query: 'امتحان')).length, 1);
          expect((await lib.searchFiles(query: 'میانترم')), isEmpty);
          await lib.updateFileMeta(r.fileId!, clearSubject: true);
          expect((await lib.getFile(r.fileId!))!.subjectId, isNull);
          expect(await lib.unclassifiedCount(), 1);
        } finally {
          await lib.close();
        }
      });

      test('trash: delete → list → restore → empty', () async {
        final lib = await openTempLib(tmp);
        try {
          final r = await lib.importFile(
            await sample(tmp, 'جزوه ریاضی.pdf', ascii('trash-me')),
          );
          await lib.deleteFile(r.fileId!);
          expect(await lib.getFile(r.fileId!), isNull);
          final trash = await lib.listTrash();
          expect(trash.length, 1);
          expect(trash.single.originalName, 'جزوه ریاضی.pdf');
          expect(trash.single.storedName, '000001.pdf');
          await lib.restoreTrash(trash.single.trashName);
          expect((await lib.listTrash()), isEmpty);
          expect((await lib.searchFiles()).length, 1);
          // Delete again and empty permanently.
          final again = (await lib.searchFiles()).single;
          await lib.deleteFile(again.id);
          await lib.emptyTrash();
          expect((await lib.listTrash()), isEmpty);
        } finally {
          await lib.close();
        }
      });

      test('backup round-trip + verify + tamper detection', () async {
        final lib = await openTempLib(tmp);
        late File backup;
        try {
          await lib.importFile(
            await sample(tmp, 'جزوه ریاضی.pdf', ascii('one')),
          );
          await lib.importFile(
            await sample(tmp, 'کاربرگ علوم.pdf', ascii('two')),
          );
          backup = await lib.exportBackup();
          expect(await backup.exists(), isTrue);
          expect(backup.path, contains('darspack-backup-'));
        } finally {
          await lib.close();
        }
        final lib2 = await openTempLib(tmp);
        try {
          final report = await lib2.verifyPackage(backup);
          expect(report.ok, isTrue, reason: report.problems.join('; '));
          // Tamper: rewrite the ZIP with one corrupted member byte and
          // verify must fail (structure stays a valid ZIP).
          final tampered = File('${tmp.path}/tampered.zip');
          final archive = ZipDecoder().decodeBytes(await backup.readAsBytes());
          final victim = archive.files.firstWhere(
            (f) => f.name.startsWith('files/'),
          );
          final corrupted = List<int>.from(victim.content as List<int>)
            ..[0] ^= 0xFF;
          final rebuilt = Archive();
          for (final f in archive.files) {
            rebuilt.addFile(
              f.name == victim.name
                  ? ArchiveFile(f.name, corrupted.length, corrupted)
                  : f,
            );
          }
          await tampered.writeAsBytes(ZipEncoder().encode(rebuilt));
          final bad = await lib2.verifyPackage(tampered);
          expect(bad.ok, isFalse);
        } finally {
          await lib2.close();
        }
      });

      test('package export/import round-trips metadata as prefill', () async {
        final lib = await openTempLib(tmp);
        late File pkg;
        try {
          final r = await lib.importFile(
            await sample(
              tmp,
              'نمونه سوال ریاضی فصل 3.pdf',
              ascii('classified'),
            ),
          );
          final math = (await lib.subjectsWithCounts()).firstWhere(
            (s) => s.name == 'ریاضی',
          );
          await lib.updateFileMeta(
            r.fileId!,
            subjectId: math.id,
            chapter: 3,
            kind: 'نمونه‌سوال',
            tags: ['امتحان'],
          );
          pkg = await lib.exportPackage([r.fileId!]);
          expect((await lib.verifyPackage(pkg)).ok, isTrue);
        } finally {
          await lib.close();
        }
        // Import into a fresh library: file lands unclassified, prefill
        // carries the subject + tags.
        final fresh = Directory('${tmp.path}/fresh');
        final lib2 = await Library.open(root: fresh);
        try {
          final results = await lib2.importPackage(pkg);
          expect(results.length, 1);
          expect(results.single.status, 'imported');
          expect(results.single.prefill?['subject'], 'ریاضی');
          expect(results.single.prefill?['tags'], ['امتحان']);
          final f = await lib2.getFile(results.single.fileId!);
          expect(f!.subjectId, isNull); // subject NEVER auto-applied
          expect(f.chapter, 3);
          expect(f.kind, 'نمونه‌سوال');
        } finally {
          await lib2.close();
        }
      });

      test('dedup: R1/R2/R3 flag-only groups', () async {
        final lib = await openTempLib(tmp);
        try {
          await lib.importFile(
            await sample(tmp, 'a.pdf', ascii('same')),
            keepDuplicate: true,
          );
          await lib.importFile(
            await sample(tmp, 'b.pdf', ascii('same')),
            keepDuplicate: true,
          );
          await lib.importFile(await sample(tmp, 'c.pdf', ascii('v1')));
          await lib.importFile(await sample(tmp, 'c.pdf', ascii('v2')));
          expect((await lib.duplicateGroups()).length, 1);
          expect((await lib.renameHints()).length, 1); // same sha, diff names
          expect(
            (await lib.versionConflicts()).length,
            1,
          ); // same name, diff sha
          final stats = await lib.stats();
          expect(stats['totalFiles'], 4);
          expect(stats['duplicates'], 1);
          expect(stats['wastedBytes'], 4); // one extra copy of 'same'
        } finally {
          await lib.close();
        }
      });

      test('activity log and learned hints', () async {
        final lib = await openTempLib(tmp);
        try {
          await lib.logActivity('test', 'hello');
          final entries = await lib.activityLog();
          expect(entries.any((e) => e.action == 'test'), isTrue);
          await lib.learnHint('فیزیک', 'فیزیک');
          await lib.learnHint('فیزیک', 'فیزیک');
          final hints = await lib.loadHints();
          expect(hints['فیزیک']?.hits, 2);
        } finally {
          await lib.close();
        }
      });

      test('reopen sweeps orphan tmp files but keeps real files', () async {
        final lib = await openTempLib(tmp);
        try {
          await lib.importFile(await sample(tmp, 'سالم.pdf', ascii('real')));
          await File(
            '${tmp.path}/lib/files/tmp_7.pdf',
          ).writeAsBytes(ascii('tmp'));
          await File(
            '${tmp.path}/lib/files/999999.pdf',
          ).writeAsBytes(ascii('orphan'));
        } finally {
          await lib.close();
        }
        final lib2 = await openTempLib(tmp);
        try {
          expect(
            await File('${tmp.path}/lib/files/tmp_7.pdf').exists(),
            isFalse,
          );
          expect(
            await File('${tmp.path}/lib/files/999999.pdf').exists(),
            isFalse,
          );
          expect(
            await File('${tmp.path}/lib/files/000001.pdf').exists(),
            isTrue,
          );
        } finally {
          await lib2.close();
        }
      });
    },
  );
}

List<int> ascii(String s) => s.codeUnits; // test content is ASCII-only
