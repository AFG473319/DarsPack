import 'package:darspack/lan/lan_utils.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('latinDigits converts Persian and Arabic digits', () {
    expect(latinDigits('۱۲۳'), '123');
    expect(latinDigits('١٢٣'), '123');
    expect(latinDigits('فصل ۳'), 'فصل 3');
    expect(latinDigits('abc123'), 'abc123');
    expect(latinDigits(''), '');
  });

  test('constantTimeEquals compares PINs', () {
    expect(constantTimeEquals('123456', '123456'), isTrue);
    expect(constantTimeEquals('123456', '123457'), isFalse);
    expect(constantTimeEquals('123456', '12345'), isFalse);
    expect(constantTimeEquals('', ''), isTrue);
  });

  test('inline types cover the Windows whitelist', () {
    expect(inlineContentTypes['.pdf'], 'application/pdf');
    expect(inlineContentTypes['.txt'], contains('text/plain'));
    expect(inlineContentTypes.containsKey('.zip'), isFalse);
    expect(maxUploadBytes, 200 * 1024 * 1024);
  });
}
