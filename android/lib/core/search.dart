// Search over the catalog (جست‌وجو).
//
// Port of Windows `core/search.py`. Both the query and the stored names
// go through matchKey(), so «فصل ۳» finds «فصل 3», and «رياضي» (Arabic ي)
// finds «ریاضی». Matching covers the filename, the subject name, tags,
// the note and the kind — and a «فصل ۵»/«درس ۳» phrase also matches the
// structured chapter/lesson columns, so classified files are found even
// when their filename never mentions the word.
//
// Multi-token: the query's words are AND-ed together — every token must
// match *somewhere*. Ranking: a prefix match on the first token beats a
// contains match; ties break by recency.
//
// The SQL is built with positional `?` placeholders (sqflite-safe) and
// the pure pieces — tokenizing and SQL building — are testable without
// a database.

import 'package:sqflite/sqflite.dart';

import 'normalize.dart';
import 'suggest.dart';

/// One search token. [num] / [field] are set only for «فصل/درس N» phrases.
class SearchToken {
  const SearchToken(this.text, {this.num, this.field});

  final String text;
  final int? num;
  final String? field; // 'chapter' or 'lesson'

  @override
  String toString() => 'SearchToken($text, num: $num, field: $field)';
}

/// A built query: SQL text plus its positional arguments, in order.
class BuiltSearch {
  const BuiltSearch(this.sql, this.args);

  final String sql;
  final List<Object?> args;
}

// «فصل ۵» / «درس سه» become structured tokens: the number is matched
// against the chapter/lesson columns in addition to the text surfaces.
// Word numbers are tried longest-first so «دوازده» is never read as «دو».
final RegExp _phraseRe = RegExp(
  r'(فصل|درس)\s*(\d{1,2}|دوازده|یازده|ده|نه|هشت|هفت|شش|پنج|چهار|سه|دو|یک)'
  r'(?![\u0600-\u06FF])',
);

const int maxTokens = 8; // a real query never has more; pasting never hangs it
const int maxTokenLen = 64; // a pasted paragraph is not a search term

/// Split a normalized query into search tokens.
///
/// Phrases stay atomic («فصل 5» is one token, not two) and the list is
/// capped at [maxTokens].
List<SearchToken> tokenizeQuery(String query) {
  final key = matchKey(query);
  final out = <SearchToken>[];
  var pos = 0;

  void addPlain(String text) {
    for (final word in text.split(' ')) {
      if (word.isEmpty) continue;
      final clipped = word.length > maxTokenLen
          ? word.substring(0, maxTokenLen)
          : word;
      out.add(SearchToken(clipped));
    }
  }

  for (final m in _phraseRe.allMatches(key)) {
    addPlain(key.substring(pos, m.start));
    final number = m.group(2)!;
    final num = int.tryParse(number) ?? wordNumbers[number];
    final field = m.group(1) == 'فصل' ? 'chapter' : 'lesson';
    final text = m.group(0)!.trim();
    out.add(
      SearchToken(
        text.length > maxTokenLen ? text.substring(0, maxTokenLen) : text,
        num: num,
        field: field,
      ),
    );
    pos = m.end;
  }
  addPlain(key.substring(pos));
  return out.length > maxTokens ? out.sublist(0, maxTokens) : out;
}

String _escapeLike(String text) =>
    text.replaceAll('/', '//').replaceAll('%', '/%').replaceAll('_', '/_');

/// Build the search SQL (same shape as Windows `_BASE_SQL`) and its args.
///
/// The SELECT list mirrors the Windows one, plus the stored/internal
/// columns the Dart models need (stored_name, name_norm).
BuiltSearch buildSearchSql({
  String query = '',
  int? subjectId,
  String? kind,
  String? schoolYear,
  int limit = 200,
  bool unclassifiedOnly = false,
}) {
  final tokens = tokenizeQuery(query);
  final args = <Object?>[];
  final whereParts = <String>[];

  for (var i = 0; i < tokens.length; i++) {
    final tok = tokens[i];
    final like = '%${_escapeLike(tok.text)}%';
    args.addAll(List.filled(5, like));
    var clause =
        '(f.name_norm LIKE ? ESCAPE \'/\''
        ' OR s.normalized LIKE ? ESCAPE \'/\''
        ' OR f.note LIKE ? ESCAPE \'/\''
        ' OR f.kind LIKE ? ESCAPE \'/\''
        ' OR EXISTS (SELECT 1 FROM file_tags ftg'
        ' JOIN tags tgt ON tgt.id = ftg.tag_id'
        ' WHERE ftg.file_id = f.id AND tgt.normalized LIKE ? ESCAPE \'/\')';
    if (tok.num != null) {
      args.add(tok.num);
      clause += ' OR f.${tok.field} = ?';
    }
    clause += ')';
    whereParts.add(clause);
  }
  if (subjectId != null) {
    whereParts.add('f.subject_id = ?');
    args.add(subjectId);
  }
  if (unclassifiedOnly) {
    whereParts.add('f.subject_id IS NULL');
  }
  if (kind != null) {
    whereParts.add('f.kind = ?');
    args.add(kind);
  }
  if (schoolYear != null) {
    whereParts.add('f.school_year = ?');
    args.add(schoolYear);
  }

  String rank;
  if (tokens.isNotEmpty) {
    // Prefix rank on the FIRST token only — later tokens are filters,
    // not ranking signals.
    args.insert(0, '${_escapeLike(tokens[0].text)}%');
    rank = "CASE WHEN f.name_norm LIKE ? ESCAPE '/' THEN 0 ELSE 1 END";
  } else {
    rank = '0'; // empty query lists everything, newest first
  }
  if (whereParts.isEmpty) {
    whereParts.add('1'); // also covers the fresh-catalog case
  }

  final sql =
      '''
SELECT f.id, f.stored_name, f.original_name, f.name_norm,
       f.size_bytes, f.sha256, f.imported_at,
       f.subject_id, f.chapter, f.lesson, f.kind, f.school_year,
       f.note, f.available,
       s.name AS subject_name,
       $rank AS rank
FROM files f
LEFT JOIN subjects s ON s.id = f.subject_id
WHERE ${whereParts.join('\n  AND ')}
ORDER BY rank, f.imported_at DESC, f.id DESC
LIMIT ?
''';
  args.add(limit);
  return BuiltSearch(sql, args);
}

/// Run a search against [db] and return the raw rows.
///
/// `unclassifiedOnly` lists files still missing their subject — the
/// "finish your catalog" view.
Future<List<Map<String, Object?>>> searchDb(
  Database db, {
  String query = '',
  int? subjectId,
  String? kind,
  String? schoolYear,
  int limit = 200,
  bool unclassifiedOnly = false,
}) async {
  final built = buildSearchSql(
    query: query,
    subjectId: subjectId,
    kind: kind,
    schoolYear: schoolYear,
    limit: limit,
    unclassifiedOnly: unclassifiedOnly,
  );
  return db.rawQuery(built.sql, built.args);
}

/// How many files still have no subject (for the status bar nudge).
Future<int> unclassifiedCountDb(Database db) async {
  final rows = await db.rawQuery(
    'SELECT COUNT(*) AS c FROM files WHERE subject_id IS NULL',
  );
  return Sqflite.firstIntValue(rows) ?? 0;
}
