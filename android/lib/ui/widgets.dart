// Shared UI pieces: kind badge, file tile, small helpers.
import 'package:darspack/core/core.dart';
import 'package:flutter/material.dart';

import '../l10n/strings.dart';
import 'theme.dart';

/// File kinds, in Persian — stored as-is in both languages.
const List<String> kinds = ['جزوه', 'نمونه‌سوال', 'کاربرگ', 'تکلیف', 'سایر'];

/// «فصل ۳ · درس ۵» style display (empty when neither is set).
extension LibraryFileDisplay on LibraryFile {
  String get chapterLesson {
    final parts = <String>[];
    if (chapter != null) parts.add('فصل $chapter');
    if (lesson != null) parts.add('درس $lesson');
    return parts.join(' · ');
  }

  /// Kind for display (never null in the UI).
  String get kindOrOther => kind ?? 'سایر';
}

/// Human size: «۱۲٫۵ مگابایت» in fa, «12.5 MB» in en.
String formatSize(int bytes, String lang) {
  const unitsFa = ['بایت', 'کیلوبایت', 'مگابایت', 'گیگابایت'];
  const unitsEn = ['B', 'KB', 'MB', 'GB'];
  final units = lang == 'fa' ? unitsFa : unitsEn;
  double v = bytes.toDouble();
  var i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i++;
  }
  final num = v == v.truncateToDouble()
      ? v.truncate().toString()
      : v.toStringAsFixed(1);
  return '${lang == 'fa' ? persianDigits(num) : num} ${units[i]}';
}

/// Persian digits for a number in fa UI, Latin in en.
String faNum(Object value, String lang) => AppStrings.num(value, lang);

/// Small pill with the file kind (جزوه / نمونه‌سوال / کاربرگ / تکلیف / سایر).
class KindBadge extends StatelessWidget {
  final String kind;
  const KindBadge(this.kind, {super.key});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
      decoration: BoxDecoration(
        color: kindBadgeColor(kind),
        borderRadius: BorderRadius.circular(20),
      ),
      child: Text(
        kind,
        style: const TextStyle(fontSize: 11, color: AppColors.text),
      ),
    );
  }
}

/// One row in the file list: type icon + name + kind badge + chapter/lesson
/// + size. Tap opens, long-press starts multi-select.
class FileTile extends StatelessWidget {
  final LibraryFile file;
  final String lang;
  final bool selected;
  final VoidCallback? onTap;
  final VoidCallback? onLongPress;
  const FileTile({
    super.key,
    required this.file,
    required this.lang,
    this.selected = false,
    this.onTap,
    this.onLongPress,
  });

  @override
  Widget build(BuildContext context) {
    final sub = [
      if (file.subjectName != null) file.subjectName!,
      if (file.chapterLesson.isNotEmpty) file.chapterLesson,
    ].join(' · ');
    return ListTile(
      key: ValueKey('file_${file.id}'),
      selected: selected,
      selectedTileColor: AppColors.primary.withValues(alpha: 0.35),
      leading: CircleAvatar(
        backgroundColor: AppColors.surface2,
        foregroundColor: AppColors.accent,
        child: Icon(fileIcon(file.originalName)),
      ),
      title: Text(
        file.originalName,
        maxLines: 1,
        overflow: TextOverflow.ellipsis,
      ),
      subtitle: Row(
        children: [
          KindBadge(file.kindOrOther),
          const SizedBox(width: 6),
          Expanded(
            child: Text(
              sub.isEmpty ? AppStrings.t('unclassified', lang) : sub,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: const TextStyle(color: AppColors.muted, fontSize: 12),
            ),
          ),
          Text(
            formatSize(file.sizeBytes, lang),
            style: const TextStyle(color: AppColors.muted, fontSize: 12),
          ),
        ],
      ),
      trailing: selected
          ? const Icon(Icons.check_circle, color: AppColors.accent)
          : null,
      onTap: onTap,
      onLongPress: onLongPress,
    );
  }
}

/// Centered empty state (icon + title + optional hint).
class EmptyState extends StatelessWidget {
  final IconData icon;
  final String title;
  final String? hint;
  const EmptyState({super.key, required this.icon, required this.title, this.hint});

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(icon, size: 56, color: AppColors.faint),
            const SizedBox(height: 12),
            Text(title, textAlign: TextAlign.center,
                style: const TextStyle(fontSize: 16)),
            if (hint != null) ...[
              const SizedBox(height: 6),
              Text(hint!,
                  textAlign: TextAlign.center,
                  style: const TextStyle(color: AppColors.muted)),
            ],
          ],
        ),
      ),
    );
  }
}

/// Simple labelled bar row used by the stats screen.
class BarRow extends StatelessWidget {
  final String label;
  final int value;
  final int max;
  final String lang;
  const BarRow({super.key, required this.label, required this.value, required this.max, required this.lang});

  @override
  Widget build(BuildContext context) {
    final frac = max <= 0 ? 0.0 : value / max;
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(
        children: [
          SizedBox(width: 130, child: Text(label, maxLines: 1, overflow: TextOverflow.ellipsis)),
          Expanded(
            child: LinearProgressIndicator(
              value: frac,
              backgroundColor: AppColors.surface2,
              color: AppColors.accent,
              minHeight: 8,
              borderRadius: BorderRadius.circular(4),
            ),
          ),
          const SizedBox(width: 8),
          SizedBox(width: 36, child: Text(faNum(value, lang), textAlign: TextAlign.end)),
        ],
      ),
    );
  }
}
