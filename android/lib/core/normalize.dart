// Persian text normalization (نرمال‌سازی متن فارسی).
//
// Port of Windows `core/normalize.py`. Display keeps the user's original
// text exactly as typed; these helpers build *match keys* instead — used
// for search and for comparing file names — so that typing style never
// changes what matches:
//
// - Arabic ي/ك become Persian ی/ک (typing «رياضي» finds «ریاضی»)
// - Arabic and Persian digits become Latin digits («فصل ۳» matches «فصل 3»)
// - diacritics (اعراب) and tatweel are removed
// - ZWNJ (نیم‌فاصله) is treated as a space, so «نمونه‌سوال» matches «نمونه سوال»
// - whitespace collapses to single spaces

// Arabic letters commonly mistyped for their Persian equivalents.
const Map<String, String> _arToFa = {'ي': 'ی', 'ك': 'ک', 'ۀ': 'ه', 'ة': 'ه'};

// All ten Persian and Arabic-Indic digits → ASCII 0-9.
const String _persianDigits = '۰۱۲۳۴۵۶۷۸۹';
const String _arabicDigits = '٠١٢٣٤٥٦٧٨٩';
const String _latinDigits = '0123456789';

// Combining marks (fatha, kasra, sukun, …) and tatweel (کشیده).
final RegExp _diacritics = RegExp(r'[\u064B-\u065F\u0670\u0640]');
final RegExp _spaces = RegExp(r'\s+');
const String zwnj = '\u200c';

String _translateDigits(String text, String from, String to) {
  final buffer = StringBuffer();
  for (var i = 0; i < text.length; i++) {
    final ch = text[i];
    final idx = from.indexOf(ch);
    buffer.write(idx >= 0 ? to[idx] : ch);
  }
  return buffer.toString();
}

/// Convert Persian/Arabic digits to Latin digits.
String latinDigits(String? text) {
  if (text == null || text.isEmpty) return '';
  var out = _translateDigits(text, _persianDigits, _latinDigits);
  return _translateDigits(out, _arabicDigits, _latinDigits);
}

/// Convert Latin digits to Persian digits (for UI display).
String persianDigits(String? text) {
  if (text == null || text.isEmpty) return '';
  return _translateDigits(text, _latinDigits, _persianDigits);
}

/// Canonical form used for matching keys (see module docstring).
String normalize(String? text) {
  if (text == null || text.isEmpty) return '';
  var out = text;
  for (final entry in _arToFa.entries) {
    out = out.replaceAll(entry.key, entry.value);
  }
  out = latinDigits(out);
  out = out.replaceAll(zwnj, ' ');
  out = out.replaceAll(_diacritics, '');
  return out.replaceAll(_spaces, ' ').trim();
}

/// normalize + casefold — the key for names, tags, subjects, queries.
String matchKey(String? text) => normalize(text).toLowerCase();
