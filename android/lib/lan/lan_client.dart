// Client for the WINDOWS DarsPack share server (کلاینت شبکه‌ی محلی).
//
// Talks to a Windows desktop running DarsPack with sharing on:
//   GET  /api/search?q=&subject_id=&kind=&unclassified=
//   GET  /api/subjects
//   GET  /api/manifest
//   GET  /api/file/<id>
//   POST /api/upload?name=&kind=&lesson=&subject=  (raw file body)
// Every /api/* call carries ?pin=<6-digit PIN>. Wrong PIN 5 times ->
// the server locks that IP out for 30 s (403 {"error":"pin"} vs
// {"error":"lockout"} — surfaced as distinct exceptions so the UI can
// say «رمز اشتباه است» vs «به‌خاطر تلاش‌های ناموفق، ۳۰ ثانیه صبر کنید»).
import 'dart:convert';
import 'dart:io';

import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';

import 'lan_utils.dart';

/// One file on the remote (Windows) library, as /api/search returns it.
class RemoteFile {
  final int id;
  final String name;
  final String? subject;
  final int? chapter;
  final int? lesson;
  final String? kind;
  final int size;
  final bool available;

  const RemoteFile({
    required this.id,
    required this.name,
    this.subject,
    this.chapter,
    this.lesson,
    this.kind,
    required this.size,
    required this.available,
  });

  factory RemoteFile.fromJson(Map<String, dynamic> json) => RemoteFile(
        id: (json['id'] as num).toInt(),
        name: json['name'] as String? ?? '',
        subject: json['subject'] as String?,
        chapter: (json['chapter'] as num?)?.toInt(),
        lesson: (json['lesson'] as num?)?.toInt(),
        kind: json['kind'] as String?,
        size: (json['size'] as num?)?.toInt() ?? 0,
        available: json['available'] as bool? ?? true,
      );
}

/// One subject on the remote library, with its file count.
class RemoteSubject {
  final int id;
  final String name;
  final int count;

  const RemoteSubject({
    required this.id,
    required this.name,
    required this.count,
  });

  factory RemoteSubject.fromJson(Map<String, dynamic> json) =>
      RemoteSubject(
        id: (json['id'] as num).toInt(),
        name: json['name'] as String? ?? '',
        count: (json['count'] as num?)?.toInt() ?? 0,
      );
}

/// A saved server address + PIN (SharedPreferences).
class SavedLanServer {
  final String baseUrl;
  final String pin;

  const SavedLanServer(this.baseUrl, this.pin);
}

/// Base failure for LAN calls: [message] is safe to show the user,
/// [statusCode] is the HTTP status (null for transport errors),
/// [error] is the server's {"error": ...} value when there is one.
class LanException implements Exception {
  final String message;
  final int? statusCode;
  final String? error;

  const LanException(this.message, {this.statusCode, this.error});

  @override
  String toString() => 'LanException: $message';
}

/// The PIN was wrong (403 {"error":"pin"}).
class LanPinException extends LanException {
  const LanPinException()
      : super('رمز اشتباه است', statusCode: 403, error: 'pin');
}

/// The server locked this IP out after 5 wrong PINs
/// (403 {"error":"lockout"}).
class LanLockoutException extends LanException {
  const LanLockoutException()
      : super('به‌خاطر تلاش‌های ناموفق، ۳۰ ثانیه صبر کنید',
            statusCode: 403, error: 'lockout');
}

/// Client for a Windows DarsPack share server.
class LanClient {
  /// Base URL of the server, e.g. `http://192.168.1.5:8080`
  /// (trailing slashes are stripped).
  final String baseUrl;

  /// 6-digit PIN for the server.
  final String pin;

  final http.Client _http;

  LanClient({
    required String baseUrl,
    required this.pin,
    http.Client? httpClient,
  })  : baseUrl = baseUrl.replaceAll(RegExp(r'/+$'), ''),
        _http = httpClient ?? http.Client();

  /// Close the underlying HTTP client. Call when the client is done.
  void close() => _http.close();

  Uri _api(String path, [Map<String, String>? query]) {
    final params = <String, String>{'pin': pin, ...?query};
    return Uri.parse(baseUrl).replace(path: path, queryParameters: params);
  }

  /// Throw the right exception for an HTTP [status] + [body], or return
  /// the body unchanged on success.
  String _check(int status, String body) {
    if (status == 200) return body;
    if (status == 403) {
      final error = _errorField(body);
      if (error == 'lockout') throw const LanLockoutException();
      throw const LanPinException();
    }
    final error = _errorField(body);
    throw LanException(_messageFor(status, error),
        statusCode: status, error: error);
  }

  static String? _errorField(String body) {
    try {
      final decoded = jsonDecode(body);
      if (decoded is Map<String, dynamic>) {
        final error = decoded['error'];
        return error is String ? error : null;
      }
    } catch (_) {
      // Not JSON — no error field.
    }
    return null;
  }

  static String _messageFor(int status, String? error) {
    if (error == 'size') return 'حجم فایل بیش از ۲۰۰ مگابایت است';
    if (error == 'not found') return 'فایل پیدا نشد';
    if (status == 404) return 'فایل پیدا نشد';
    return 'خطای سرور ($status)';
  }

  /// Search the remote library (mirrors /api/search on Windows).
  Future<List<RemoteFile>> search({
    String query = '',
    int? subjectId,
    String? kind,
    bool unclassifiedOnly = false,
  }) async {
    final params = <String, String>{'q': latinDigits(query)};
    if (subjectId != null) params['subject_id'] = '$subjectId';
    if (kind != null) params['kind'] = kind;
    if (unclassifiedOnly) params['unclassified'] = '1';
    final res = await _http.get(_api('/api/search', params));
    final body = _check(res.statusCode, res.body);
    final decoded = jsonDecode(body) as Map<String, dynamic>;
    final files = decoded['files'] as List? ?? const [];
    return files
        .map((f) => RemoteFile.fromJson(f as Map<String, dynamic>))
        .toList();
  }

  /// Subjects with file counts (mirrors /api/subjects on Windows).
  Future<List<RemoteSubject>> subjects() async {
    final res = await _http.get(_api('/api/subjects'));
    final body = _check(res.statusCode, res.body);
    final decoded = jsonDecode(body) as Map<String, dynamic>;
    final list = decoded['subjects'] as List? ?? const [];
    return list
        .map((s) => RemoteSubject.fromJson(s as Map<String, dynamic>))
        .toList();
  }

  /// The remote catalog manifest: {sha256: {name, size}}
  /// (mirrors /api/manifest on Windows).
  Future<Map<String, dynamic>> manifest() async {
    final res = await _http.get(_api('/api/manifest'));
    final body = _check(res.statusCode, res.body);
    return jsonDecode(body) as Map<String, dynamic>;
  }

  /// Download one remote file to [dest] (mirrors `GET /api/file/{id}`).
  Future<void> downloadFile(RemoteFile file, File dest) async {
    final request = http.Request('GET', _api('/api/file/${file.id}'));
    final streamed = await _http.send(request);
    if (streamed.statusCode != 200) {
      final body = await streamed.stream.bytesToString();
      _check(streamed.statusCode, body);
      return; // unreachable: _check throws on non-200
    }
    await dest.parent.create(recursive: true);
    final sink = dest.openWrite();
    try {
      await streamed.stream.pipe(sink);
    } finally {
      await sink.close();
    }
  }

  /// Upload [file] to the remote library as a RAW body (NOT multipart),
  /// mirroring /api/upload on Windows. Returns the server's JSON reply
  /// ({"status": "imported"|"duplicate"|"error", "message": ..., ...}).
  /// Throws [LanException] with error 'size' when the file is over 200 MB.
  Future<Map<String, dynamic>> uploadFile(
    File file, {
    String? name,
    String? kind,
    int? lesson,
    String? subject,
  }) async {
    final size = await file.length();
    if (size > maxUploadBytes) {
      throw const LanException('حجم فایل بیش از ۲۰۰ مگابایت است',
          statusCode: 413, error: 'size');
    }
    final displayName = name ?? file.uri.pathSegments.last;
    final params = <String, String>{'name': displayName};
    if (kind != null) params['kind'] = kind;
    if (lesson != null) params['lesson'] = latinDigits('$lesson');
    if (subject != null) params['subject'] = subject;
    final request =
        http.StreamedRequest('POST', _api('/api/upload', params));
    request.contentLength = size;
    // send() FIRST, then stream the body: awaiting addStream() before
    // send() deadlocks — nothing drains the sink until the request is
    // sent (the sink's addStream future only completes once the body
    // has actually been written out).
    final sendFuture = _http.send(request);
    await request.sink.addStream(file.openRead());
    await request.sink.close();
    final streamed = await sendFuture;
    final body = await streamed.stream.bytesToString();
    final checked = _check(streamed.statusCode, body);
    return jsonDecode(checked) as Map<String, dynamic>;
  }

  // -- Saved server (SharedPreferences) -------------------------------

  static const String savedUrlKey = 'lan_server_url';
  static const String savedPinKey = 'lan_server_pin';

  /// Save the server address + PIN after the user enters them once.
  static Future<void> saveServer(String baseUrl, String pin) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(savedUrlKey, baseUrl);
    await prefs.setString(savedPinKey, pin);
  }

  /// The saved server, or null when the user never entered one.
  static Future<SavedLanServer?> loadSavedServer() async {
    final prefs = await SharedPreferences.getInstance();
    final url = prefs.getString(savedUrlKey);
    final savedPin = prefs.getString(savedPinKey);
    if (url == null || savedPin == null) return null;
    return SavedLanServer(url, savedPin);
  }

  /// Forget the saved server (e.g. on logout).
  static Future<void> clearSavedServer() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(savedUrlKey);
    await prefs.remove(savedPinKey);
  }
}
