// Tests for LanClient against a small fake HTTP server that mimics
// the Windows share server: PIN gate (?pin=), 5-fails -> 30 s lockout,
// /api/search, /api/subjects, /api/manifest, /api/file/<id>,
// /api/upload with a RAW body (not multipart).
import 'dart:convert';
import 'dart:io';

import 'package:darspack/lan/lan_client.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

const _pin = '123456';

/// Minimal fake of the Windows server, in-memory.
class FakeWindowsServer {
  final HttpServer _http;
  final Map<String, List<DateTime>> _fails = {};
  List<int> lastUploadBody = [];
  String lastUploadName = '';

  FakeWindowsServer(this._http);

  static Future<FakeWindowsServer> bind() async {
    final http =
        await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    final server = FakeWindowsServer(http);
    http.listen(server._handle);
    return server;
  }

  int get port => _http.port;
  String get baseUrl => 'http://127.0.0.1:$port';

  Future<void> close() => _http.close(force: true);

  bool _lockedOut(String ip) {
    final cutoff = DateTime.now().subtract(const Duration(seconds: 30));
    final fails = _fails[ip];
    if (fails == null) return false;
    fails.removeWhere((t) => t.isBefore(cutoff));
    return fails.length >= 5;
  }

  Future<void> _handle(HttpRequest req) async {
    final ip = req.connectionInfo?.remoteAddress.address ?? 'unknown';
    final query = req.uri.queryParameters;
    final path = req.uri.path;
    if (path.startsWith('/api/')) {
      if (_lockedOut(ip)) {
        return _json(req, 403, {'error': 'lockout'});
      }
      if (query['pin'] != _pin) {
        _fails.putIfAbsent(ip, () => []).add(DateTime.now());
        final error = _lockedOut(ip) ? 'lockout' : 'pin';
        return _json(req, 403, {'error': error});
      }
      _fails.remove(ip);
    }
    if (path == '/api/search' && req.method == 'GET') {
      final q = query['q'] ?? '';
      final files = <Map<String, dynamic>>[
        {
          'id': 1,
          'name': 'جزوه ریاضی فصل ۳.pdf',
          'subject': 'ریاضی',
          'chapter': 3,
          'lesson': 2,
          'kind': 'جزوه',
          'size': 42,
          'available': true,
        },
        {
          'id': 2,
          'name': 'کاربرگ علوم.pdf',
          'subject': 'علوم تجربی',
          'chapter': null,
          'lesson': 5,
          'kind': 'کاربرگ',
          'size': 17,
          'available': false,
        },
      ].where((f) =>
          q.isEmpty || (f['name'] as String).contains(q) ||
          (f['subject'] as String?)?.contains(q) == true);
      return _json(req, 200, {'files': files.toList()});
    }
    if (path == '/api/subjects') {
      return _json(req, 200, {
        'subjects': [
          {'id': 1, 'name': 'ریاضی', 'count': 1},
          {'id': 2, 'name': 'علوم تجربی', 'count': 1},
        ],
        'unclassified': 3,
      });
    }
    if (path == '/api/manifest') {
      return _json(req, 200, {
        'abc123': {'name': 'جزوه ریاضی فصل ۳.pdf', 'size': 42},
      });
    }
    if (path == '/api/file/1') {
      req.response
        ..statusCode = 200
        ..headers.contentType = ContentType('application', 'pdf')
        ..headers.set('Content-Disposition', 'inline; filename="x.pdf"')
        ..add(utf8.encode('%PDF-1.4 remote bytes'));
      await req.response.close();
      return;
    }
    if (path.startsWith('/api/file/')) {
      return _json(req, 404, {'error': 'not found'});
    }
    if (path == '/api/upload' && req.method == 'POST') {
      final body = await req.fold<List<int>>(
          [], (acc, chunk) => acc..addAll(chunk));
      lastUploadBody = body;
      lastUploadName = query['name'] ?? '';
      return _json(req, 200, {
        'status': 'imported',
        'message': '«${query['name']}» وارد شد',
        'prefill': {'subject': query['subject']},
      });
    }
    req.response.statusCode = 404;
    await req.response.close();
  }

  Future<void> _json(
      HttpRequest req, int status, Map<String, dynamic> obj) async {
    req.response
      ..statusCode = status
      ..headers.contentType = ContentType.json
      ..headers.set('Cache-Control', 'no-store')
      ..write(jsonEncode(obj));
    await req.response.close();
  }
}

void main() {
  late FakeWindowsServer fake;
  late LanClient client;
  late Directory tmp;

  setUp(() async {
    SharedPreferences.setMockInitialValues({});
    fake = await FakeWindowsServer.bind();
    client = LanClient(baseUrl: fake.baseUrl, pin: _pin);
    tmp = await Directory.systemTemp.createTemp('darspack-client-test-');
  });

  tearDown(() async {
    client.close();
    await fake.close();
    await tmp.delete(recursive: true);
  });

  test('search parses RemoteFile rows', () async {
    final files = await client.search(query: 'ریاضی');
    expect(files.length, 1);
    final f = files.first;
    expect(f.id, 1);
    expect(f.name, 'جزوه ریاضی فصل ۳.pdf');
    expect(f.subject, 'ریاضی');
    expect(f.chapter, 3);
    expect(f.lesson, 2);
    expect(f.kind, 'جزوه');
    expect(f.size, 42);
    expect(f.available, isTrue);

    final all = await client.search();
    expect(all.length, 2);
    expect(all.last.available, isFalse);
  });

  test('subjects parses RemoteSubject rows', () async {
    final subjects = await client.subjects();
    expect(subjects.length, 2);
    expect(subjects.first.name, 'ریاضی');
    expect(subjects.first.count, 1);
  });

  test('manifest returns the sha256 map', () async {
    final manifest = await client.manifest();
    expect(manifest['abc123']['name'], 'جزوه ریاضی فصل ۳.pdf');
    expect(manifest['abc123']['size'], 42);
  });

  test('downloadFile writes the remote bytes to disk', () async {
    final file = RemoteFile(
      id: 1,
      name: 'جزوه ریاضی فصل ۳.pdf',
      size: 42,
      available: true,
    );
    final dest = File('${tmp.path}/downloaded.pdf');
    await client.downloadFile(file, dest);
    expect(await dest.readAsString(), '%PDF-1.4 remote bytes');
  });

  test('uploadFile sends the RAW body, not multipart', () async {
    final src = File('${tmp.path}/up.pdf');
    final bytes = utf8.encode('%PDF-1.4 upload me');
    await src.writeAsBytes(bytes);
    final reply = await client.uploadFile(
      src,
      kind: 'جزوه',
      lesson: 2,
      subject: 'ریاضی',
    );
    expect(reply['status'], 'imported');
    expect(reply['prefill'], {'subject': 'ریاضی'});
    // Raw body: exactly the file bytes, no multipart boundary.
    expect(fake.lastUploadBody, bytes);
    expect(fake.lastUploadName, 'up.pdf');
  });

  test('uploadFile refuses files over 200 MB without sending', () async {
    final big = File('${tmp.path}/big.bin');
    final raf = await big.open(mode: FileMode.write);
    await raf.truncate(201 * 1024 * 1024); // sparse: no real I/O
    await raf.close();
    await expectLater(
      client.uploadFile(big),
      throwsA(isA<LanException>()
          .having((e) => e.error, 'error', 'size')),
    );
    expect(fake.lastUploadBody, isEmpty);
  });

  test('wrong PIN throws LanPinException', () async {
    final bad = LanClient(baseUrl: fake.baseUrl, pin: '000000');
    await expectLater(
      bad.subjects(),
      throwsA(isA<LanPinException>()),
    );
    bad.close();
  });

  test('5 wrong PINs throw LanLockoutException', () async {
    final bad = LanClient(baseUrl: fake.baseUrl, pin: '000000');
    for (var i = 0; i < 4; i++) {
      await expectLater(bad.subjects(),
          throwsA(isA<LanPinException>()));
    }
    await expectLater(
      bad.subjects(),
      throwsA(isA<LanLockoutException>()),
    );
    // Even the right PIN is locked out now (same IP).
    await expectLater(
      client.subjects(),
      throwsA(isA<LanLockoutException>()),
    );
    bad.close();
  });

  test('server address + PIN round-trip through SharedPreferences',
      () async {
    expect(await LanClient.loadSavedServer(), isNull);
    await LanClient.saveServer(fake.baseUrl, _pin);
    final saved = await LanClient.loadSavedServer();
    expect(saved, isNotNull);
    expect(saved!.baseUrl, fake.baseUrl);
    expect(saved.pin, _pin);
    await LanClient.clearSavedServer();
    expect(await LanClient.loadSavedServer(), isNull);
  });
}
