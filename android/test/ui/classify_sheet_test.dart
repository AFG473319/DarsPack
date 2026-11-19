// Widget tests: the classify sheet pre-fills suggestions from the
// filename (subject as a suggested choice only — never pre-applied),
// and saving stores the chosen subject.
import 'dart:io';

import 'package:darspack/app_state.dart';
import 'package:darspack/core/core.dart';
import 'package:darspack/ui/classify_sheet.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'test_helpers.dart';

void main() {
  testWidgets('classify sheet shows suggestions from the filename',
      (tester) async {
    final state = await seededStateIn(tester);
    await pumpAppWithState(tester, state);

    // Import a fresh file whose name suggests ریاضی / فصل ۷ / جزوه.
    // (Library IO lives in runAsync — see test_helpers.dart.)
    late final ImportResult res;
    late final LibraryFile? file;
    await tester.runAsync(() async {
      final src = await _tempFile('جزوه ریاضی فصل ۷.pdf', 'new content 7');
      res = await state.library.importFile(src);
      file = await state.library.getFile(res.fileId!);
    });
    expect(res.isImported, isTrue);
    expect(file, isNotNull);
    final imported = file!;
    // The file itself is still unclassified (subject never auto-applied).
    expect(imported.subjectId, isNull);
    expect(imported.chapter, 7); // chapter/lesson/kind hints ARE applied
    expect(imported.kind, 'جزوه');
    // And the suggestion for the sheet says ریاضی.
    expect(suggest('جزوه ریاضی فصل ۷').subject, 'ریاضی');

    await tester.pumpWidget(
      _SheetHarness(state: state, files: [imported]),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.text('open'));
    await tester.pumpAndSettle();

    expect(find.text('تکمیل اطلاعات فایل‌های تازه'), findsOneWidget);
    // Suggested subject is offered as the selected dropdown value.
    expect(find.text('ریاضی'), findsWidgets);
  });

  testWidgets('saving the classify sheet stores the subject',
      (tester) async {
    final state = await seededStateIn(tester);
    await pumpAppWithState(tester, state);

    late final ImportResult res;
    late final LibraryFile? file;
    await tester.runAsync(() async {
      final src = await _tempFile(
          'نمونه سوال عربی نهم فصل ۲.pdf', 'arabic exam');
      res = await state.library.importFile(src);
      file = await state.library.getFile(res.fileId!);
    });

    await tester.pumpWidget(
      _SheetHarness(state: state, files: [file!]),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.text('open'));
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const ValueKey('classify_save')));
    await tester.pumpAndSettle();

    late final LibraryFile? saved;
    await tester.runAsync(() async {
      saved = await state.library.getFile(res.fileId!);
    });
    expect(saved?.subjectName, 'عربی');
    expect(saved?.chapter, 2);
    expect(saved?.kind, 'نمونه‌سوال');
  });

  testWidgets('suggest() never applies a subject on its own',
      (tester) async {
    final state = await seededStateIn(tester);
    late final ImportResult res;
    late final LibraryFile? file;
    await tester.runAsync(() async {
      final src = await _tempFile('جزوه فیزیک فصل ۱.pdf', 'physics?');
      res = await state.library.importFile(src);
      file = await state.library.getFile(res.fileId!);
    });
    // «فیزیک» is not a default subject; no subject suggested or stored.
    expect(suggest('جزوه فیزیک فصل ۱').subject, isNull);
    expect(file?.subjectId, isNull);
  });
}

Future<File> _tempFile(String name, String content) async {
  final dir = await Directory.systemTemp.createTemp('darspack_classify_');
  final f = File('${dir.path}/$name');
  await f.writeAsString(content);
  return f;
}

class _SheetHarness extends StatelessWidget {
  final AppState state;
  final List<LibraryFile> files;
  const _SheetHarness({required this.state, required this.files});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      home: Scaffold(
        body: Builder(
          builder: (ctx) => Center(
            child: ElevatedButton(
              onPressed: () => showClassifySheet(ctx, state, files),
              child: const Text('open'),
            ),
          ),
        ),
      ),
    );
  }
}
