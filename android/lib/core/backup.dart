// Full-library backup (پشتیبان‌گیری کامل کتابخانه).
//
// Port of Windows `core/backup.py`. The backup is BOTH things at once —
// a browsable درس‌پک (manifest + files + index.html via the normal
// export path) AND the catalog itself (a consistent snapshot of
// catalog.db, plus a short restore guide). Restore is the documented
// manual steps: replace catalog.db AND the whole files/ folder together
// (keep a safety copy of the current library first).
//
// CRITICAL: the ZIP's files/ keeps the catalog's own stored names
// (files/000001.pdf), NOT friendly display labels. The catalog.db
// snapshot points at those names, so a restore must replace catalog.db
// AND the whole files/ folder together.

import 'dart:convert';
import 'dart:io';

import 'package:archive/archive.dart';
import 'package:path/path.dart' as p;
import 'package:shamsi_date/shamsi_date.dart';
import 'package:sqflite/sqflite.dart';

import 'manifest.dart';

const String restoreGuide = '''بازگردانی پشتیبان درس‌پک — راهنما
=================================

این فایل یک پشتیبانِ کامل کتابخانه است:
  - manifest.json + پوشه‌ی files/ + index.html : فایل‌ها و فهرست قابل مرور آن‌ها
  - catalog.db : پایگاه داده (فراداده، درس‌ها، برچسب‌ها، تاریخچه)
  - RESTORE-راهنما.txt : همین راهنما

نکته‌ی مهم: نام فایل‌های داخل پوشه‌ی files/ این پشتیبان، همان نام‌های داخلی
کاتالوگ‌اند (مثل 000001.pdf)، نه نام‌های نمایشی. catalog.db داخل پشتیبان به
همین نام‌ها اشاره می‌کند. بنابراین باید catalog.db و کل پوشه‌ی files/ را با هم
جایگزین کنید. اگر فایل‌ها را با نام دیگری کپی کنید، کاتالوگ آنها را نمی‌شناسد.
هیچ‌چیز پاک نمی‌شود: در نخستین باز شدن برنامه، هر فایلی که محتوای آن (اثر
انگشت SHA-256) با ردیفی از کاتالوگ که فایلش گم شده هم‌خوانی دارد، سر جای خود
برمی‌گردد؛ فقط محتوای بی‌صاحب پاکسازی می‌شود. بررسی سلامت نیز ردیف‌های
گم‌شده را علامت‌گذاری می‌کند.

بازگردانی (گام‌به‌گام):
  1. برنامه‌ی DarsPack را کاملاً ببندید.
  2. از پوشه‌ی کتابخانه‌ی فعلی یک کپی امن در جای دیگری بگیرید.
  3. محتوای پوشه‌ی کتابخانه را با محتوای این پشتیبان جایگزین کنید:
     catalog.db (و catalog.db-wal / catalog.db-shm اگر وجود دارند) را پاک کنید،
     catalog.db این پشتیبان را کنار پوشه‌ی files/ بگذارید؛ سپس کل پوشه‌ی
     files/ داخل پشتیبان را جای files/ فعلی کپی/جایگزین کنید.
  4. برنامه را دوباره باز کنید؛ «بررسی سلامت» در شروع، هر problem را نشان می‌دهد.

هشدار: بسته‌ی پشتیبان را روی همان دیسک نگه ندارید — فلش یا مسیر دیگری بهتر است.
''';

/// Jalali-dated name for the backup ZIP: darspack-backup-1405-08-03.zip.
String backupFilename([DateTime? today]) {
  final jalali = Jalali.fromDateTime(today ?? DateTime.now());
  final y = jalali.year.toString().padLeft(4, '0');
  final m = jalali.month.toString().padLeft(2, '0');
  final d = jalali.day.toString().padLeft(2, '0');
  return 'darspack-backup-$y-$m-$d.zip';
}

/// Write the one-click backup ZIP; returns the export info dict.
///
/// Order matters: the snapshot is taken FIRST (a consistent
/// point-in-time copy of the catalog), then the files are exported from
/// the same connection. Both parts live in one ZIP so nothing can
/// half-arrive.
///
/// The snapshot uses SQLite `VACUUM INTO`, which copies the database
/// INCLUDING committed WAL content — never zip catalog.db directly, a
/// live WAL file is not a snapshot. (`VACUUM INTO` cannot run inside a
/// transaction, so this must be called outside one.)
Future<Map<String, dynamic>> backupLibrary(
  Database db,
  Directory filesDir,
  File outFile,
) async {
  final ids = [
    for (final row in await db.query('files', columns: ['id'], orderBy: 'id'))
      row['id'] as int,
  ];

  // Snapshot first, into a temp file next to the output.
  final tmpDir = await Directory.systemTemp.createTemp('darspack-backup-');
  try {
    final snapshot = File(p.join(tmpDir.path, 'catalog.db'));
    await db.execute('VACUUM INTO ?', [snapshot.path]);

    final info = await exportPackage(
      db,
      filesDir,
      ids,
      outFile,
      storedNames: true,
    );

    final existing = ZipDecoder().decodeBytes(await outFile.readAsBytes());
    final archive = Archive();
    for (final f in existing.files) {
      archive.addFile(f);
    }
    final snapshotBytes = await snapshot.readAsBytes();
    archive.addFile(
      ArchiveFile('catalog.db', snapshotBytes.length, snapshotBytes),
    );
    final guideBytes = utf8.encode(restoreGuide);
    archive.addFile(
      ArchiveFile('RESTORE-راهنما.txt', guideBytes.length, guideBytes),
    );
    await outFile.writeAsBytes(ZipEncoder().encode(archive));
    return info;
  } finally {
    try {
      await tmpDir.delete(recursive: true);
    } catch (_) {}
  }
}
