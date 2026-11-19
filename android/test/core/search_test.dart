// Tests for search tokenizing and SQL building — the pure half of
// Windows tests/test_search.py. DB-backed search behaviour (matching,
// ranking, filters) lives in database_test.dart and is skipped here:
// sqflite has no Linux-desktop engine, so it cannot run under
// `flutter test` on this VM (see that file).
import 'package:darspack/core/search.dart';
import 'package:flutter_test/flutter_test.dart';

int placeholderCount(String sql) => '?'.allMatches(sql).length;

void main() {
  test('فصل 3 and فصل ۳ tokenize identically', () {
    expect(tokenizeQuery('فصل 3').map((t) => t.text), ['فصل 3']);
    expect(tokenizeQuery('فصل ۳').map((t) => t.text), ['فصل 3']);
    final t = tokenizeQuery('فصل 3').single;
    expect(t.num, 3);
    expect(t.field, 'chapter');
  });

  test('word-number phrases are structured tokens (longest-first)', () {
    final t = tokenizeQuery('فصل دوازده').single;
    expect(t.num, 12);
    expect(t.field, 'chapter');
    expect(tokenizeQuery('فصل دو').single.num, 2);
    expect(tokenizeQuery('درس سه').single.num, 3);
    expect(tokenizeQuery('درس 3').single.field, 'lesson');
  });

  test('فصل and درس target their own columns', () {
    expect(tokenizeQuery('فصل 3').single.field, 'chapter');
    expect(tokenizeQuery('درس 3').single.field, 'lesson');
  });

  test('phrases stay atomic; plain words split', () {
    final tokens = tokenizeQuery('ریاضی نمونه سوال فصل ۵');
    expect(tokens.map((t) => t.text), ['ریاضی', 'نمونه', 'سوال', 'فصل 5']);
    expect(tokens.last.num, 5);
  });

  test('token order does not matter for the token list', () {
    expect(tokenizeQuery('ریاضی نمونه سوال').map((t) => t.text), [
      'ریاضی',
      'نمونه',
      'سوال',
    ]);
    expect(tokenizeQuery('نمونه سوال ریاضی').map((t) => t.text), [
      'نمونه',
      'سوال',
      'ریاضی',
    ]);
  });

  test('query is capped at 8 tokens', () {
    expect(tokenizeQuery('کلمه ' * 50).length, 8);
    expect(tokenizeQuery('ریاضی ' * 20).length, 8);
  });

  test('empty / whitespace query has no tokens', () {
    expect(tokenizeQuery(''), isEmpty);
    expect(tokenizeQuery('   '), isEmpty);
  });

  test('Arabic ي matches Persian ی after normalization', () {
    expect(
      tokenizeQuery('رياضي').map((t) => t.text),
      tokenizeQuery('ریاضی').map((t) => t.text),
    );
  });

  test('ZWNJ query normalizes to spaced tokens', () {
    expect(tokenizeQuery('نمونه‌سوال').map((t) => t.text), ['نمونه', 'سوال']);
  });

  test('built SQL: placeholders always match args', () {
    final cases = [
      buildSearchSql(),
      buildSearchSql(query: 'ریاضی'),
      buildSearchSql(query: 'ریاضی نمونه سوال فصل ۵'),
      buildSearchSql(query: 'فصل 3', subjectId: 2, kind: 'جزوه'),
      buildSearchSql(query: '', unclassifiedOnly: true, limit: 2),
      buildSearchSql(query: 'درس 3', schoolYear: '1404-1405'),
      buildSearchSql(query: '100%_x'), // LIKE wildcards in the query
    ];
    for (final built in cases) {
      expect(
        placeholderCount(built.sql),
        built.args.length,
        reason: 'SQL: ${built.sql}\nargs: ${built.args}',
      );
    }
  });

  test('built SQL: empty query lists everything, newest first', () {
    final built = buildSearchSql(query: '');
    expect(built.sql, contains('ORDER BY rank, f.imported_at DESC'));
    expect(built.sql, contains('WHERE 1'));
    expect(built.args, [200]); // only the limit
  });

  test('built SQL: first-token prefix rank, filters as AND clauses', () {
    final built = buildSearchSql(
      query: 'جزوه',
      subjectId: 3,
      kind: 'جزوه',
      schoolYear: '1405-1406',
      unclassifiedOnly: false,
    );
    expect(built.sql, contains('CASE WHEN f.name_norm LIKE ?'));
    expect(built.sql, contains('f.subject_id = ?'));
    expect(built.sql, contains("f.kind = ?"));
    expect(built.sql, contains('f.school_year = ?'));
    expect(built.args.first, 'جزوه%'); // prefix arg comes first
    expect(built.args.last, 200);
  });

  test('built SQL: unclassified filter', () {
    final built = buildSearchSql(query: '', unclassifiedOnly: true);
    expect(built.sql, contains('f.subject_id IS NULL'));
  });

  test('built SQL: LIKE wildcards in the query are escaped', () {
    final built = buildSearchSql(query: '100%_x');
    // The LIKE pattern must escape % and _ so they match literally.
    expect(built.args.any((a) => (a as String).contains('/%')), isTrue);
    expect(built.args.any((a) => (a as String).contains('/_')), isTrue);
  });

  test('built SQL: فصل phrase adds a structured chapter clause', () {
    final built = buildSearchSql(query: 'فصل 5');
    expect(built.sql, contains('OR f.chapter = ?'));
    expect(built.args, contains(5));
    final lesson = buildSearchSql(query: 'درس 3');
    expect(lesson.sql, contains('OR f.lesson = ?'));
    expect(lesson.sql, isNot(contains('f.chapter = ?')));
  });

  test('built SQL: limit is honored', () {
    expect(buildSearchSql(query: '', limit: 2).args.last, 2);
  });
}
