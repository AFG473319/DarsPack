// Tests for filename suggestions — port of Windows
// tests/test_hashing_suggest.py (suggest half), WITH the two bug fixes
// the Android contract requires:
//
// - «فصل دوازده» is chapter 12 (Windows bug: longest-first word numbers)
// - «هنرستان» does NOT suggest «هنر» (Windows bug: word-boundary subjects)
//
// Where the fix changes a pinned Windows quirk, the test pins the FIXED
// behaviour and says so.
import 'package:darspack/core/suggest.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('full case', () {
    expect(
      suggest('نمونه سوال ریاضی نهم فصل 3'),
      const Suggestion(
        subject: 'ریاضی',
        chapter: 3,
        kind: 'نمونه‌سوال',
        grade: 'نهم',
      ),
    );
  });

  test('word number and ZWNJ', () {
    // «علوم» alone is no longer a subject (canonical «علوم تجربی» only)
    final out = suggest('جزوه علوم فصل پنج');
    expect(out.chapter, 5);
    expect(out.kind, 'جزوه');
    expect(out.subject, isNull);

    final out2 = suggest('نمونه‌سوال عربی فصل ۷'); // ZWNJ + Persian digit
    expect(out2.kind, 'نمونه‌سوال');
    expect(out2.subject, 'عربی');
    expect(out2.chapter, 7);
  });

  test('no match returns all null', () {
    expect(suggest('IMG_20260101_1234'), const Suggestion());
  });

  test('Arabic letters still match', () {
    final out = suggest('كاربرگ فارسي'); // Arabic ك and ي
    expect(out.kind, 'کاربرگ');
    expect(out.subject, 'فارسی');
  });

  test('honors a custom subject list', () {
    expect(suggest('جزوه فیزیک فصل 2', subjects: ['فیزیک']).subject, 'فیزیک');
    expect(suggest('جزوه ریاضی فصل 2', subjects: ['فیزیک']).subject, isNull);
  });

  test('chapter boundaries', () {
    expect(suggest('تکلیف ریاضی فصل 40').chapter, 40); // MAX_CHAPTER edge
    expect(suggest('تکلیف ریاضی فصل 41').chapter, isNull); // above the bound
    expect(suggest('جزوه علوم فصل یازده').chapter, 11);
  });

  test('first kind hint wins', () {
    // «نمونه سوال» and «جزوه» both appear — نمونه سوال is checked first
    expect(suggest('نمونه سوال جزوه ریاضی').kind, 'نمونه‌سوال');
  });

  test('chapter 123 quirk kept: regex takes the first two digits', () {
    expect(suggest('جزوه ریاضی فصل 123').chapter, 12);
  });

  test('chapter zero stays zero', () {
    expect(suggest('جزوه ریاضی فصل 0').chapter, 0);
  });

  test('FIXED: فصل دوازده is chapter 12, not 2', () {
    expect(suggest('جزوه علوم فصل دوازده').chapter, 12);
    expect(suggest('کاربرگ عربی درس دوازده').lesson, 12);
  });

  test('FIXED: word numbers need a word boundary (فصل یکم is no chapter)', () {
    expect(suggest('جزوه ریاضی فصل یکم').chapter, isNull);
  });

  test('FIXED: هنرستان does NOT suggest هنر', () {
    expect(suggest('برنامه هنرستان').subject, isNull);
  });

  test('علوم تجربی wins (longest match first)', () {
    expect(suggest('جزوه علوم تجربی فصل 3').subject, 'علوم تجربی');
    expect(
      suggest(
        'جزوه علوم تجربی فصل 2',
        subjects: ['علوم', 'علوم تجربی'],
      ).subject,
      'علوم تجربی',
    );
  });

  test('lesson parsed separately from chapter', () {
    final out = suggest('فارسی درس 3');
    expect(out.lesson, 3);
    expect(out.chapter, isNull);
    final out2 = suggest('جزوه ریاضی درس دو فصل 5');
    expect(out2.lesson, 2);
    expect(out2.chapter, 5);
    expect(suggest('کاربرگ عربی درس سه').lesson, 3);
  });

  test('new kind keywords', () {
    for (final name in ['تست ریاضی', 'بانک سوال فیزیک', 'سوالات فصل 2']) {
      expect(suggest(name).kind, 'نمونه‌سوال', reason: name);
    }
    for (final name in [
      'مرور فصل 3',
      'جمع بندی علوم تجربی',
      'فرمول های ریاضی',
    ]) {
      expect(suggest(name).kind, 'جزوه', reason: name);
    }
  });

  test('grade hint', () {
    expect(suggest('نمونه سوال ریاضی هشتم').grade, 'هشتم');
    expect(suggest('کاربرگ هفتم').grade, 'هفتم');
    expect(suggest('جزوه بدون پایه').grade, isNull);
  });

  test('learned hints fire only at hits >= 2 and only when list misses', () {
    const learned = {
      'فیزیک': (subject: 'فیزیک', hits: 2),
      'شیمی': (subject: 'شیمی', hits: 1),
    };
    expect(suggest('جزوه فیزیک فصل 2', learned: learned).subject, 'فیزیک');
    expect(suggest('جزوه شیمی فصل 2', learned: learned).subject, isNull);
    // Fixed list wins over learned hints.
    expect(suggest('جزوه ریاضی فیزیک', learned: learned).subject, 'ریاضی');
  });

  test('default subjects are the 14 from the design', () {
    expect(defaultSubjects.length, 14);
    expect(DEFAULT_SUBJECTS, defaultSubjects);
    expect(defaultSubjects, contains('علوم تجربی'));
    expect(defaultSubjects, isNot(contains('علوم')));
  });
}
