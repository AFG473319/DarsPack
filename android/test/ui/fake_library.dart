// In-memory fake of the real Library (test-only).
//
// sqflite has no Linux-desktop engine, so the real SQLite Library
// throws MissingPluginException under `flutter test` on this VM (the
// data agent's DB tests skip for the same reason). Widget tests and
// the screenshot harness therefore run against this fake, which
// implements the REAL Library API (same signatures, same rules:
// SHA-256 dedup by hash, chapter/lesson/kind hints applied at import,
// subject NEVER auto-applied) with an in-memory catalog + real files
// on disk. The app itself (lib/) uses the real SQLite Library; this
// file is never imported by app code.
import 'dart:convert';
import 'dart:io';

import 'package:archive/archive.dart';
import 'package:crypto/crypto.dart';
import 'package:darspack/core/backup.dart' as backup;
import 'package:darspack/core/core.dart';
import 'package:darspack/core/manifest.dart' as manifest;
import 'package:path/path.dart' as p;

class FakeLibrary extends Library {
  final Directory root;
  FakeLibrary(this.root);

  final List<LibraryFile> _files = [];
  final List<TrashEntry> _trash = [];
  final List<ActivityEntry> _activity = [];
  final Map<String, LearnedHint> _hints = {};
  var _savedBytes = 0;
  var _nextId = 1;
  var _nextActivityId = 1;

  Directory get _filesDir => Directory(p.join(root.path, 'files'));
  Directory get _trashDir => Directory(p.join(root.path, 'files', '.trash'));

  @override
  Directory get filesDir => _filesDir;

  @override
  String get rootPath => root.path;

  @override
  Future<void> close() async {}

  List<Subject> get _subjects => defaultSubjects
      .asMap()
      .entries
      .map((e) => Subject(
          id: e.key + 1, name: e.value, normalized: matchKey(e.value)))
      .toList();

  String? _subjectName(int? id) {
    if (id == null) return null;
    for (final s in _subjects) {
      if (s.id == id) return s.name;
    }
    return null;
  }

  int? _subjectIdByName(String? name) {
    if (name == null) return null;
    for (final s in _subjects) {
      if (s.name == name || s.normalized == matchKey(name)) return s.id;
    }
    return null;
  }

  void _log(String action, String detail) {
    _activity.insert(
      0,
      ActivityEntry(
          id: _nextActivityId++, ts: DateTime.now().toIso8601String(), action: action, detail: detail),
    );
  }

  @override
  Future<void> logActivity(String action, String detail) async {
    _log(action, detail);
  }

  @override
  Future<void> learnHint(String token, String subjectName) async {
    final key = matchKey(token);
    final old = _hints[key];
    _hints[key] = (
      subject: subjectName,
      hits: (old?.hits ?? 1) + 1,
    );
  }

  @override
  Future<Map<String, LearnedHint>> loadHints() async =>
      Map<String, LearnedHint>.of(_hints);

  @override
  File storedFileFor(LibraryFile f) =>
      File(p.join(_filesDir.path, f.storedName));

  @override
  Future<List<LibraryFile>> searchFiles({
    String query = '',
    int? subjectId,
    String? kind,
    String? schoolYear,
    int limit = 200,
    bool unclassifiedOnly = false,
  }) async {
    var out = List<LibraryFile>.from(_files);
    if (subjectId != null) {
      out = out.where((f) => f.subjectId == subjectId).toList();
    }
    if (kind != null) out = out.where((f) => f.kind == kind).toList();
    if (schoolYear != null) {
      out = out.where((f) => f.schoolYear == schoolYear).toList();
    }
    if (unclassifiedOnly) {
      out = out.where((f) => f.subjectId == null).toList();
    }
    final q = query.trim();
    if (q.isNotEmpty) {
      final norm = matchKey(latinDigits(q));
      int? chapterQ;
      int? lessonQ;
      final cm = RegExp(r'فصل\s*([0-9]{1,2})').firstMatch(norm);
      if (cm != null) chapterQ = int.tryParse(cm.group(1)!);
      final lm = RegExp(r'درس\s*([0-9]{1,2})').firstMatch(norm);
      if (lm != null) lessonQ = int.tryParse(lm.group(1)!);
      final tokens = norm
          .split(' ')
          .where((t) => t.isNotEmpty && t != 'فصل' && t != 'درس')
          .toList()
          .take(8)
          .toList();
      bool matches(LibraryFile f) {
        if (chapterQ != null && f.chapter != chapterQ) return false;
        if (lessonQ != null && f.lesson != lessonQ) return false;
        final hay = [
          f.nameNorm,
          matchKey(f.subjectName ?? ''),
          matchKey(f.note),
          matchKey(f.kind ?? ''),
          ...f.tags.map(matchKey),
        ].join(' ');
        for (final t in tokens) {
          final digits = int.tryParse(t);
          if (digits != null) {
            if (f.chapter == digits || f.lesson == digits) continue;
          }
          if (!hay.contains(t)) return false;
        }
        return true;
      }

      out = out.where(matches).toList();
      if (tokens.isNotEmpty) {
        final first = tokens.first;
        out.sort((a, b) {
          final ap = a.nameNorm.startsWith(first) ? 0 : 1;
          final bp = b.nameNorm.startsWith(first) ? 0 : 1;
          if (ap != bp) return ap - bp;
          return b.importedAt.compareTo(a.importedAt);
        });
      } else {
        out.sort((a, b) => b.importedAt.compareTo(a.importedAt));
      }
    } else {
      out.sort((a, b) => b.importedAt.compareTo(a.importedAt));
    }
    if (out.length > limit) out = out.sublist(0, limit);
    return out;
  }

  @override
  Future<List<Subject>> subjectsWithCounts() async {
    final counts = <int, int>{};
    for (final f in _files) {
      if (f.subjectId != null) {
        counts[f.subjectId!] = (counts[f.subjectId!] ?? 0) + 1;
      }
    }
    return _subjects
        .map((s) => Subject(
            id: s.id,
            name: s.name,
            normalized: s.normalized,
            fileCount: counts[s.id] ?? 0))
        .toList();
  }

  @override
  Future<int> unclassifiedCount() async =>
      _files.where((f) => f.subjectId == null).length;

  @override
  Future<ImportResult> importFile(
    File src, {
    String? displayName,
    Map<String, dynamic>? meta,
    bool keepDuplicate = false,
  }) async {
    final name = displayName ?? p.basename(src.path);
    final stem =
        name.contains('.') ? name.substring(0, name.lastIndexOf('.')) : name;
    final suggestion = suggest(stem);
    meta ??= {};
    final kind = meta['kind'] as String? ?? suggestion.kind;
    Map<String, dynamic>? prefill;
    if (meta['subject'] != null || meta['tags'] != null) {
      prefill = {
        'subject': meta['subject'],
        'tags': List<String>.from((meta['tags'] as List?) ?? const []),
      };
    }
    try {
      final bytes = await src.readAsBytes();
      final hash = sha256.convert(bytes).toString();
      final twin = _files.where((f) => f.sha256 == hash).toList();
      if (twin.isNotEmpty && !keepDuplicate) {
        _savedBytes += bytes.length;
        return ImportResult(
          status: 'duplicate',
          messageFa: '«$name» تکرارِ «${twin.first.originalName}» است',
          existingId: twin.first.id,
          prefill: prefill,
        );
      }
      final id = _nextId++;
      final ext = p.extension(src.path);
      final stored = '${id.toString().padLeft(6, '0')}$ext';
      await _filesDir.create(recursive: true);
      final tmp = File(p.join(_filesDir.path, 'tmp_$stored'));
      await tmp.writeAsBytes(bytes);
      await tmp.rename(p.join(_filesDir.path, stored));
      _files.add(LibraryFile(
        id: id,
        storedName: stored,
        originalName: name,
        nameNorm: matchKey(name),
        sizeBytes: bytes.length,
        sha256: hash,
        importedAt: DateTime.now(),
        // Subject NEVER auto-applied — only chapter/lesson/kind hints are.
        chapter: meta['chapter'] as int? ?? suggestion.chapter,
        lesson: meta['lesson'] as int? ?? suggestion.lesson,
        schoolYear:
            meta['school_year'] as String? ?? currentSchoolYear(),
        kind: kind,
      ));
      _log('وارد کردن', name);
      return const ImportResult(status: 'imported', messageFa: 'وارد شد')
          .copyWithFileId(id);
    } catch (e) {
      return ImportResult(
          status: 'error', messageFa: 'خطا در وارد کردن $name: $e');
    }
  }

  @override
  Future<List<ImportResult>> importFiles(List<File> srcs) async {
    final out = <ImportResult>[];
    for (final f in srcs) {
      out.add(await importFile(f)); // one bad file never aborts a batch
    }
    return out;
  }

  @override
  Future<LibraryFile?> getFile(int id) async {
    for (final f in _files) {
      if (f.id == id) return f;
    }
    return null;
  }

  @override
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
    final i = _files.indexWhere((f) => f.id == id);
    if (i < 0) return;
    final f = _files[i];
    final newSubjectId = clearSubject ? null : (subjectId ?? f.subjectId);
    _files[i] = LibraryFile(
      id: f.id,
      storedName: f.storedName,
      originalName: f.originalName,
      nameNorm: f.nameNorm,
      sizeBytes: f.sizeBytes,
      sha256: f.sha256,
      importedAt: f.importedAt,
      subjectId: newSubjectId,
      subjectName: _subjectName(newSubjectId),
      chapter: chapter ?? f.chapter,
      lesson: lesson ?? f.lesson,
      schoolYear: f.schoolYear,
      kind: kind ?? f.kind,
      note: note ?? f.note,
      available: f.available,
      tags: tags ?? f.tags,
    );
    _log('ویرایش اطلاعات', f.originalName);
  }

  @override
  Future<void> deleteFile(int id) async {
    final i = _files.indexWhere((f) => f.id == id);
    if (i < 0) return;
    final f = _files.removeAt(i);
    await _trashDir.create(recursive: true);
    final stored = storedFileFor(f);
    if (await stored.exists()) {
      await stored.rename(p.join(_trashDir.path, f.storedName));
    }
    _trash.add(TrashEntry(
      trashName: f.storedName,
      originalName: f.originalName,
      storedName: f.storedName,
      subjectName: f.subjectName ?? '',
      size: f.sizeBytes,
      deletedAt: DateTime.now().toIso8601String(),
      kind: f.kind ?? 'سایر',
      tags: f.tags,
    ));
    _log('حذف', f.originalName);
  }

  @override
  Future<List<TrashEntry>> listTrash() async => List.unmodifiable(_trash);

  @override
  Future<void> restoreTrash(String trashName) async {
    final i = _trash.indexWhere((t) => t.trashName == trashName);
    if (i < 0) return;
    final t = _trash.removeAt(i);
    final id = _nextId++;
    final trashed = File(p.join(_trashDir.path, t.storedName));
    final ext = p.extension(t.storedName);
    final stored = '${id.toString().padLeft(6, '0')}$ext';
    if (await trashed.exists()) {
      await trashed.rename(p.join(_filesDir.path, stored));
    }
    var size = t.size;
    final restored = File(p.join(_filesDir.path, stored));
    if (await restored.exists()) size = await restored.length();
    _files.add(LibraryFile(
      id: id,
      storedName: stored,
      originalName: t.originalName,
      nameNorm: matchKey(t.originalName),
      sizeBytes: size,
      sha256: '',
      importedAt: DateTime.now(),
      subjectId: _subjectIdByName(t.subjectName.isEmpty ? null : t.subjectName),
      subjectName: t.subjectName.isEmpty ? null : t.subjectName,
      schoolYear: currentSchoolYear(),
      kind: t.kind,
      tags: t.tags,
    ));
    _log('بازیابی از سطل زباله', t.originalName);
  }

  @override
  Future<void> emptyTrash() async {
    if (await _trashDir.exists()) {
      await for (final e in _trashDir.list()) {
        await e.delete(recursive: true);
      }
    }
    final n = _trash.length;
    _trash.clear();
    _log('پاک‌سازی سطل زباله', '$n فایل');
  }

  Map<String, dynamic> _manifestFor(List<LibraryFile> files) => {
        'format': manifest.packageFormat,
        'version': manifest.packageVersion,
        'created': DateTime.now().toIso8601String().substring(0, 19),
        'files': files
            .map((f) => {
                  'name': f.originalName,
                  'sha256': f.sha256,
                  'size': f.sizeBytes,
                  'subject': f.subjectName,
                  'chapter': f.chapter,
                  'lesson': f.lesson,
                  'school_year': f.schoolYear,
                  'kind': f.kind,
                  'tags': f.tags,
                  'path': 'files/${f.storedName}',
                })
            .toList(),
      };

  Future<File> _buildZip(List<LibraryFile> files,
      {required String name, bool withCatalog = false}) async {
    final archive = Archive();
    final entries =
        (_manifestFor(files)['files'] as List).cast<Map<String, dynamic>>();
    for (var i = 0; i < files.length; i++) {
      final f = files[i];
      final stored = storedFileFor(f);
      if (!await stored.exists()) continue;
      final bytes = await stored.readAsBytes();
      final arc = withCatalog
          ? 'files/${f.storedName}'
          : 'files/${(i + 1).toString().padLeft(3, '0')} - ${manifest.safeName(f.originalName)}';
      entries[i]['path'] = arc;
      archive.addFile(ArchiveFile(arc, bytes.length, bytes));
    }
    final manifestMap = _manifestFor(files);
    manifestMap['files'] = entries;
    final manifestBytes = utf8.encode(jsonEncode(manifestMap));
    archive.addFile(
        ArchiveFile('manifest.json', manifestBytes.length, manifestBytes));
    archive.addFile(ArchiveFile('index.html', 0,
        utf8.encode(manifest.makeIndexHtml(manifestMap))));
    if (withCatalog) {
      final catalog = utf8.encode('{}');
      archive.addFile(ArchiveFile('catalog.db', catalog.length, catalog));
      final guide = utf8.encode(backup.restoreGuide);
      archive.addFile(
          ArchiveFile('RESTORE-راهنما.txt', guide.length, guide));
    }
    final out = File(p.join(Directory.systemTemp.path, name));
    await out.writeAsBytes(ZipEncoder().encode(archive));
    return out;
  }

  @override
  Future<File> exportBackup() async {
    final files = await searchFiles();
    final file = await _buildZip(files,
        name: backup.backupFilename(), withCatalog: true);
    _log('پشتیبان‌گیری', '${files.length} فایل');
    return file;
  }

  @override
  Future<File> exportPackage(List<int> ids) async {
    final files = _files.where((f) => ids.contains(f.id)).toList();
    final now = DateTime.now();
    final stamp = '${now.hour.toString().padLeft(2, '0')}'
        '${now.minute.toString().padLeft(2, '0')}'
        '${now.second.toString().padLeft(2, '0')}';
    final jalaliDate =
        backup.backupFilename(now).replaceFirst('darspack-backup-', '').replaceFirst('.zip', '');
    return _buildZip(files,
        name: 'darspack-package-$jalaliDate-$stamp.zip');
  }

  @override
  Future<VerifyReport> verifyPackage(File zip) =>
      manifest.verifyPackage(zip);

  @override
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
          results.add(ImportResult(
            status: 'error',
            messageFa: 'گم‌شده: ${entry['name']} ($arc)',
          ));
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
        results.add(await importFile(staged,
            displayName: entry['name'] as String?, meta: meta));
      }
      return results;
    } finally {
      try {
        await tmpDir.delete(recursive: true);
      } catch (_) {}
    }
  }

  List<T> _groupBy<T>(
    T Function(String label, List<LibraryFile> files, String detail) build,
    String Function(LibraryFile) key,
    bool Function(List<LibraryFile>) keep,
  ) {
    final map = <String, List<LibraryFile>>{};
    for (final f in _files) {
      map.putIfAbsent(key(f), () => []).add(f);
    }
    final out = <T>[];
    for (final e in map.entries) {
      if (e.value.length > 1 && keep(e.value)) {
        out.add(build(
          e.value.first.originalName,
          e.value,
          '${e.value.length} فایل',
        ));
      }
    }
    return out;
  }

  @override
  Future<List<DuplicateGroup>> duplicateGroups() async => _groupBy(
        (label, files, detail) =>
            DuplicateGroup(labelFa: label, files: files, detailFa: detail),
        (f) => f.sha256,
        (g) => g.isNotEmpty && g.first.sha256.isNotEmpty,
      );

  @override
  Future<List<VersionConflict>> versionConflicts() async => _groupBy(
        (label, files, detail) =>
            VersionConflict(labelFa: label, files: files, detailFa: detail),
        (f) => f.nameNorm,
        (g) => g.map((f) => f.sha256).toSet().length > 1,
      );

  @override
  Future<List<RenameHint>> renameHints() async => _groupBy(
        (label, files, detail) =>
            RenameHint(labelFa: label, files: files, detailFa: detail),
        (f) => f.sha256,
        (g) =>
            g.map((f) => f.nameNorm).toSet().length > 1 &&
            g.first.sha256.isNotEmpty,
      );

  @override
  Future<Map<String, dynamic>> stats() async {
    var total = 0;
    var unclassified = 0;
    var wasted = 0;
    for (final f in _files) {
      total += f.sizeBytes;
      if (f.subjectId == null) unclassified++;
    }
    for (final g in await duplicateGroups()) {
      wasted += (g.files.length - 1) * g.files.first.sizeBytes;
    }
    return {
      'totalFiles': _files.length,
      'totalSizeBytes': total,
      'unclassified': unclassified,
      'subjects': _subjects.length,
      'duplicates': (await duplicateGroups()).length,
      'wastedBytes': wasted,
      'trashCount': _trash.length,
      'skippedBytes': _savedBytes,
    };
  }

  @override
  Future<List<ActivityEntry>> activityLog({int limit = 100}) async =>
      _activity.take(limit).toList();
}

/// Real ImportResult has no copyWith; this tiny helper fills fileId.
extension on ImportResult {
  ImportResult copyWithFileId(int id) => ImportResult(
        status: status,
        messageFa: messageFa,
        fileId: id,
        existingId: existingId,
        prefill: prefill,
      );
}
