// Data models for the library (مدل‌های داده).
//
// Plain value classes shared by the data layer, the UI and the LAN
// server. Field names follow the task contract exactly.

import 'normalize.dart';

/// One catalogued file.
class LibraryFile {
  const LibraryFile({
    required this.id,
    required this.storedName,
    required this.originalName,
    required this.nameNorm,
    required this.sizeBytes,
    required this.sha256,
    required this.importedAt,
    this.subjectId,
    this.subjectName,
    this.chapter,
    this.lesson,
    this.schoolYear,
    this.kind,
    this.note = '',
    this.available = true,
    this.tags = const [],
  });

  final int id;

  /// Real name in files/, e.g. `000123.pdf`.
  final String storedName;

  /// Name as imported, never altered.
  final String originalName;

  /// Match key of [originalName].
  final String nameNorm;
  final int sizeBytes;
  final String sha256;

  /// Import time, stored in the catalog as an ISO-8601 string.
  final DateTime importedAt;
  final int? subjectId;
  final String? subjectName;
  final int? chapter;
  final int? lesson;
  final String? schoolYear;
  final String? kind;
  final String note;
  final bool available;
  final List<String> tags;

  /// Build from a catalog row (plain `files` row or a search row joined
  /// with `subjects`, which adds `subject_name`). [tags] are attached by
  /// the caller when available.
  factory LibraryFile.fromRow(Map<String, Object?> row, {List<String>? tags}) {
    return LibraryFile(
      id: row['id'] as int,
      storedName: (row['stored_name'] as String?) ?? '',
      originalName: row['original_name'] as String,
      nameNorm:
          (row['name_norm'] as String?) ??
          matchKey(row['original_name'] as String),
      sizeBytes: (row['size_bytes'] as int?) ?? 0,
      sha256: (row['sha256'] as String?) ?? '',
      importedAt:
          DateTime.tryParse((row['imported_at'] as String?) ?? '') ??
          DateTime.fromMillisecondsSinceEpoch(0),
      subjectId: row['subject_id'] as int?,
      subjectName: row['subject_name'] as String?,
      chapter: row['chapter'] as int?,
      lesson: row['lesson'] as int?,
      schoolYear: row['school_year'] as String?,
      kind: row['kind'] as String?,
      note: (row['note'] as String?) ?? '',
      available: ((row['available'] as int?) ?? 1) == 1,
      tags: tags ?? const [],
    );
  }

  @override
  String toString() => 'LibraryFile($id, $originalName)';
}

/// A subject (درس) with its file count.
class Subject {
  const Subject({
    required this.id,
    required this.name,
    required this.normalized,
    this.fileCount = 0,
  });

  final int id;
  final String name;
  final String normalized;
  final int fileCount;

  factory Subject.fromRow(Map<String, Object?> row) {
    return Subject(
      id: row['id'] as int,
      name: row['name'] as String,
      normalized:
          (row['normalized'] as String?) ?? matchKey(row['name'] as String),
      fileCount: (row['file_count'] as int?) ?? 0,
    );
  }
}

/// The result of importing one file.
class ImportResult {
  const ImportResult({
    required this.status,
    required this.messageFa,
    this.fileId,
    this.existingId,
    this.prefill,
  });

  /// 'imported' | 'duplicate' | 'error'.
  final String status;

  /// Persian message for the user.
  final String messageFa;

  /// Catalog id of the newly imported file (when [status] == 'imported').
  final int? fileId;

  /// Catalog id of the existing twin (when [status] == 'duplicate').
  final int? existingId;

  /// Pre-fill metadata carried back from a package manifest
  /// (`{'subject': String?, 'tags': List<String>}`).
  /// The importer NEVER stores these — pre-fill only.
  final Map<String, dynamic>? prefill;

  bool get isImported => status == 'imported';
  bool get isDuplicate => status == 'duplicate';
  bool get isError => status == 'error';
}

/// One file in files/.trash/, with its sidecar metadata.
class TrashEntry {
  const TrashEntry({
    required this.trashName,
    required this.originalName,
    required this.storedName,
    required this.subjectName,
    required this.size,
    required this.deletedAt,
    required this.kind,
    this.tags = const [],
  });

  /// Name of the file inside .trash/ (used to restore it).
  final String trashName;
  final String originalName;
  final String storedName;
  final String subjectName;
  final int size;
  final String deletedAt;
  final String kind;
  final List<String> tags;
}

/// R1 — exact duplicates: same SHA-256, more than one row.
/// Flag-only: nothing here ever deletes.
class DuplicateGroup {
  const DuplicateGroup({
    required this.labelFa,
    required this.files,
    required this.detailFa,
  });

  final String labelFa;
  final List<LibraryFile> files;
  final String detailFa;
}

/// R2 — version conflicts: same normalized name, different content.
class VersionConflict {
  const VersionConflict({
    required this.labelFa,
    required this.files,
    required this.detailFa,
  });

  final String labelFa;
  final List<LibraryFile> files;
  final String detailFa;
}

/// R3 — rename hints: same content saved under different names.
class RenameHint {
  const RenameHint({
    required this.labelFa,
    required this.files,
    required this.detailFa,
  });

  final String labelFa;
  final List<LibraryFile> files;
  final String detailFa;
}

/// One row of the user-activity log.
class ActivityEntry {
  const ActivityEntry({
    required this.id,
    required this.ts,
    required this.action,
    this.detail = '',
  });

  final int id;
  final String ts;
  final String action;
  final String detail;

  factory ActivityEntry.fromRow(Map<String, Object?> row) {
    return ActivityEntry(
      id: row['id'] as int,
      ts: row['ts'] as String,
      action: row['action'] as String,
      detail: (row['detail'] as String?) ?? '',
    );
  }
}

/// The result of verifying a درس‌پک package against its manifest.
class VerifyReport {
  const VerifyReport({required this.ok, this.problems = const []});

  final bool ok;

  /// Persian problem messages (empty when [ok]).
  final List<String> problems;
}
