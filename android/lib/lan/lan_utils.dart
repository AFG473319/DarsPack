// Shared helpers for the LAN client + server (مشترک).
//
// Kept in one place so both directions agree on the wire rules:
// Persian digits, PIN comparison, inline-viewable types, upload cap.

/// Convert Persian / Arabic-Indic digits in [input] to Latin digits.
/// Latin digits pass through unchanged.
String latinDigits(String input) {
  const fa = '۰۱۲۳۴۵۶۷۸۹';
  const ar = '٠١٢٣٤٥٦٧٨٩';
  final out = StringBuffer();
  for (final ch in input.runes) {
    final c = String.fromCharCode(ch);
    final faIndex = fa.indexOf(c);
    if (faIndex >= 0) {
      out.write(faIndex);
      continue;
    }
    final arIndex = ar.indexOf(c);
    if (arIndex >= 0) {
      out.write(arIndex);
      continue;
    }
    out.write(c);
  }
  return out.toString();
}

/// Constant-time string equality (like Python's hmac.compare_digest),
/// so PIN timing cannot leak how many digits matched.
bool constantTimeEquals(String a, String b) {
  final aUnits = a.codeUnits;
  final bUnits = b.codeUnits;
  var diff = aUnits.length ^ bUnits.length;
  final n = aUnits.length < bUnits.length ? aUnits.length : bUnits.length;
  for (var i = 0; i < n; i++) {
    diff |= aUnits[i] ^ bUnits[i];
  }
  return diff == 0;
}

/// Extensions served inline in the browser, with a FIXED Content-Type.
/// Mirrors `_INLINE_TYPES` in the Windows server — never guess by MIME
/// (on Windows that consults the registry and differs per machine).
const Map<String, String> inlineContentTypes = {
  '.pdf': 'application/pdf',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.gif': 'image/gif',
  '.txt': 'text/plain; charset=utf-8',
};

/// Max upload size, both directions (Windows: MAX_UPLOAD).
const int maxUploadBytes = 200 * 1024 * 1024;

/// Wrong PIN 5 times -> the IP is locked out for 30 s (Windows rule).
const int maxPinFails = 5;
const int lockoutSeconds = 30;
