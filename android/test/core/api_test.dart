// Compile-time contract check: the Library API the UI and LAN agents
// code against exists with the exact names and signatures from the
// task. This runs without a database (no sqflite calls are made).
import 'package:darspack/core/library.dart';
import 'package:darspack/core/models.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('Library API exists with the contracted signatures', () {
    // Static open + default constructor (test fakes subclass Library).
    final openFn = Library.open;
    expect(openFn, isNotNull);
    final unopened = Library();
    expect(unopened, isA<Library>());

    // Instance members, referenced as tear-offs (never called).
    // (filesDir / rootPath getters need an opened library, so they are
    // not touched here.)
    expect(unopened.close, isNotNull);
    expect(unopened.searchFiles, isNotNull);
    expect(unopened.subjectsWithCounts, isNotNull);
    expect(unopened.unclassifiedCount, isNotNull);
    expect(unopened.importFile, isNotNull);
    expect(unopened.importFiles, isNotNull);
    expect(unopened.getFile, isNotNull);
    expect(unopened.updateFileMeta, isNotNull);
    expect(unopened.deleteFile, isNotNull);
    expect(unopened.listTrash, isNotNull);
    expect(unopened.restoreTrash, isNotNull);
    expect(unopened.emptyTrash, isNotNull);
    expect(unopened.exportBackup, isNotNull);
    expect(unopened.exportPackage, isNotNull);
    expect(unopened.verifyPackage, isNotNull);
    expect(unopened.importPackage, isNotNull);
    expect(unopened.duplicateGroups, isNotNull);
    expect(unopened.versionConflicts, isNotNull);
    expect(unopened.renameHints, isNotNull);
    expect(unopened.stats, isNotNull);
    expect(unopened.activityLog, isNotNull);
    expect(unopened.logActivity, isNotNull);
    expect(unopened.storedFileFor, isNotNull);
    expect(unopened.loadHints, isNotNull);
    expect(unopened.learnHint, isNotNull);
  });

  test('models carry the contracted fields', () {
    final file = LibraryFile(
      id: 1,
      storedName: '000001.pdf',
      originalName: 'جزوه ریاضی.pdf',
      nameNorm: 'جزوه ریاضی.pdf',
      sizeBytes: 123,
      sha256: 'abc',
      importedAt: DateTime(2026, 11, 19),
      subjectId: 2,
      subjectName: 'ریاضی',
      chapter: 3,
      lesson: null,
      schoolYear: '1405-1406',
      kind: 'جزوه',
      note: '',
      available: true,
      tags: ['امتحان'],
    );
    expect(file.id, 1);
    expect(file.importedAt.year, 2026);

    const subject = Subject(
      id: 2,
      name: 'ریاضی',
      normalized: 'ریاضی',
      fileCount: 1,
    );
    expect(subject.fileCount, 1);

    const result = ImportResult(
      status: 'imported',
      messageFa: 'وارد شد',
      fileId: 1,
      prefill: {
        'subject': 'ریاضی',
        'tags': ['امتحان'],
      },
    );
    expect(result.isImported, isTrue);

    const trash = TrashEntry(
      trashName: '000001.pdf',
      originalName: 'جزوه ریاضی.pdf',
      storedName: '000001.pdf',
      subjectName: 'ریاضی',
      size: 123,
      deletedAt: '2026-11-19T09:00:00',
      kind: 'جزوه',
      tags: ['امتحان'],
    );
    expect(trash.trashName, '000001.pdf');

    const report = VerifyReport(ok: false, problems: ['خراب']);
    expect(report.ok, isFalse);
  });
}
