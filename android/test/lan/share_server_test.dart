// Tests for the share server (phone hosts, laptop reads).
//
// The real server is started on 127.0.0.1:0 and hit over HTTP with a
// real client, so the PIN gate, lockout, headers and file streaming
// are all exercised end to end. A fresh server (fresh PIN, fresh
// failure counters) is started per test so the lockout test cannot
// poison the others.
import 'dart:convert';
import 'dart:io';

import 'package:darspack/lan/share_server.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;

import 'fake_library.dart';

void main() {
  // Plain unit tests don't init the widget binding, so rootBundle
  // (which the server uses for assets/web/index.html + fonts) would
  // throw. Initializing it here makes asset loading work in tests —
  // but the binding also installs a mock HttpClient that answers 400
  // to every request, so restore the real one right away.
  TestWidgetsFlutterBinding.ensureInitialized();
  HttpOverrides.global = null;

  late Directory tmp;
  late FakeLibrary library;
  late ShareServer server;
  late http.Client client;
  late String base;
  late String pin;

  setUp(() async {
    tmp = await Directory.systemTemp.createTemp('darspack-lan-test-');
    library = FakeLibrary(tmp);
    final mathId = library.addSubject('ریاضی');
    library.addSubject('علوم تجربی');
    await library.addFile(
      'جزوه ریاضی فصل ۳.pdf',
      utf8.encode('%PDF-1.4 fake pdf bytes'),
      subjectId: mathId,
      chapter: 3,
      lesson: 2,
      kind: 'جزوه',
    );
    await library.addFile(
      'عکس تخته.png',
      [0x89, 0x50, 0x4E, 0x47, 1, 2, 3],
      kind: 'سایر',
    );
    await library.addFile(
      'بایگانی.zip',
      [0x50, 0x4B, 0x03, 0x04, 9, 9, 9],
      kind: 'سایر',
    );
    server = ShareServer(library);
    final urls = await server.start();
    base = 'http://127.0.0.1:${server.port}';
    pin = server.pin;
    expect(urls, isNotEmpty);
    expect(urls.first, startsWith('http://127.0.0.1:${server.port}/'));
    client = http.Client();
  });

  tearDown(() async {
    client.close();
    await server.stop();
    await tmp.delete(recursive: true);
  });

  Uri api(String path, {String? pin, Map<String, String>? extra}) {
    final params = <String, String>{};
    if (pin != null) params['pin'] = pin;
    if (extra != null) params.addAll(extra);
    return Uri.parse('$base$path').replace(queryParameters: params);
  }

  test('start() reports a running server with a 6-digit Latin PIN',
      () {
    expect(server.isRunning, isTrue);
    expect(server.port, greaterThan(0));
    expect(RegExp(r'^\d{6}$').hasMatch(pin), isTrue);
  });

  test('GET / serves the web UI', () async {
    final res = await client.get(Uri.parse('$base/'));
    expect(res.statusCode, 200);
    expect(res.headers['content-type'], contains('text/html'));
    expect(res.body, contains('درس‌پک'));
    expect(res.body, contains('?pin='));
    expect(res.body, contains('/api/search'));
  });

  test('GET /fonts/Vazirmatn-Regular.ttf serves the font', () async {
    final res = await client
        .get(Uri.parse('$base/fonts/Vazirmatn-Regular.ttf'));
    expect(res.statusCode, 200);
    expect(res.headers['content-type'], contains('font/ttf'));
    expect(res.bodyBytes.length, greaterThan(10000));
    final missing =
        await client.get(Uri.parse('$base/fonts/NotAFont.ttf'));
    expect(missing.statusCode, 404);
  });

  test('API without PIN is 403 pin; with PIN it answers', () async {
    final noPin = await client.get(Uri.parse('$base/api/subjects'));
    expect(noPin.statusCode, 403);
    expect(jsonDecode(noPin.body), {'error': 'pin'});

    final ok = await client.get(api('/api/subjects', pin: pin));
    expect(ok.statusCode, 200);
    expect(ok.headers['cache-control'], 'no-store');
    final data = jsonDecode(ok.body) as Map<String, dynamic>;
    final subjects = data['subjects'] as List;
    expect(subjects.length, 2);
    final math = subjects.firstWhere((s) => s['name'] == 'ریاضی');
    expect(math['count'], 1);
    expect(data['unclassified'], 2);
  });

  test('search: query, subject filter (Persian digits), unclassified',
      () async {
    final byQuery = await client
        .get(api('/api/search', pin: pin, extra: {'q': 'ریاضی'}));
    expect(byQuery.statusCode, 200);
    var files =
        (jsonDecode(byQuery.body) as Map)['files'] as List;
    expect(files.length, 1);
    expect(files.first['name'], 'جزوه ریاضی فصل ۳.pdf');
    expect(files.first['chapter'], 3);
    expect(files.first['lesson'], 2);
    expect(files.first['kind'], 'جزوه');
    expect(files.first['size'], greaterThan(0));
    expect(files.first['available'], isTrue);

    // Persian digit subject_id must work, like the Windows server.
    final bySubject = await client.get(api('/api/search',
        pin: pin, extra: {'subject_id': '۱'}));
    files = (jsonDecode(bySubject.body) as Map)['files'] as List;
    expect(files.length, 1);

    final unclassified = await client.get(api('/api/search',
        pin: pin, extra: {'unclassified': '1'}));
    files = (jsonDecode(unclassified.body) as Map)['files'] as List;
    expect(files.length, 2);
  });

  test('manifest is keyed by sha256', () async {
    final res = await client.get(api('/api/manifest', pin: pin));
    expect(res.statusCode, 200);
    final data = jsonDecode(res.body) as Map<String, dynamic>;
    expect(data.length, 3);
    final entry = data.values
        .firstWhere((v) => v['name'] == 'جزوه ریاضی فصل ۳.pdf');
    expect(entry['size'], greaterThan(0));
  });

  test('file: pdf inline, zip attachment, ?download=1 forces download',
      () async {
    final pdf = await client.get(api('/api/file/1', pin: pin));
    expect(pdf.statusCode, 200);
    expect(pdf.headers['content-type'], 'application/pdf');
    expect(pdf.headers['content-disposition'], startsWith('inline;'));
    expect(pdf.body, contains('fake pdf bytes'));

    final forced =
        await client.get(api('/api/file/1', pin: pin,
            extra: {'download': '1'}));
    expect(forced.headers['content-disposition'],
        startsWith('attachment;'));

    final zip = await client.get(api('/api/file/3', pin: pin));
    expect(zip.statusCode, 200);
    expect(zip.headers['content-type'], 'application/octet-stream');
    expect(zip.headers['content-disposition'],
        startsWith('attachment;'));

    final missing = await client.get(api('/api/file/999', pin: pin));
    expect(missing.statusCode, 404);
    expect(jsonDecode(missing.body), {'error': 'not found'});

    final badId = await client.get(api('/api/file/abc', pin: pin));
    expect(badId.statusCode, 400);
    expect(jsonDecode(badId.body), {'error': 'id'});
  });

  test('upload lands unclassified, kind/lesson stored, subject prefill',
      () async {
    final res = await client.post(
      api('/api/upload', pin: pin, extra: {
        'name': 'نمونه سوال علوم نهم.pdf',
        'kind': 'نمونه‌سوال',
        'lesson': '۵',
        'subject': 'علوم تجربی',
      }),
      body: utf8.encode('%PDF-1.4 uploaded bytes'),
    );
    expect(res.statusCode, 200);
    final data = jsonDecode(res.body) as Map<String, dynamic>;
    expect(data['status'], 'imported');
    expect(data['prefill'], {'subject': 'علوم تجربی'});

    // The file is in the library but unclassified (subject never stored).
    final unclassified = await client.get(api('/api/search',
        pin: pin, extra: {'unclassified': '1'}));
    final files =
        (jsonDecode(unclassified.body) as Map)['files'] as List;
    final uploaded = files.firstWhere(
        (f) => f['name'] == 'نمونه سوال علوم نهم.pdf');
    expect(uploaded['kind'], 'نمونه‌سوال');
    expect(uploaded['lesson'], 5);
    expect(uploaded['subject'], isNull);

    // Same bytes again -> duplicate, naming the twin.
    final dup = await client.post(
      api('/api/upload', pin: pin,
          extra: {'name': 'نمونه سوال علوم نهم.pdf'}),
      body: utf8.encode('%PDF-1.4 uploaded bytes'),
    );
    expect(jsonDecode(dup.body)['status'], 'duplicate');
  });

  test('lockout after 5 wrong PINs; correct PIN still locked', () async {
    for (var i = 0; i < 4; i++) {
      final res =
          await client.get(api('/api/subjects', pin: '000000'));
      expect(res.statusCode, 403);
      expect(jsonDecode(res.body), {'error': 'pin'});
    }
    final fifth =
        await client.get(api('/api/subjects', pin: '000000'));
    expect(fifth.statusCode, 403);
    expect(jsonDecode(fifth.body), {'error': 'lockout'});

    final correct = await client.get(api('/api/subjects', pin: pin));
    expect(correct.statusCode, 403);
    expect(jsonDecode(correct.body), {'error': 'lockout'});
  });

  test('stop() leaves the server down and never touches the library',
      () async {
    await server.stop();
    expect(server.isRunning, isFalse);
    expect(server.port, 0);
    // The library is still usable after stop (it belongs to the app).
    final files = await library.searchFiles(query: '');
    expect(files.length, 3);
    await expectLater(
      client.get(Uri.parse('$base/api/subjects')),
      throwsA(isA<http.ClientException>()),
    );
  });
}
