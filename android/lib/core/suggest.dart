// Metadata suggestions from Persian filenames (پیشنهاد فراداده).
//
// Port of Windows `core/suggest.py`, with the two known Windows bugs
// FIXED (per the data-layer contract):
// - word numbers are tried longest-first, so «فصل دوازده» is chapter 12,
//   never chapter 2;
// - subject matching is word-boundary based, so «هنرستان» does NOT
//   suggest «هنر» (a subject's words must appear as whole words, in
//   order, in the filename).
//
// Suggestions are *shown for review* in the import dialog; nothing is
// applied silently.

import 'package:sqflite/sqflite.dart';

import 'database.dart';
import 'normalize.dart';

/// One filename suggestion: every value may be null.
class Suggestion {
  const Suggestion({
    this.subject,
    this.chapter,
    this.lesson,
    this.kind,
    this.grade,
  });

  final String? subject;
  final int? chapter;
  final int? lesson;
  final String? kind;
  final String? grade;

  @override
  bool operator ==(Object other) =>
      other is Suggestion &&
      subject == other.subject &&
      chapter == other.chapter &&
      lesson == other.lesson &&
      kind == other.kind &&
      grade == other.grade;

  @override
  int get hashCode => Object.hash(subject, chapter, lesson, kind, grade);

  @override
  String toString() =>
      'Suggestion(subject: $subject, chapter: $chapter, lesson: $lesson, '
      'kind: $kind, grade: $grade)';
}

/// Default subject list (فهرست دروس دوره اول متوسطه).
/// The canonical science subject is «علوم تجربی» (the official textbook
/// name): the bare «علوم» entry is gone so the two can never fight over
/// the same filename.
const List<String> defaultSubjects = [
  'ریاضی',
  'علوم تجربی',
  'فارسی',
  'عربی',
  'دینی',
  'انگلیسی',
  'مطالعات اجتماعی',
  'هنر',
  'کار و فناوری',
  'تربیت بدنی',
  'آمادگی دفاعی',
  'سلامت و بهداشت',
  'تفکر و سبک زندگی',
  'کارگاه',
];

/// Backwards-compatible alias (the task spec calls it DEFAULT_SUBJECTS).
// ignore: constant_identifier_names
const List<String> DEFAULT_SUBJECTS = defaultSubjects;

// Keyword → file kind (نوع فایل). Keys are matched after normalization,
// so «نمونه‌سوال» with a half-space also matches the «نمونه سوال» key.
// Dart maps preserve insertion order: the FIRST matching hint wins,
// exactly like the Windows dict (نمونه سوال is checked before جزوه).
const Map<String, String> _kindHints = {
  'نمونه سوال': 'نمونه‌سوال',
  'نمونه سوالات': 'نمونه‌سوال',
  'امتحان': 'نمونه‌سوال',
  'آزمون': 'نمونه‌سوال',
  'بانک سوال': 'نمونه‌سوال',
  'سوالات': 'نمونه‌سوال',
  'سوال': 'نمونه‌سوال',
  'تست': 'نمونه‌سوال',
  'جزوه': 'جزوه',
  'خلاصه': 'جزوه',
  'جزوات': 'جزوه',
  'مرور': 'جزوه',
  'جمع بندی': 'جزوه',
  'فرمول': 'جزوه',
  'کاربرگ': 'کاربرگ',
  'ورقه': 'کاربرگ',
  'تکلیف': 'تکلیف',
  'تمرین': 'تکلیف',
  'پروژه': 'تکلیف',
  'مشی': 'تکلیف',
};

/// «فصل سه» style chapter words (school books have up to 12+ chapters).
/// Sorted longest-first when matching so «دوازده» is never read as «دو».
const Map<String, int> wordNumbers = {
  'یک': 1,
  'دو': 2,
  'سه': 3,
  'چهار': 4,
  'پنج': 5,
  'شش': 6,
  'هفت': 7,
  'هشت': 8,
  'نه': 9,
  'ده': 10,
  'یازده': 11,
  'دوازده': 12,
};

/// Longest word first — the fix for «فصل دوازده» reading as chapter 2.
final List<MapEntry<String, int>> _wordNumbersLongestFirst = () {
  final entries = wordNumbers.entries.toList();
  entries.sort((a, b) => b.key.length.compareTo(a.key.length));
  return entries;
}();

final RegExp _chapterDigitRe = RegExp(r'فصل\s*([0-9]{1,2})');
final RegExp _lessonDigitRe = RegExp(r'درس\s*([0-9]{1,2})');
const int maxChapter =
    40; // sanity bound — anything larger is not a school chapter

/// Grade words in filenames («نمونه سوال ریاضی نهم»); a display hint only.
const List<String> _grades = ['نهم', 'هشتم', 'هفتم'];

/// One learned token→subject vote, as returned by [loadHints].
typedef LearnedHint = ({String subject, int hits});

bool _subjectWordsMatch(List<String> keyWords, String subject) {
  final subjectWords = matchKey(subject).split(' ');
  if (subjectWords.isEmpty || subjectWords.length > keyWords.length) {
    return false;
  }
  // The subject's words must appear as a contiguous run of whole words.
  for (var start = 0; start <= keyWords.length - subjectWords.length; start++) {
    var ok = true;
    for (var i = 0; i < subjectWords.length; i++) {
      if (keyWords[start + i] != subjectWords[i]) {
        ok = false;
        break;
      }
    }
    if (ok) return true;
  }
  return false;
}

int? _numberAfter(List<String> words, String marker) {
  for (var i = 0; i < words.length - 1; i++) {
    if (words[i] != marker) continue;
    final next = words[i + 1];
    final digit = int.tryParse(next);
    if (digit != null) return digit;
    for (final entry in _wordNumbersLongestFirst) {
      if (next == entry.key) return entry.value;
    }
    return null;
  }
  return null;
}

/// Suggest subject / chapter / lesson / kind / grade from a filename stem.
///
/// The stem carries no extension. Every value may be null. The importer
/// turns subject names into ids; here we keep it string-based so the
/// function is trivially testable.
///
/// [learned] (optional): {token: (subject, hits)} from the hint_rules
/// table — a class-specific memory consulted only when the fixed subject
/// list misses, and only at hits >= 2. Pre-fill only.
Suggestion suggest(
  String filenameStem, {
  List<String>? subjects,
  Map<String, LearnedHint>? learned,
}) {
  final key = matchKey(latinDigits(filenameStem));
  final keyWords = key.isEmpty ? <String>[] : key.split(' ');

  String? subject;
  int? chapter;
  int? lesson;
  String? kind;
  String? grade;

  // Longest match first: «علوم تجربی» must beat any shorter overlap, and
  // a custom subject list gets the same courtesy.
  final candidates = List<String>.of(subjects ?? defaultSubjects)
    ..sort((a, b) => matchKey(b).length.compareTo(matchKey(a).length));
  for (final subj in candidates) {
    if (_subjectWordsMatch(keyWords, subj)) {
      subject = subj;
      break;
    }
  }

  final chapterDigit = _chapterDigitRe.firstMatch(key);
  if (chapterDigit != null && int.parse(chapterDigit.group(1)!) <= maxChapter) {
    chapter = int.parse(chapterDigit.group(1)!);
  } else {
    final n = _numberAfter(keyWords, 'فصل');
    if (n != null && n <= maxChapter) chapter = n;
  }

  final lessonDigit = _lessonDigitRe.firstMatch(key);
  if (lessonDigit != null && int.parse(lessonDigit.group(1)!) <= maxChapter) {
    lesson = int.parse(lessonDigit.group(1)!);
  } else {
    final n = _numberAfter(keyWords, 'درس');
    if (n != null && n <= maxChapter) lesson = n;
  }

  for (final entry in _kindHints.entries) {
    if (key.contains(matchKey(entry.key))) {
      kind = entry.value;
      break;
    }
  }

  for (final g in _grades) {
    if (key.contains(g)) {
      grade = g;
      break;
    }
  }

  // Learned token→subject memory (pre-fill only, like everything here).
  // Fires only when the fixed list missed and the class has confirmed
  // the same token → subject at least twice.
  if (subject == null && learned != null) {
    for (final token in keyWords) {
      final entry = learned[token];
      if (entry != null && token.length >= 3 && entry.hits >= 2) {
        subject = entry.subject;
        break;
      }
    }
  }

  return Suggestion(
    subject: subject,
    chapter: chapter,
    lesson: lesson,
    kind: kind,
    grade: grade,
  );
}

// --- Learned-hint store (hint_rules table) -------------------------------
// The classify dialog's save path calls [learnHint] once per saved file;
// [suggest] consumes the table via [loadHints]. Pre-fill only — nothing
// here ever touches a file's stored subject.

/// Record/refresh one token→subject vote from a confirmed save.
Future<void> learnHint(Database db, String token, String subjectName) async {
  final key = matchKey(token);
  if (key.length < 3) return;
  final subjectId = await getOrCreate(db, 'subjects', subjectName);
  if (subjectId == null) return;
  final now = DateTime.now().toIso8601String().substring(0, 19);
  await db.rawInsert(
    'INSERT INTO hint_rules(token, subject_id, hits, last_used) '
    'VALUES (?, ?, 1, ?) '
    'ON CONFLICT(token) DO UPDATE SET '
    'hits = hits + 1, subject_id = excluded.subject_id, '
    'last_used = excluded.last_used',
    [key, subjectId, now],
  );
}

/// Delete one learned rule (the user changed their mind).
Future<void> forgetHint(Database db, String token) async {
  await db.delete(
    'hint_rules',
    where: 'token = ?',
    whereArgs: [matchKey(token)],
  );
}

/// All learned rules as {token: (subject, hits)} for [suggest].
Future<Map<String, LearnedHint>> loadHints(Database db) async {
  final rows = await db.rawQuery(
    'SELECT h.token, h.hits, s.name AS subject '
    'FROM hint_rules h JOIN subjects s ON s.id = h.subject_id',
  );
  return {
    for (final row in rows)
      row['token'] as String: (
        subject: row['subject'] as String,
        hits: row['hits'] as int,
      ),
  };
}
