// Duplicate grouping and conflict detection (تشخیص تکراری و تضاد).
//
// Port of Windows `core/dedup.py`. Four rules — and the rule of rules:
// *flag only*. Nothing here deletes or overwrites; the UI shows these
// groups and the user decides.
//
//   R1 exact duplicate  : same sha256 (محتوای یکسان)
//   R2 version conflict : same normalized name, different sha256
//                         (نسخه‌های متفاوت با نام یکسان)
//   R3 rename hint      : same sha256, different normalized names
//                         (یک محتوا با نام‌های مختلف)
//   R4-lite (likely_versions): names differing only by re-download noise
//                         («x (1).pdf», «نسخه نهایی», «final») with
//                         different content — a WEAK hint, flag-only

import 'package:sqflite/sqflite.dart';

import 'models.dart';

Future<List<LibraryFile>> _rowsForSha(Database db, String sha) async {
  final rows = await db.query(
    'files',
    where: 'sha256 = ?',
    whereArgs: [sha],
    orderBy: 'imported_at',
  );
  return [for (final r in rows) LibraryFile.fromRow(r)];
}

Future<List<LibraryFile>> _rowsForNameNorm(Database db, String nameNorm) async {
  final rows = await db.query(
    'files',
    where: 'name_norm = ?',
    whereArgs: [nameNorm],
    orderBy: 'imported_at',
  );
  return [for (final r in rows) LibraryFile.fromRow(r)];
}

/// R1 — every sha256 owned by more than one row.
Future<List<DuplicateGroup>> duplicateGroups(Database db) async {
  final shas = await db.rawQuery(
    'SELECT sha256 FROM files GROUP BY sha256 HAVING COUNT(*) > 1',
  );
  final groups = <DuplicateGroup>[];
  for (final row in shas) {
    final files = await _rowsForSha(db, row['sha256'] as String);
    if (files.length < 2) continue;
    final wasted = (files.length - 1) * files.first.sizeBytes;
    groups.add(
      DuplicateGroup(
        labelFa: 'تکراری کامل',
        files: files,
        detailFa:
            '${files.length} نسخه‌ی یکسان — فضای اشغال‌شده‌ی تکراری: $wasted بایت',
      ),
    );
  }
  return groups;
}

/// R2 — same normalized name saved with different content.
Future<List<VersionConflict>> versionConflicts(Database db) async {
  final names = await db.rawQuery(
    'SELECT name_norm FROM files '
    'GROUP BY name_norm HAVING COUNT(DISTINCT sha256) > 1',
  );
  final groups = <VersionConflict>[];
  for (final row in names) {
    final files = await _rowsForNameNorm(db, row['name_norm'] as String);
    groups.add(
      VersionConflict(
        labelFa: 'نسخه‌های متفاوت با نام یکسان',
        files: files,
        detailFa:
            'احتمالاً نسخه‌های مختلف یک فایل‌اند — قبل از استفاده مقایسه کن',
      ),
    );
  }
  return groups;
}

/// R3 — identical content saved under different names.
Future<List<RenameHint>> renameHints(Database db) async {
  final hints = <RenameHint>[];
  for (final g in await duplicateGroups(db)) {
    if ({for (final f in g.files) f.nameNorm}.length > 1) {
      hints.add(
        RenameHint(
          labelFa: 'یک محتوا با نام‌های مختلف',
          files: g.files,
          detailFa: 'محتوای یکسان با نام‌های متفاوت ذخیره شده',
        ),
      );
    }
  }
  return hints;
}

// --- R4-lite: likely different versions of the same file -----------------
// Kept INSIDE dedup.dart on purpose: the noise patterns below are the
// core-algorithm material, so they must not leak into normalize.dart.

final RegExp _noiseRe = RegExp(
  r'(\(\d+\))' // the browser's re-download suffix: «x (1).pdf»
  r'|(نسخه ?\d+)' // «نسخه ۲»
  r'|(نهایی|اصلاح ?شده|جدید|کپی|کپی شده)'
  r'|(final|copy|v\d+)', // Latin twins of the same habits
);

final RegExp _spaceBeforeExtRe = RegExp(
  r'\s+(\.\w+)$',
); // «x (1) .pdf» → «x.pdf»

/// Drop re-download/version noise from a match key (key only — the
/// stored original_name is never touched). Pure helper, unit-testable.
String stripVersionNoise(String nameNorm) {
  var cleaned = nameNorm.replaceAll(_noiseRe, ' ');
  cleaned = cleaned.replaceAllMapped(_spaceBeforeExtRe, (m) => m.group(1)!);
  return cleaned.split(' ').where((w) => w.isNotEmpty).join(' ');
}

/// R4-lite — names differing only by version noise, different content.
///
/// R2 only fires on EXACT normalized-name equality, so the most common
/// real pattern escapes it: the teacher's corrected worksheet
/// re-downloaded as «x (1).pdf» sits beside the outdated twin. Group
/// rows whose noise-stripped key matches when the group holds >1
/// distinct sha256 AND >1 distinct name (otherwise every single file
/// would self-group). Weak hint by design: false positives are
/// acceptable because nothing ever acts on this group automatically.
Future<List<VersionConflict>> likelyVersions(Database db) async {
  final rows = await db.query('files', orderBy: 'imported_at');
  final buckets = <String, List<LibraryFile>>{};
  for (final row in rows) {
    final file = LibraryFile.fromRow(row);
    var key = stripVersionNoise(file.nameNorm);
    if (key.isEmpty) key = file.nameNorm;
    buckets.putIfAbsent(key, () => []).add(file);
  }
  final groups = <VersionConflict>[];
  final keys = buckets.keys.toList()..sort();
  for (final key in keys) {
    final groupRows = buckets[key]!;
    if ({for (final f in groupRows) f.sha256}.length > 1 &&
        {for (final f in groupRows) f.nameNorm}.length > 1) {
      groups.add(
        VersionConflict(
          labelFa: 'نسخه‌های احتمالی',
          files: groupRows,
          detailFa:
              'احتمالاً نسخه‌های مختلف یک فایل‌اند — قبل از استفاده مقایسه کن',
        ),
      );
    }
  }
  return groups;
}
