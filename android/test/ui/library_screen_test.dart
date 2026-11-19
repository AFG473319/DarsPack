// Widget tests: the library screen renders seeded files, the subject
// chips filter, search filters, and long-press multi-select works.
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'test_helpers.dart';

void main() {
  testWidgets('library list renders the 8 seeded files',
      (tester) async {
    await pumpSeededApp(tester);

    expect(find.text('جزوه ریاضی فصل ۳ نهم.pdf'), findsOneWidget);
    expect(find.text('کاربرگ علوم تجربی درس ۵.pdf'), findsOneWidget);
    expect(find.text('فایل بدون درس برای تست.pdf'), findsOneWidget);
    // Kind badges show.
    expect(find.text('نمونه‌سوال'), findsWidgets);
    expect(find.text('جزوه'), findsWidgets);
    // Unclassified chip shows the count (۱).
    expect(find.textContaining('بدون درس'), findsWidgets);
  });

  testWidgets('search filters to matching files', (tester) async {
    await pumpSeededApp(tester);

    await tester.enterText(
        find.byKey(const ValueKey('search_field')), 'ریاضی');
    await tester.pumpAndSettle();

    expect(find.text('جزوه ریاضی فصل ۳ نهم.pdf'), findsOneWidget);
    expect(find.text('نمونه سوال ریاضی نهم فصل ۳.pdf'), findsOneWidget);
    expect(find.text('عکس تخته تدریس ریاضی فصل ۵.png'), findsOneWidget);
    expect(find.text('کاربرگ علوم تجربی درس ۵.pdf'), findsNothing);
    expect(find.text('تکلیف زبان انگلیسی درس ۳.pdf'), findsNothing);
  });

  testWidgets('search with a فصل phrase matches the chapter column',
      (tester) async {
    await pumpSeededApp(tester);

    await tester.enterText(
        find.byKey(const ValueKey('search_field')), 'فصل ۳');
    await tester.pumpAndSettle();

    expect(find.text('جزوه ریاضی فصل ۳ نهم.pdf'), findsOneWidget);
    expect(find.text('نمونه سوال ریاضی نهم فصل ۳.pdf'), findsOneWidget);
    expect(find.text('عکس تخته تدریس ریاضی فصل ۵.png'), findsNothing);
  });

  testWidgets('subject chip filters the list', (tester) async {
    await pumpSeededApp(tester);

    // The فارسی chip (id 3 in the default subject order, 1 file).
    // Chips overflow horizontally (RTL): scroll it into view first,
    // otherwise the tap lands off-screen and the test passes vacuously.
    await tester.ensureVisible(find.byKey(const ValueKey('chip_subject_3')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('chip_subject_3')));
    await tester.pumpAndSettle();

    expect(find.text('جزوه فارسی درس ۲ هشتم.pdf'), findsOneWidget);
    expect(find.text('جزوه ریاضی فصل ۳ نهم.pdf'), findsNothing);
  });

  testWidgets('unclassified chip shows only the file without a subject',
      (tester) async {
    await pumpSeededApp(tester);

    await tester.tap(find.byKey(const ValueKey('chip_unclassified')));
    await tester.pumpAndSettle();

    expect(find.text('فایل بدون درس برای تست.pdf'), findsOneWidget);
    expect(find.text('جزوه ریاضی فصل ۳ نهم.pdf'), findsNothing);
  });

  testWidgets('long-press starts multi-select with delete action',
      (tester) async {
    await pumpSeededApp(tester);

    await tester.longPress(find.text('جزوه ریاضی فصل ۳ نهم.pdf'));
    await tester.pumpAndSettle();

    expect(find.byKey(const ValueKey('action_delete')), findsOneWidget);
    expect(find.byKey(const ValueKey('action_edit')), findsOneWidget);
    // Selection count shows in the app bar.
    expect(find.text('۱'), findsOneWidget);
  });

  testWidgets('empty search shows the empty state', (tester) async {
    await pumpSeededApp(tester);

    await tester.enterText(
        find.byKey(const ValueKey('search_field')), 'چیزی که نیست');
    await tester.pumpAndSettle();

    expect(find.textContaining('چیزی پیدا نشد'), findsOneWidget);
  });
}
