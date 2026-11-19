// Jalali school-year helpers (سال تحصیلی).
//
// Port of Windows `core/schoolyear.py`. The Iranian school year starts
// on 1 Mehr (month 7) and is named after the two calendar years it
// spans, e.g. «1405-1406». Storing the school year per file lets a
// student keep this year's and last year's نمونه‌سوال side by side
// without confusion.

import 'package:shamsi_date/shamsi_date.dart';

const int monthMehr =
    7; // Jalali month 7 = Mehr; school starts on its first day

/// Return the school-year label («1405-1406») a Jalali date belongs to.
String schoolYearForJalali(int jalaliYear, int jalaliMonth) {
  if (jalaliMonth >= monthMehr) {
    return '$jalaliYear-${jalaliYear + 1}';
  }
  return '${jalaliYear - 1}-$jalaliYear';
}

/// Return the school-year label for a Gregorian [date].
String schoolYearForDate(DateTime date) {
  final jalali = Jalali.fromDateTime(date);
  return schoolYearForJalali(jalali.year, jalali.month);
}

/// The school year today belongs to.
String currentSchoolYear([DateTime? today]) =>
    schoolYearForDate(today ?? DateTime.now());
