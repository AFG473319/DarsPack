// Smoke test: the app boots to the library screen.
import 'package:flutter_test/flutter_test.dart';

import 'ui/test_helpers.dart';

void main() {
  testWidgets('app boots to the library screen', (tester) async {
    await pumpSeededApp(tester);
    expect(find.text('درس‌پک'), findsWidgets);
    expect(find.text('جزوه ریاضی فصل ۳ نهم.pdf'), findsOneWidget);
  });
}
