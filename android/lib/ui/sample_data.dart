// Screenshot/widget-test seeding — mirrors Windows scripts/app_harness.py
// SandboxEnvironment._populate_sample_files exactly (same 8 files, same
// subjects/chapters/kinds/notes; note the فارسی file is year 1404-1405
// in the harness, but the spec'd updateFileMeta has no schoolYear
// parameter, so the seeded year is the import-stamped current year).
import 'dart:io';

import 'package:darspack/core/core.dart';
import 'package:path/path.dart' as p;

/// The 8 Windows sandbox sample files:
/// (name, subject, chapter, lesson, kind, schoolYear, note)
const List<(String, String?, int?, int?, String, String, String)>
    sampleFiles = [
  ('جزوه ریاضی فصل ۳ نهم.pdf', 'ریاضی', 3, null, 'جزوه', '1405-1406',
      'مهم برای امتحان'),
  ('نمونه سوال ریاضی نهم فصل ۳.pdf', 'ریاضی', 3, null, 'نمونه‌سوال',
      '1405-1406', 'سوالات تستی'),
  ('کاربرگ علوم تجربی درس ۵.pdf', 'علوم تجربی', null, 5, 'کاربرگ',
      '1405-1406', ''),
  ('جزوه فارسی درس ۲ هشتم.pdf', 'فارسی', null, 2, 'جزوه', '1404-1405',
      'آرایه‌ها'),
  ('نمونه سوال علوم نهم فصل ۴.pdf', 'علوم تجربی', 4, null, 'نمونه‌سوال',
      '1405-1406', 'حرکت و نیرو'),
  ('تکلیف زبان انگلیسی درس ۳.pdf', 'انگلیسی', null, 3, 'تکلیف',
      '1405-1406', 'Grammar'),
  ('عکس تخته تدریس ریاضی فصل ۵.png', 'ریاضی', 5, null, 'جزوه', '1405-1406',
      'فرمول اتحاد'),
  ('فایل بدون درس برای تست.pdf', null, null, null, 'سایر', '1405-1406',
      'هنوز دسته‌بندی نشده'),
];

/// Seeds [library] with the 8 sample files (subject is applied here by
/// the seeder — the importer itself never auto-applies a subject).
/// With [extras] also adds: an exact duplicate, a rename hint, a version
/// conflict, two trash entries, activity rows and two hint rules, so the
/// duplicates/trash/activity screens have real content.
Future<void> seedSampleLibrary(Library library, {bool extras = false}) async {
  final tmp = await Directory.systemTemp.createTemp('darspack_seed_');
  final subjects = await library.subjectsWithCounts();
  int? subjectId(String? name) {
    if (name == null) return null;
    for (final s in subjects) {
      if (s.name == name) return s.id;
    }
    return null;
  }

  for (var i = 0; i < sampleFiles.length; i++) {
    final (name, subj, ch, les, kind, year, note) = sampleFiles[i];
    final src = File(p.join(tmp.path, name));
    await src.writeAsString('sample dummy school content $i $name');
    final res = await library.importFile(src);
    if (res.fileId != null) {
      await library.updateFileMeta(
        res.fileId!,
        subjectId: subjectId(subj),
        chapter: ch,
        lesson: les,
        kind: kind,
        note: note,
        clearSubject: subj == null,
      );
      assert(year.isNotEmpty); // year is import-stamped; see file header.
    }
  }

  if (!extras) return;

  // R1 exact duplicate: same bytes, same name, kept on purpose.
  final first = File(p.join(tmp.path, sampleFiles[0].$1));
  await library.importFile(first, keepDuplicate: true);
  // R3 rename hint: same content, different name.
  await library.importFile(first,
      displayName: 'جزوه ریاضی فصل ۳ (کپی).pdf', keepDuplicate: true);
  // R2 version conflict: same name, different content.
  final conflict = File(p.join(tmp.path, 'conflict.tmp'));
  await conflict.writeAsString('different content, same name');
  await library.importFile(conflict,
      displayName: sampleFiles[0].$1, keepDuplicate: true);

  // Two trash entries.
  for (final name in ['جزوه قدیمی ریاضی.pdf', 'نمونه سوال قدیمی.pdf']) {
    final src = File(p.join(tmp.path, name));
    await src.writeAsString('old file $name');
    final res = await library.importFile(src);
    if (res.fileId != null) await library.deleteFile(res.fileId!);
  }

  await library.learnHint('اتحاد', 'ریاضی');
  await library.learnHint('گرامر', 'انگلیسی');
  await library.logActivity('وارد کردن', 'جزوه ریاضی فصل ۳ نهم.pdf');
  await library.logActivity('راستی‌آزمایی بسته', 'بسته‌ی شب امتحان');
}
