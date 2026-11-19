// Tests for Persian normalization — port of Windows tests/test_normalize.py.
import 'package:darspack/core/normalize.dart';
import 'package:flutter_test/flutter_test.dart';

const zwnj = '\u200c';

void main() {
  test('normalize table (Windows CASES)', () {
    const cases = {
      'ریاضی': 'ریاضی',
      'رياضي نهم': 'ریاضی نهم', // Arabic ي → Persian ی
      'كاربرگ': 'کاربرگ', // Arabic ك → Persian ک
      'فصل ۳': 'فصل 3', // Persian digit → Latin
      'فصل ٤': 'فصل 4', // Arabic-Indic digit → Latin
      'نمونه‌سوال': 'نمونه سوال', // ZWNJ treated as space
      'ریاضی   نهم': 'ریاضی نهم', // collapsed spaces
      '  جزوه  ': 'جزوه', // stripped
      'جزءُ': 'جزء', // diacritics removed
    };
    for (final entry in cases.entries) {
      expect(
        normalize(entry.key),
        entry.value,
        reason: 'normalize(${entry.key})',
      );
    }
  });

  test('normalize more cases', () {
    const cases = {
      'جـــزوه': 'جزوه', // tatweel (کشیده) removed
      'مكتبة': 'مکتبه', // Arabic ة → ه (plus ك → ک)
      'ریاضی\n\tنهم': 'ریاضی نهم', // tabs/newlines collapse
      '$zwnjریاضی$zwnj': 'ریاضی', // edge ZWNJ → space → stripped
      'نمونه$zwnj$zwnjسوال': 'نمونه سوال', // double ZWNJ collapses
    };
    for (final entry in cases.entries) {
      expect(
        normalize(entry.key),
        entry.value,
        reason: 'normalize(${entry.key})',
      );
    }
  });

  test('matchKey casefolds Latin', () {
    expect(matchKey('Algebra.PDF'), 'algebra.pdf');
  });

  test('digit conversions round-trip', () {
    expect(persianDigits('1405'), '۱۴۰۵');
    expect(latinDigits('۱۴۰۵'), '1405');
    expect(latinDigits('٤٥٦'), '456');
    expect(latinDigits('۰۱۲۳۴۵۶۷۸۹'), '0123456789');
    expect(latinDigits('٠١٢٣٤٥٦٧٨٩'), '0123456789');
  });

  test('persianDigits only touches Latin digits', () {
    expect(persianDigits('٤'), '٤'); // Arabic-Indic passes through unchanged
  });

  test('normalize strips all Arabic diacritics', () {
    expect(normalize('دَرْسٌ مُهِمٌّ وَمُفِيدٌ'), 'درس مهم ومفید');
  });

  test('empty and null safety', () {
    expect(normalize(''), '');
    expect(normalize(null), '');
    expect(matchKey(null), '');
    expect(matchKey('   '), '');
    expect(matchKey('   \t\n  '), '');
    expect(latinDigits(''), '');
    expect(persianDigits(''), '');
  });
}
