// Share server: the phone hosts its library so a laptop browser can
// read it (سرور شبکه‌ی محلی).
//
// Embedded shelf server on a random port, bound to all interfaces,
// ONLY while sharing is on. Mirrors the Windows server
// (src/darspack/web/server.py) endpoint for endpoint:
//   GET  /                    -> assets/web/index.html
//   GET  /fonts/<name>        -> Vazirmatn fonts from Flutter assets
//   GET  /api/manifest        -> {sha256: {name, size}}
//   GET  /api/subjects        -> {subjects: [{id, name, count}],
//                                 unclassified: n}
//   GET  /api/search?q=&subject_id=&kind=&unclassified=
//   GET  /api/file/<id>       -> inline for pdf/png/jpg/jpeg/gif/txt,
//                                attachment otherwise; ?download=1 forces
//                                a download, ?inline=1 forces inline
//   POST /api/upload?name=&kind=&lesson=&subject=  (raw file body)
// Every /api/* call requires ?pin= (random 6-digit per session, Latin
// digits). Wrong PIN 5 times -> that IP is locked out for 30 s
// (constant-time PIN compare, like hmac.compare_digest).
// Max upload 200 MB. API responses carry Cache-Control: no-store.
//
// The Library belongs to the app, NOT to the server: stop() waits for
// in-flight requests before closing, and never closes the Library.
import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:math';

import 'package:darspack/core/library.dart';
import 'package:darspack/core/models.dart';
import 'package:flutter/services.dart';
import 'package:network_info_plus/network_info_plus.dart';
import 'package:shelf/shelf.dart';
import 'package:shelf/shelf_io.dart' as shelf_io;
import 'package:shelf_router/shelf_router.dart';

import 'lan_utils.dart';

/// Vazirmatn files the web UI may fetch (same whitelist as Windows).
const _fontFiles = {
  'Vazirmatn-Regular.ttf',
  'Vazirmatn-Medium.ttf',
  'Vazirmatn-SemiBold.ttf',
  'Vazirmatn-Bold.ttf',
};

class ShareServer {
  final Library _library;

  /// Random 6-digit PIN for this session (Latin digits).
  late final String _pin;

  HttpServer? _server;
  int _inFlight = 0;
  bool _stopping = false;

  /// ip -> timestamps of failed PIN attempts (for the 30 s lockout).
  final Map<String, List<DateTime>> _fails = {};

  ShareServer(Library library) : _library = library {
    final random = Random.secure();
    _pin = List.generate(6, (_) => random.nextInt(10)).join();
  }

  String get pin => _pin;
  int get port => _server?.port ?? 0;
  bool get isRunning => _server != null;

  /// Start listening on 0.0.0.0, random port. Returns the share URLs,
  /// e.g. `http://192.168.1.4:54321/` (PIN is shown separately).
  Future<List<String>> start() async {
    if (_server != null) return _urls();
    _stopping = false;
    final handler = const Pipeline()
        .addMiddleware(_trackInFlight)
        .addHandler(_router.call);
    _server = await shelf_io.serve(handler, '0.0.0.0', 0);
    return _urls();
  }

  /// Stop listening, after in-flight requests finish. The Library is
  /// never closed here — it belongs to the app.
  Future<void> stop() async {
    final server = _server;
    if (server == null) return;
    _stopping = true;
    final deadline = DateTime.now().add(const Duration(seconds: 10));
    while (_inFlight > 0 && DateTime.now().isBefore(deadline)) {
      await Future<void>.delayed(const Duration(milliseconds: 25));
    }
    await server.close(force: false);
    _server = null;
    _stopping = false;
  }

  Future<List<String>> _urls() async {
    final ips = <String>{'127.0.0.1'};
    try {
      final wifiIp = await NetworkInfo().getWifiIP();
      if (wifiIp != null && wifiIp.isNotEmpty) ips.add(wifiIp);
    } catch (_) {
      // No Wi-Fi (emulator / test): loopback is still a valid URL.
    }
    return ips.map((ip) => 'http://$ip:$port/').toList();
  }

  // -- middleware -------------------------------------------------------

  Middleware get _trackInFlight => (Handler inner) {
        return (Request request) async {
          if (_stopping) {
            return Response(503, body: 'stopping');
          }
          _inFlight++;
          try {
            return await inner(request);
          } finally {
            _inFlight--;
          }
        };
      };

  Router get _router {
    final router = Router();
    router.get('/', _serveIndex);
    router.get('/index.html', _serveIndex);
    router.get('/fonts/<name>', _serveFont);
    router.get('/api/manifest', _manifest);
    router.get('/api/subjects', _subjects);
    router.get('/api/search', _search);
    router.get('/api/file/<id>', _serveFile);
    router.post('/api/upload', _upload);
    return router;
  }

  // -- PIN gate ---------------------------------------------------------

  String _clientIp(Request request) {
    final info =
        request.context['shelf.io.connection_info'] as HttpConnectionInfo?;
    return info?.remoteAddress.address ?? 'unknown';
  }

  bool _lockedOut(String ip) {
    final cutoff = DateTime.now().subtract(
      const Duration(seconds: lockoutSeconds),
    );
    final fails = _fails[ip];
    if (fails == null) return false;
    fails.removeWhere((t) => t.isBefore(cutoff));
    if (fails.isEmpty) _fails.remove(ip);
    return fails.length >= maxPinFails;
  }

  /// Returns null when the PIN is OK, else 'pin' or 'lockout'
  /// (same rule as the Windows server's check_pin).
  String? _pinError(Request request) {
    final ip = _clientIp(request);
    if (_lockedOut(ip)) return 'lockout';
    final given = request.url.queryParameters['pin'] ?? '';
    if (constantTimeEquals(given, _pin)) {
      _fails.remove(ip);
      return null;
    }
    _fails.putIfAbsent(ip, () => []).add(DateTime.now());
    return _lockedOut(ip) ? 'lockout' : 'pin';
  }

  /// Returns a 403 response when the PIN is wrong/locked, else null.
  Response? _requirePin(Request request) {
    final error = _pinError(request);
    if (error == null) return null;
    return _jsonError(error, 403);
  }

  // -- response helpers -------------------------------------------------

  Response _json(Object obj, {int status = 200}) => Response(
        status,
        body: jsonEncode(obj),
        headers: {
          'content-type': 'application/json; charset=utf-8',
          'cache-control': 'no-store',
        },
      );

  Response _jsonError(String error, int status) =>
      _json({'error': error}, status: status);

  static int? _intParam(String? raw) {
    if (raw == null) return null;
    final latin = latinDigits(raw);
    return latin.isNotEmpty && int.tryParse(latin) != null
        ? int.parse(latin)
        : null;
  }

  static bool _flagParam(String? raw) =>
      raw != null && (raw == '1' || raw.toLowerCase() == 'true');

  static String? _nonEmpty(String? raw) =>
      raw == null || raw.isEmpty ? null : raw;

  static Map<String, dynamic> _fileJson(LibraryFile f) => {
        'id': f.id,
        'name': f.originalName,
        'subject': f.subjectName,
        'chapter': f.chapter,
        'lesson': f.lesson,
        'kind': f.kind,
        'size': f.sizeBytes,
        'available': f.available,
      };

  // -- static files -----------------------------------------------------

  Future<Response> _serveIndex(Request request) async {
    final data = await rootBundle.load('assets/web/index.html');
    return Response.ok(
      data.buffer.asUint8List(),
      headers: {
        'content-type': 'text/html; charset=utf-8',
        'cache-control': 'no-store',
      },
    );
  }

  Future<Response> _serveFont(Request request) async {
    final name = request.params['name'] ?? '';
    if (!_fontFiles.contains(name)) {
      return Response.notFound('not found');
    }
    final data = await rootBundle.load('assets/fonts/$name');
    return Response.ok(
      data.buffer.asUint8List(),
      headers: {
        'content-type': 'font/ttf',
        'cache-control': 'public, max-age=86400',
      },
    );
  }

  // -- API --------------------------------------------------------------

  /// GET /api/manifest — {sha256: {name, size}}, like catalog_manifest
  /// in the Windows web/sync.py (first row wins per hash).
  Future<Response> _manifest(Request request) async {
    final pinError = _requirePin(request);
    if (pinError != null) return pinError;
    final files = await _library.searchFiles(query: '', limit: 100000);
    final manifest = <String, Map<String, dynamic>>{};
    for (final f in files) {
      manifest.putIfAbsent(
        f.sha256,
        () => {'name': f.originalName, 'size': f.sizeBytes},
      );
    }
    return _json(manifest);
  }

  /// GET /api/subjects — subjects with counts + the unclassified count,
  /// so the web UI needs no per-chip requests (Windows D1).
  Future<Response> _subjects(Request request) async {
    final pinError = _requirePin(request);
    if (pinError != null) return pinError;
    final subjects = await _library.subjectsWithCounts();
    final unclassified = await _library.unclassifiedCount();
    return _json({
      'subjects': subjects
          .map((s) => {'id': s.id, 'name': s.name, 'count': s.fileCount})
          .toList(),
      'unclassified': unclassified,
    });
  }

  /// GET /api/search?q=&subject_id=&kind=&unclassified=
  /// (Persian digits accepted for subject_id, like Windows).
  Future<Response> _search(Request request) async {
    final pinError = _requirePin(request);
    if (pinError != null) return pinError;
    final q = request.url.queryParameters;
    final files = await _library.searchFiles(
      query: q['q'] ?? '',
      subjectId: _intParam(q['subject_id']),
      kind: _nonEmpty(q['kind']),
      unclassifiedOnly: _flagParam(q['unclassified']),
      limit: 300,
    );
    return _json({'files': files.map(_fileJson).toList()});
  }

  /// `GET /api/file/{id}` — inline for whitelisted types with a FIXED
  /// Content-Type, attachment otherwise; `?download=1` forces a download.
  Future<Response> _serveFile(Request request) async {
    final pinError = _requirePin(request);
    if (pinError != null) return pinError;
    final id = _intParam(request.params['id']);
    if (id == null) return _jsonError('id', 400);
    final found = await _library.getFile(id);
    if (found == null) return _jsonError('not found', 404);
    final file = _library.storedFileFor(found);
    if (!await file.exists()) return _jsonError('file missing', 404);
    final name = found.originalName;
    final dot = name.lastIndexOf('.');
    final ext = dot >= 0 ? name.substring(dot).toLowerCase() : '';
    final inlineType = inlineContentTypes[ext];
    final isWhitelisted = inlineType != null;
    final q = request.url.queryParameters;
    final forceDownload = _flagParam(q['download']);
    final forceInline = _flagParam(q['inline']);
    final String disposition;
    if (forceDownload) {
      disposition = 'attachment';
    } else if (forceInline && isWhitelisted) {
      disposition = 'inline';
    } else {
      disposition = isWhitelisted ? 'inline' : 'attachment';
    }
    final length = await file.length();
    return Response.ok(
      file.openRead(),
      headers: {
        'content-type': inlineType ?? 'application/octet-stream',
        'content-disposition':
            "$disposition; filename*=UTF-8''${Uri.encodeComponent(name)}",
        'content-length': '$length',
      },
    );
  }

  /// POST /api/upload?name=&kind=&lesson=&subject= with the RAW file
  /// as the body. Staged to temp, then imported through the normal
  /// importer: kind/lesson are stored, subject is NEVER stored — it
  /// travels back on the reply as `prefill`, and the file lands
  /// unclassified (Windows G4).
  Future<Response> _upload(Request request) async {
    final pinError = _requirePin(request);
    if (pinError != null) return pinError;
    final q = request.url.queryParameters;
    var name = q['name'] ?? 'upload.bin';
    name = name.split('/').last.split('\\').last; // strip any path part
    if (name.isEmpty) name = 'upload.bin';
    final length = request.contentLength ?? -1;
    if (length <= 0 || length > maxUploadBytes) {
      return _jsonError('size', 413);
    }
    final tmpDir =
        await Directory.systemTemp.createTemp('darspack-upload-');
    final tmp = File('${tmpDir.path}/upload${_safeSuffix(name)}');
    try {
      var received = 0;
      final sink = tmp.openWrite();
      try {
        await for (final chunk in request.read()) {
          received += chunk.length;
          if (received > maxUploadBytes) {
            await sink.close();
            return _jsonError('size', 413);
          }
          sink.add(chunk);
        }
      } finally {
        await sink.close();
      }
      if (received != length) return _jsonError('incomplete', 400);
      final meta = <String, dynamic>{};
      final kind = _nonEmpty(q['kind']);
      if (kind != null) meta['kind'] = kind;
      final lesson = _intParam(q['lesson']);
      if (lesson != null) meta['lesson'] = lesson;
      final subject = _nonEmpty(q['subject']);
      if (subject != null) meta['subject'] = subject;
      final result = await _library.importFile(
        tmp,
        displayName: name,
        meta: meta.isEmpty ? null : meta,
      );
      final reply = <String, dynamic>{
        'status': result.status,
        'message': result.messageFa,
      };
      if (result.prefill != null) reply['prefill'] = result.prefill;
      return _json(reply);
    } finally {
      // The staged temp file is never library data — delete it even
      // when the import failed (Windows B4).
      try {
        await tmpDir.delete(recursive: true);
      } catch (_) {}
    }
  }

  /// Keep only a safe suffix for the staged temp file name.
  static String _safeSuffix(String name) {
    final dot = name.lastIndexOf('.');
    if (dot < 0) return '.bin';
    final ext =
        name.substring(dot).replaceAll(RegExp(r'[^A-Za-z0-9._-]'), '');
    if (ext.isEmpty) return '.bin';
    return ext.length > 16 ? ext.substring(0, 16) : ext;
  }
}
