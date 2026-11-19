// Screenshot harness — Flutter mirror of the Windows
// scripts/capture_all_pages.py.
//
// Seeds a temp library with the same 8 sample files as the Windows
// sandbox (same names/subjects/chapters/kinds/notes) plus duplicate
// groups, two trash entries, activity rows and hint rules, then walks
// EVERY screen and dialog with real taps, calling pumpAndSettle BEFORE
// every capture, and saves one numbered PNG per capture via
// binding.takeScreenshot.
//
// Run from the project root:
//   flutter test integration_test/screenshots_test.dart
// PNGs land in integration_test/screenshots/ (see README.md).
// The test also asserts every screenshot is non-blank (file size above
// a threshold and more than one distinct colour), so a blank render
// fails loudly.
//
// flutter-tester fallback: under plain `flutter test` with no device
// (e.g. `flutter test -d flutter-tester ...` on a dev VM) the
// captureScreenshot channel has no implementation, so
// binding.takeScreenshot throws MissingPluginException. shot() then
// captures the same pixels from a RepaintBoundary wrapped around the
// app instead, so the walk and the non-blank assertions still run.
// On a real device/emulator the takeScreenshot path is used.
import 'dart:io';
import 'dart:ui' as ui;

import 'package:darspack/main.dart';
import 'package:file_picker/file_picker.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:path/path.dart' as p;

import '../test/ui/test_helpers.dart';

// RepaintBoundary around the whole app (see the header note): the
// flutter-tester screenshot fallback captures from this boundary.
final _shotKey = GlobalKey();

// Fake OS file picker: every pick returns the same pre-made files.
// (file_picker's Linux implementation talks D-Bus directly, so a
// method-channel mock never intercepts it; replacing the platform
// object works on every platform, device or tester.)
class _FakePicker extends FilePicker {
  final List<PlatformFile> files;
  _FakePicker(this.files);

  @override
  Future<FilePickerResult?> pickFiles({
    String? dialogTitle,
    String? initialDirectory,
    FileType type = FileType.any,
    List<String>? allowedExtensions,
    Function(FilePickerStatus)? onFileLoading,
    bool allowCompression = false,
    int compressionQuality = 0,
    bool allowMultiple = false,
    bool withData = false,
    bool withReadStream = false,
    bool lockParentWindow = false,
    bool readSequential = false,
  }) async =>
      FilePickerResult(files);
}

void main() {
  final binding = IntegrationTestWidgetsFlutterBinding.ensureInitialized();

  testWidgets('capture every screen',
      (tester) async {
    // --- fake the OS file picker: the "user" picks two fresh files ---
    // Real IO lives in runAsync (testWidgets fakes async otherwise).
    late final List<PlatformFile> picked;
    await tester.runAsync(() async {
      final pickDir =
          await Directory.systemTemp.createTemp('darspack_shots_');
      final pick1 = File(p.join(pickDir.path, 'جزوه ریاضی فصل ۷ نهم.pdf'));
      await pick1.writeAsString('shot import one');
      final pick2 = File(p.join(pickDir.path, 'نمونه سوال علوم فصل ۲.pdf'));
      await pick2.writeAsString('shot import two');
      picked = [
        PlatformFile(
            name: p.basename(pick1.path),
            path: pick1.path,
            size: await pick1.length()),
        PlatformFile(
            name: p.basename(pick2.path),
            path: pick2.path,
            size: await pick2.length()),
      ];
    });
    final realPicker = FilePicker.platform;
    FilePicker.platform = _FakePicker(picked);
    addTearDown(() {
      FilePicker.platform = realPicker;
    });

    final state = await seededStateIn(tester, extras: true);
    // Tall phone-like surface so all 10 list tiles (8 seeded + 2
    // imported) are built by the ListView (at the default 800x600 the
    // oldest tiles never build and the long-press steps can't find them).
    tester.view.physicalSize = const Size(800, 1400);
    tester.view.devicePixelRatio = 1.0;
    await tester.pumpWidget(
        RepaintBoundary(key: _shotKey, child: DarsPackApp(state: state)));
    await tester.pumpAndSettle();

    final shots = <String, List<int>>{};
    final outDir = Directory(
        p.join(Directory.current.path, 'integration_test', 'screenshots'));
    await tester.runAsync(() async {
      await outDir.create(recursive: true);
    });

    Future<void> shot(String name) async {
      await tester.pumpAndSettle();
      List<int> bytes;
      try {
        bytes = await binding.takeScreenshot(name);
      } on MissingPluginException {
        // No device: capture the app boundary instead (see header).
        final fallback = await tester.runAsync<List<int>>(() async {
          final boundary = _shotKey.currentContext!.findRenderObject()
              as RenderRepaintBoundary;
          final image = await boundary.toImage(pixelRatio: 1.0);
          final data =
              await image.toByteData(format: ui.ImageByteFormat.png);
          return data!.buffer.asUint8List();
        });
        bytes = fallback!;
      }
      shots[name] = bytes;
      await tester.runAsync(() async {
        await File(p.join(outDir.path, name)).writeAsBytes(bytes);
      });
    }

    Future<void> openDrawerItem(String key) async {
      final menu = find.byTooltip('Open navigation menu');
      if (menu.evaluate().isNotEmpty) {
        await tester.tap(menu);
      } else {
        await tester.tap(find.byIcon(Icons.menu));
      }
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(ValueKey(key)));
      await tester.pumpAndSettle();
    }

    Future<void> back() async {
      await tester.pageBack();
      await tester.pumpAndSettle();
    }

    Future<void> tapTab(int index) async {
      await tester.tap(find.byType(Tab).at(index));
      await tester.pumpAndSettle();
    }

    // 01 — library home.
    await shot('01_library.png');

    // 02 — search «ریاضی».
    await tester.enterText(
        find.byKey(const ValueKey('search_field')), 'ریاضی');
    await shot('02_search.png');
    await tester.tap(find.byIcon(Icons.clear));
    await tester.pumpAndSettle();

    // 03 — import screen; 04 — classify sheet (real import, real taps).
    await tester.tap(find.byKey(const ValueKey('fab_import')));
    await tester.pumpAndSettle();
    await shot('03_import.png');
    await tester.tap(find.byKey(const ValueKey('import_pick')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('import_classify')));
    await tester.pumpAndSettle();
    await shot('04_classify.png');
    await tester.tap(find.byKey(const ValueKey('classify_save')));
    await tester.pumpAndSettle(); // back on the library

    // 05 — file detail / edit sheet (long-press → edit, single file).
    // NOTE: the seeded extras include an exact duplicate AND a version
    // conflict of this same filename, so find.text would match 3 tiles.
    // file_1 is the original (first seeded file); the copies have later
    // ids, so the key finder is unambiguous.
    await tester.longPress(find.byKey(const ValueKey('file_1')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('action_edit')));
    await tester.pumpAndSettle();
    await shot('05_detail.png');
    await tester.tap(find.byKey(const ValueKey('detail_save')));
    await tester.pumpAndSettle();

    // 06 — bulk edit (long-press one file, tap a second, edit).
    await tester.longPress(find.byKey(const ValueKey('file_1')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('نمونه سوال ریاضی نهم فصل ۳.pdf'));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('action_edit')));
    await tester.pumpAndSettle();
    await shot('06_bulk_edit.png');
    await tester.tap(find.byKey(const ValueKey('bulk_save')));
    await tester.pumpAndSettle();

    // 07 — stats.
    await openDrawerItem('nav_stats');
    await shot('07_stats.png');
    await back();

    // 08/09 — activity: history tab, then learned-rules tab.
    await openDrawerItem('nav_history');
    await shot('08_activity_history.png');
    await tapTab(1);
    await shot('09_activity_hints.png');
    await back();

    // 10/11/12 — duplicates: exact, conflicts, rename hints.
    await openDrawerItem('nav_duplicates');
    await shot('10_duplicates_exact.png');
    await tapTab(1);
    await shot('11_duplicates_conflicts.png');
    await tapTab(2);
    await shot('12_duplicates_renames.png');
    await back();

    // 13 — share (PIN + QR): start the stub server, then stop it.
    await openDrawerItem('nav_share');
    await tester.tap(find.byKey(const ValueKey('share_toggle')));
    await tester.pumpAndSettle();
    await shot('13_share.png');
    await tester.tap(find.byKey(const ValueKey('share_toggle')));
    await tester.pumpAndSettle();
    await back();

    // 14 — settings.
    await openDrawerItem('nav_settings');
    await shot('14_settings.png');
    await back();

    // 15 — backup & restore (tap "create backup" first).
    await openDrawerItem('nav_backup');
    await tester.tap(find.byKey(const ValueKey('backup_create')));
    await tester.pumpAndSettle();
    await shot('15_backup.png');
    await back();

    // 16/17 — packages, then verify the just-exported package.
    await openDrawerItem('nav_packages');
    await shot('16_packages.png');
    await tester.tap(find.byKey(const ValueKey('pkg_export')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('pkg_verify_last')));
    await tester.pumpAndSettle();
    await shot('17_verify.png');
    await back();

    // 18 — trash.
    await openDrawerItem('nav_trash');
    await shot('18_trash.png');
    await back();

    // 19 — exam pack.
    await openDrawerItem('nav_exam_pack');
    await shot('19_exam_pack.png');
    await back();

    // 20/21/22 — welcome slides.
    await openDrawerItem('nav_welcome');
    await shot('20_welcome_1.png');
    await tester.tap(find.byKey(const ValueKey('welcome_next')));
    await tester.pumpAndSettle();
    await shot('21_welcome_2.png');
    await tester.tap(find.byKey(const ValueKey('welcome_next')));
    await tester.pumpAndSettle();
    await shot('22_welcome_3.png');
    await tester.tap(find.byKey(const ValueKey('welcome_start')));
    await tester.pumpAndSettle();

    // 23/24/25 — help tabs: quick, phone, FAQ.
    await openDrawerItem('nav_help');
    await shot('23_help_quick.png');
    await tapTab(1);
    await shot('24_help_phone.png');
    await tapTab(2);
    await shot('25_help_faq.png');
    await back();

    // 26 — LAN client (form + connect attempt; the real client is the
    // LAN agent's — the stub reports the missing wiring honestly).
    await openDrawerItem('nav_lan_client');
    await tester.enterText(
        find.byKey(const ValueKey('lan_address')), 'http://192.168.1.5:8765');
    await tester.enterText(find.byKey(const ValueKey('lan_pin')), '123456');
    await tester.tap(find.byKey(const ValueKey('lan_connect')));
    await tester.pumpAndSettle();
    await shot('26_lan_client.png');

    // --- every screenshot must be non-blank ---
    expect(shots.length, 26);
    await tester.runAsync(() async {
    for (final e in shots.entries) {
      expect(e.value.length, greaterThan(8000),
          reason: '${e.key} is suspiciously small (blank?)');
      // Painting's decodeImageFromList (1 arg); dart:ui's needs 2.
      final image = await decodeImageFromList(
          Uint8List.fromList(e.value));
      final byteData = await image.toByteData(
          format: ui.ImageByteFormat.rawRgba);
      final pixels = byteData!.buffer.asUint32List();
      final colors = <int>{};
      for (var i = 0; i < pixels.length; i += 997) {
        colors.add(pixels[i]);
        if (colors.length > 2) break;
      }
      expect(colors.length, greaterThan(1),
          reason: '${e.key} is a single solid colour (blank?)');
    }
    });
  }, timeout: const Timeout(Duration(minutes: 10)));
}
