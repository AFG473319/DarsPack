// Tests for streaming SHA-256 — port of Windows
// tests/test_hashing_suggest.py (hashing half).
import 'dart:io';

import 'package:crypto/crypto.dart';
import 'package:darspack/core/hashing.dart';
import 'package:flutter_test/flutter_test.dart';

const abcSha256 =
    'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad';
const emptySha256 =
    'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855';

void main() {
  test('sha256 known vector', () async {
    final dir = await Directory.systemTemp.createTemp('darspack-hash-');
    try {
      final p = File('${dir.path}/abc.bin')..writeAsBytesSync([97, 98, 99]);
      expect(await sha256File(p), abcSha256);
    } finally {
      await dir.delete(recursive: true);
    }
  });

  test('sha256 large file is chunked and progress reaches the end', () async {
    final dir = await Directory.systemTemp.createTemp('darspack-hash-');
    try {
      final data = List.filled(
        3 * 1024 * 1024,
        120,
      ); // forces several 1 MB chunks
      final p = File('${dir.path}/big.bin')..writeAsBytesSync(data);
      final seen = <(int, int)>[];
      expect(
        await sha256File(
          p,
          onProgress: (done, total) => seen.add((done, total)),
        ),
        sha256.convert(data).toString(),
      );
      expect(seen.last, (data.length, data.length));
    } finally {
      await dir.delete(recursive: true);
    }
  });

  test('sha256 of empty file; progress never called', () async {
    final dir = await Directory.systemTemp.createTemp('darspack-hash-');
    try {
      final p = File('${dir.path}/empty.bin')..writeAsBytesSync([]);
      final seen = <(int, int)>[];
      expect(
        await sha256File(p, onProgress: (d, t) => seen.add((d, t))),
        emptySha256,
      );
      expect(seen, isEmpty);
    } finally {
      await dir.delete(recursive: true);
    }
  });

  test('sha256Bytes matches sha256File', () async {
    expect(sha256Bytes([97, 98, 99]), abcSha256);
  });
}
