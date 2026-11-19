// Streaming SHA-256 (هش فایل).
//
// Port of Windows `core/hashing.py`. Reads the file in 1 MB chunks so a
// large PDF never loads fully into RAM. `onProgress(done, total)` lets
// the UI show a bar without knowing any hashing details.

import 'dart:io';

import 'package:crypto/crypto.dart';

const int chunkSize = 1024 * 1024; // 1 MB

/// Return the hex SHA-256 of [file], read in chunks.
Future<String> sha256File(
  File file, {
  void Function(int done, int total)? onProgress,
  int? size,
}) async {
  final total = size ?? await file.length();
  final sink = _DigestSink();
  final input = sha256.startChunkedConversion(sink);
  var done = 0;
  final raf = await file.open();
  try {
    while (true) {
      final chunk = await raf.read(chunkSize);
      if (chunk.isEmpty) break;
      input.add(chunk);
      done += chunk.length;
      onProgress?.call(done, total);
    }
  } finally {
    await raf.close();
  }
  input.close();
  return sink.digest.toString();
}

class _DigestSink implements Sink<Digest> {
  Digest? _digest;
  Digest get digest => _digest!;
  @override
  void add(Digest data) => _digest = data;
  @override
  void close() {}
}

/// Synchronous SHA-256 of in-memory [bytes] (for package verification).
String sha256Bytes(List<int> bytes) => sha256.convert(bytes).toString();
