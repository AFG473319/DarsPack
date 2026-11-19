# Screenshot harness

Flutter mirror of the Windows `scripts/capture_all_pages.py`.

## Run

From the project root (`~/workspace/darspack-android/`), one command:

```sh
flutter test integration_test/screenshots_test.dart
```

That is the canonical command: it runs the walk on a connected
Android device or emulator, where `binding.takeScreenshot` captures
real device pixels. On a dev VM with **no Android device**, use the
flutter-tester explicitly:

```sh
flutter test -d flutter-tester integration_test/screenshots_test.dart
```

(Plain `flutter test integration_test/...` with no device refuses:
the only device this VM sees is Linux desktop, which this
Android-only project does not support.)

## What it does

1. Seeds a temp library with the same 8 sample files as the
   Windows sandbox (`scripts/app_harness.py`: جزوه ریاضی فصل ۳ نهم.pdf،
   نمونه سوال ریاضی نهم فصل ۳.pdf، کاربرگ علوم تجربی درس ۵.pdf،
   جزوه فارسی درس ۲ هشتم.pdf، نمونه سوال علوم نهم فصل ۴.pdf،
   تکلیف زبان انگلیسی درس ۳.pdf، عکس تخته تدریس ریاضی فصل ۵.png،
   فایل بدون درس برای تست.pdf — same subjects/chapters/kinds/notes),
   plus an exact duplicate, a rename hint, a version conflict, two
   trash entries, activity rows and two hint rules, so the duplicates /
   trash / activity screens have real content. Tests run against
   `FakeLibrary` (see `test/ui/fake_library.dart`): sqflite has no
   Linux-desktop engine, so the real SQLite library cannot open under
   `flutter test` on this VM.
2. Walks every screen and dialog with real taps (never by pumping a
   bare widget), calling `pumpAndSettle` BEFORE every capture:
   `01_library`, `02_search` («ریاضی»), `03_import`, `04_classify`,
   `05_detail`, `06_bulk_edit`, `07_stats`, `08_activity_history`,
   `09_activity_hints`, `10_duplicates_exact`,
   `11_duplicates_conflicts`, `12_duplicates_renames`, `13_share`
   (PIN + QR), `14_settings`, `15_backup`, `16_packages`,
   `17_verify`, `18_trash`, `19_exam_pack`, `20–22_welcome` (3 slides),
   `23–25_help` (quick / phone / FAQ), `26_lan_client`.
   The OS file picker is faked by replacing `FilePicker.platform`
   with a small `_FakePicker` that returns two pre-made files — a
   method-channel mock does NOT work here: file_picker's Linux
   implementation talks D-Bus (XDG portal) directly and never touches
   the `miguelruivo.flutter.plugins.filepicker` channel.
   The walk uses a tall phone-like test surface (800×1400) so all
   list tiles are built by the ListView (at the default 800×600 the
   oldest tiles never build and the long-press steps can't find them).
3. Saves one numbered PNG per capture via `binding.takeScreenshot`.

## Output folder (Flutter 3.35.7, verified by running the test)

The test writes the PNG bytes itself to:

```
integration_test/screenshots/
```

i.e. `<project>/integration_test/screenshots/01_library.png` …
`26_lan_client.png` (26 files). `binding.takeScreenshot` only
returns the PNG bytes under `flutter test`; nothing else in the
toolchain saves them, so the test does the writing. The folder is
git-ignored (screenshots are build artefacts, not sources).

Verified run 2026-11-19 on this VM
(`flutter test -d flutter-tester ...`, ~72 s): **all 26 PNGs, test
passed**, 800×1400 each, 23,601–134,996 bytes.

## Non-blank assertion

After the walk, the test asserts every screenshot is non-blank: file
size above 8000 bytes AND more than one distinct colour when sampled
from the decoded pixels. A blank render fails loudly instead of
silently.

## flutter-tester fallback (no device)

Under plain `flutter test` the `captureScreenshot` channel has no
implementation, so `binding.takeScreenshot` throws
`MissingPluginException`. The harness then captures the same pixels
from a `RepaintBoundary` wrapped around the app instead, so the walk
and the non-blank assertions still run. On a real device/emulator
the `takeScreenshot` path is used.

## Linux prerequisite: a system D-Bus (share step only)

Step 13 starts the real `ShareServer`, whose `_urls()` calls
`NetworkInfo.getWifiIP()` — on Linux that talks to NetworkManager
over the **system** D-Bus. With no system bus at all, an uncaught
async error from the D-Bus signal stream fails the test (the
`catch` in `_urls` can't catch it — it doesn't go through the
awaited future). Start one first (needs the `messagebus` user and
`/usr/share/dbus-1/system.conf`, both present on this VM):

```sh
dbus-daemon --system --fork
```

With a bus running but no NetworkManager, the lookup fails cleanly
through the awaited path and the server falls back to the loopback
URL (`http://127.0.0.1:<port>/`), which is what `13_share.png`
shows. The bus does not survive a VM reboot — restart it before
re-running the harness.

## Notes / known gaps

- The LAN client capture (`26_lan_client.png`) shows the connect
  form plus the connection error: it dials `http://192.168.1.5:8765`
  and no server is there. The client itself is the real `LanClient`
  (not a stub); the shot is honest about the missing peer. The
  dial fails fast on this VM (~0.3 s), so `pumpAndSettle` settles.
- The share capture (`13_share.png`) uses the real `ShareServer`
  (real shelf server on 0.0.0.0, loopback URL + random 6-digit PIN +
  QR). On a phone the Wi-Fi IP would appear instead of loopback.
- The فارسی sample file's school year is the import-stamped current
  year: the spec'd `updateFileMeta` has no `schoolYear` parameter,
  so the harness value `1404-1405` cannot be set from the UI layer.
- The seeded extras import جزوه ریاضی فصل ۳ نهم.pdf three times
  (original + exact duplicate + version conflict), so that filename
  matches three tiles: the walk long-presses it by tile key
  (`file_1`, the original) instead of by text.
- Test-harness quirk worth knowing: a `testWidgets` body runs in
  the widget-test binding's fake-async zone, so real async work
  (file IO, `SharedPreferences`) never completes there — all seeding
  and file writes in this harness go through `tester.runAsync()`
  (see `test/ui/test_helpers.dart`).
