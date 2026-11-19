// Stats screen: total size, space saved by dedup, unclassified count,
// per-subject and per-kind breakdowns.
//
// The real Library.stats() returns a Map (no per-subject/per-kind
// breakdown), so per-subject comes from subjectsWithCounts() and
// per-kind is grouped from the file list here.
import 'package:darspack/core/core.dart';
import 'package:flutter/material.dart';

import '../app_state.dart';
import '../l10n/strings.dart';
import 'widgets.dart';

class StatsScreen extends StatelessWidget {
  const StatsScreen({super.key});

  Future<(Map<String, dynamic>, List<Subject>, List<LibraryFile>)>
      _load(AppState state) async {
    final stats = await state.library.stats();
    final subjects = await state.library.subjectsWithCounts();
    final files = await state.library.searchFiles();
    return (stats, subjects, files);
  }

  @override
  Widget build(BuildContext context) {
    final state = AppStateScope.of(context);
    return Scaffold(
      appBar: AppBar(title: Text(state.t('stats_title'))),
      body: FutureBuilder<(Map<String, dynamic>, List<Subject>, List<LibraryFile>)>(
        future: _load(state),
        builder: (context, snap) {
          if (snap.connectionState == ConnectionState.waiting) {
            return Center(child: Text(state.t('stats_computing')));
          }
          final data = snap.data;
          if (data == null) {
            return EmptyState(
                icon: Icons.bar_chart, title: state.t('stats_empty'));
          }
          final (stats, subjects, files) = data;
          final totalFiles = stats['totalFiles'] as int? ?? 0;
          if (totalFiles == 0) {
            return EmptyState(
                icon: Icons.bar_chart, title: state.t('stats_empty'));
          }
          final lang = state.language;
          final perKind = <String, int>{};
          for (final f in files) {
            final k = f.kind ?? 'سایر';
            perKind[k] = (perKind[k] ?? 0) + 1;
          }
          final maxSubject = subjects.fold<int>(
              0, (m, s) => s.fileCount > m ? s.fileCount : m);
          final maxKind = perKind.values.fold<int>(
              0, (m, v) => v > m ? v : m);
          return ListView(
            padding: const EdgeInsets.all(16),
            children: [
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(12),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                          '${state.t('stats_total')}: ${formatSize(stats['totalSizeBytes'] as int? ?? 0, lang)}'),
                      const SizedBox(height: 4),
                      Text(
                          '${state.t('stats_dedup')}: ${formatSize(stats['skippedBytes'] as int? ?? 0, lang)}'),
                      Text(state.t('stats_dedup_hint'),
                          style: const TextStyle(color: Colors.grey)),
                      const SizedBox(height: 4),
                      Text(
                          '${state.t('stats_unclassified')}: ${AppStrings.num(stats['unclassified'] as int? ?? 0, lang)}'),
                    ],
                  ),
                ),
              ),
              const SizedBox(height: 16),
              Text(state.t('stats_per_subject'),
                  style: const TextStyle(fontSize: 18)),
              const SizedBox(height: 8),
              ...subjects
                  .where((s) => s.fileCount > 0)
                  .map((s) => BarRow(
                      label: s.name,
                      value: s.fileCount,
                      max: maxSubject,
                      lang: lang)),
              const SizedBox(height: 16),
              Text(state.t('stats_per_kind'),
                  style: const TextStyle(fontSize: 18)),
              const SizedBox(height: 8),
              ...perKind.entries.map((e) => BarRow(
                  label: e.key, value: e.value, max: maxKind, lang: lang)),
            ],
          );
        },
      ),
    );
  }
}
