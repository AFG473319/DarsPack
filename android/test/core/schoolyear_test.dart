// Tests for Jalali school-year boundaries — port of Windows
// tests/test_schoolyear.py.
import 'package:darspack/core/schoolyear.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('Mehr 1 starts the new year', () {
    expect(schoolYearForJalali(1405, 7), '1405-1406');
  });

  test('late Shahrivar belongs to the previous year', () {
    expect(schoolYearForJalali(1405, 6), '1404-1405');
  });

  test('mid-year months', () {
    expect(schoolYearForJalali(1405, 9), '1405-1406');
    expect(schoolYearForJalali(1406, 3), '1405-1406');
  });

  test('all twelve months of 1405', () {
    const expected = {
      1: '1404-1405',
      2: '1404-1405',
      3: '1404-1405',
      4: '1404-1405',
      5: '1404-1405',
      6: '1404-1405',
      7: '1405-1406',
      8: '1405-1406',
      9: '1405-1406',
      10: '1405-1406',
      11: '1405-1406',
      12: '1405-1406',
    };
    for (final entry in expected.entries) {
      expect(schoolYearForJalali(1405, entry.key), entry.value);
    }
  });

  test('currentSchoolYear honors a given date', () {
    // 1 Mehr 1405 = 23 Sep 2026; 31 Shahrivar 1405 = 22 Sep 2026.
    expect(currentSchoolYear(DateTime(2026, 9, 23)), '1405-1406');
    expect(currentSchoolYear(DateTime(2026, 9, 22)), '1404-1405');
    expect(currentSchoolYear(DateTime(2026, 10, 25)), '1405-1406');
  });

  test('today has a school year', () {
    final res = currentSchoolYear();
    expect(res.contains('-'), isTrue);
    expect(res.length, 9); // e.g. 1405-1406
  });
}
