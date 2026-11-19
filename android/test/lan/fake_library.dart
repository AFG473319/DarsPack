// In-memory fake of the data-layer Library, for LAN tests only.
//
// Implements the task's Library contract with plain Dart: files live
// under [dir]/files/<id:06d><ext>, subjects are seeded by the test.
// Import mirrors the Windows rules that the server relies on: SHA-256
// duplicate check (duplicate = reported + skipped), kind/lesson from
// meta are stored, subject is NEVER stored (it comes back as prefill),
// the file lands unclassified.
import 'dart:io';

import 'package:crypto/crypto.dart';
import 'package:darspack/core/library.dart';
import 'package:darspack/core/models.dart';
import 'package:darspack/lan/lan_utils.dart';

class FakeLibrary extends Library {
  final Directory dir;
  final List<LibraryFile> _files = [];
  final List<Subject> _subjects = [];
  int _nextId = 1;

  FakeLibrary(this.dir);

  /// Seed a subject. Returns its id.
  int addSubject(String name) {
    final id = _subjects.length + 1;
    _subjects.add(Subject(
      id: id,
      name: name,
      normalized: latinDigits(name),
    ));
    return id;
  }

  /// Seed a file with real bytes on disk. Returns the LibraryFile.
  Future<LibraryFile> addFile(
    String originalName,
    List<int> bytes, {
    int? subjectId,
    int? chapter,
    int? lesson,
    String? kind,
    bool available = true,
  }) async {
    final id = _nextId++;
    final ext = _extension(originalName);
    final storedName =
        '${id.toString().padLeft(6, '0')}$ext';
    final filesDir = Directory('${dir.path}/files');
    await filesDir.create(recursive: true);
    final stored = File('${filesDir.path}/$storedName');
    await stored.writeAsBytes(bytes);
    final subject = subjectId == null
        ? null
        : _subjects.firstWhere((s) => s.id == subjectId);
    final file = LibraryFile(
      id: id,
      storedName: storedName,
      originalName: originalName,
      nameNorm: latinDigits(originalName),
      sizeBytes: bytes.length,
      sha256: sha256.convert(bytes).toString(),
      importedAt: DateTime.now(),
      subjectId: subjectId,
      subjectName: subject?.name,
      chapter: chapter,
      lesson: lesson,
      kind: kind,
      available: available,
    );
    _files.add(file);
    return file;
  }

  static String _extension(String name) {
    final dot = name.lastIndexOf('.');
    return dot >= 0 ? name.substring(dot) : '';
  }

  @override
  Future<LibraryFile?> getFile(int id) async {
    for (final f in _files) {
      if (f.id == id) return f;
    }
    return null;
  }

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
    final q = latinDigits(query).trim();
    if (q.isNotEmpty) {
      final tokens = q.split(RegExp(r'\s+'));
      out = out.where((f) {
        final haystack =
            '${latinDigits(f.originalName)} ${f.subjectName ?? ''} ${f.kind ?? ''}';
        return tokens.every((t) => haystack.contains(t));
      }).toList();
    }
    if (subjectId != null) {
      out = out.where((f) => f.subjectId == subjectId).toList();
    }
    if (unclassifiedOnly) {
      out = out.where((f) => f.subjectId == null).toList();
    }
    if (kind != null) {
      out = out.where((f) => f.kind == kind).toList();
    }
    if (out.length > limit) {
      out = out.sublist(0, limit);
    }
    return out;
  }

  @override
  Future<List<Subject>> subjectsWithCounts() async => _subjects
      .map((s) => Subject(
            id: s.id,
            name: s.name,
            normalized: s.normalized,
            fileCount:
                _files.where((f) => f.subjectId == s.id).length,
          ))
      .toList();

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
    final bytes = await src.readAsBytes();
    final hash = sha256.convert(bytes).toString();
    final shownName = displayName ?? src.uri.pathSegments.last;
    final subjectHint = meta?['subject'] as String?;
    final prefill = subjectHint == null
        ? null
        : <String, dynamic>{'subject': subjectHint};
    for (final existing in _files) {
      if (existing.sha256 == hash && !keepDuplicate) {
        return ImportResult(
          status: 'duplicate',
          messageFa: '«$shownName» تکرارِ «${existing.originalName}» است',
          existingId: existing.id,
          prefill: prefill,
        );
      }
    }
    final id = _nextId++;
    final ext = _extension(shownName);
    final storedName = '${id.toString().padLeft(6, '0')}$ext';
    final filesDir = Directory('${dir.path}/files');
    await filesDir.create(recursive: true);
    await src.copy('${filesDir.path}/$storedName');
    final file = LibraryFile(
      id: id,
      storedName: storedName,
      originalName: shownName,
      nameNorm: latinDigits(shownName),
      sizeBytes: bytes.length,
      sha256: hash,
      importedAt: DateTime.now(),
      subjectId: null, // NEVER auto-applied — lands unclassified
      chapter: null,
      lesson: (meta?['lesson'] as num?)?.toInt(),
      kind: meta?['kind'] as String?,
    );
    _files.add(file);
    return ImportResult(
      status: 'imported',
      messageFa: '«$shownName» وارد شد',
      fileId: id,
      prefill: prefill,
    );
  }

  @override
  File storedFileFor(LibraryFile file) =>
      File('${dir.path}/files/${file.storedName}');
}
