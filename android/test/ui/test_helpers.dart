// Shared helpers for UI widget tests: a seeded fake library +
// a ready AppState, pumped inside DarsPackApp.
//
// NOTE: the real SQLite Library cannot open under `flutter test` on
// this Linux VM (sqflite has no Linux-desktop engine), so tests use
// FakeLibrary (test/ui/fake_library.dart), an in-memory fake of the
// real Library API. The app itself uses the real Library.
//
// NOTE 2: a testWidgets body runs in the widget-test binding's fake
// async zone, so REAL async work (file IO, SharedPreferences) never
// completes there — it must run inside tester.runAsync(). All seeding
// below goes through runAsync; only pumping/tapping stays outside.
import 'dart:io';
import 'dart:ui';

import 'package:darspack/app_state.dart';
import 'package:darspack/main.dart';
import 'package:darspack/ui/sample_data.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'fake_library.dart';

/// Builds a fresh seeded AppState (8 sample files, fa, welcome shown).
/// Call only inside tester.runAsync (see seededStateIn) — never
/// directly in a testWidgets body.
Future<AppState> seededState({bool extras = false}) async {
  SharedPreferences.setMockInitialValues({
    'language': 'fa',
    'welcomeShown': true,
  });
  final prefs = await SharedPreferences.getInstance();
  final root = await Directory.systemTemp.createTemp('darspack_test_lib_');
  final library = FakeLibrary(root);
  await seedSampleLibrary(library, extras: extras);
  final state = AppState(library: library, prefs: prefs);
  await state.init();
  return state;
}

/// Seeded state, built inside runAsync so its real IO completes.
Future<AppState> seededStateIn(WidgetTester tester,
    {bool extras = false}) async {
  late final AppState state;
  await tester.runAsync(() async {
    state = await seededState(extras: extras);
  });
  return state;
}

/// Tall phone-like surface so all 8 seeded list tiles are built by
/// the ListView (at the default 800x600 only ~5 fit and the rest are
/// never built, so find.text on them fails).
void _tallSurface(WidgetTester tester) {
  tester.view.physicalSize = const Size(800, 1400);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.reset);
}

/// Pumps the whole app with a seeded state and settles.
Future<void> pumpSeededApp(
  WidgetTester tester, {
  bool extras = false,
}) async {
  _tallSurface(tester);
  final state = await seededStateIn(tester, extras: extras);
  await tester.pumpWidget(DarsPackApp(state: state));
  await tester.pumpAndSettle();
}

/// Pumps the whole app with an already-built state.
Future<void> pumpAppWithState(WidgetTester tester, AppState state) async {
  _tallSurface(tester);
  await tester.pumpWidget(DarsPackApp(state: state));
  await tester.pumpAndSettle();
}
