// Exam-night pack builder: pick a subject, optionally exam-related
// kinds only (نمونه‌سوال + جزوه), and export the matching files as one
// درس‌پک package.
import 'package:flutter/material.dart';

import '../app_state.dart';
import '../l10n/strings.dart';
import 'package:darspack/core/core.dart';

class ExamPackScreen extends StatefulWidget {
  const ExamPackScreen({super.key});

  @override
  State<ExamPackScreen> createState() => _ExamPackScreenState();
}

class _ExamPackScreenState extends State<ExamPackScreen> {
  int? _subjectId;
  bool _examKindsOnly = true;
  String? _done;

  List<LibraryFile> _matching(AppState state) {
    var files = state.files;
    if (_subjectId != null) {
      files = files.where((f) => f.subjectId == _subjectId).toList();
    }
    if (_examKindsOnly) {
      files = files
          .where((f) => f.kind == 'نمونه‌سوال' || f.kind == 'جزوه')
          .toList();
    }
    return files;
  }

  Future<void> _create(AppState state) async {
    final files = _matching(state);
    if (files.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(state.t('exam_pack_no_files'))));
      return;
    }
    final out =
        await state.library.exportPackage(files.map((f) => f.id).toList());
    setState(() => _done = state.t('exam_pack_done',
        {'0': AppStrings.num(files.length, state.language)}));
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('${state.t('exam_pack_done', {
          '0': AppStrings.num(files.length, state.language),
        })} — ${out.path.split('/').last}')));
  }

  @override
  Widget build(BuildContext context) {
    final state = AppStateScope.of(context);
    final matching = _matching(state);
    final totalSize =
        matching.fold<int>(0, (sum, f) => sum + f.sizeBytes);
    return Scaffold(
      appBar: AppBar(title: Text(state.t('btn_exam_pack'))),
      body: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(state.t('exam_pack_subject')),
            const SizedBox(height: 8),
            DropdownButtonFormField<int?>(
              key: const ValueKey('exam_subject'),
              initialValue: _subjectId,
              items: [
                DropdownMenuItem(
                    value: null, child: Text(state.t('all_subjects'))),
                for (final s in state.subjects)
                  DropdownMenuItem(value: s.id, child: Text(s.name)),
              ],
              onChanged: (v) => setState(() => _subjectId = v),
            ),
            CheckboxListTile(
              value: _examKindsOnly,
              onChanged: (v) =>
                  setState(() => _examKindsOnly = v ?? true),
              title: Text(state.t('exam_pack_filter_kinds')),
              controlAffinity: ListTileControlAffinity.leading,
              contentPadding: EdgeInsets.zero,
            ),
            const SizedBox(height: 8),
            Text(state.t('exam_pack_summary_count', {
              '0': AppStrings.num(matching.length, state.language),
              '1': totalSize < 1024 * 1024
                  ? '${AppStrings.num(totalSize ~/ 1024, state.language)} KB'
                  : '${AppStrings.num((totalSize / (1024 * 1024)).toStringAsFixed(1), state.language)} MB',
            })),
            const SizedBox(height: 16),
            FilledButton.icon(
              key: const ValueKey('exam_create'),
              onPressed: () => _create(state),
              icon: const Icon(Icons.school),
              label: Text(state.t('exam_pack_btn_create')),
            ),
            if (_done != null) ...[
              const SizedBox(height: 16),
              Card(
                  child: Padding(
                      padding: const EdgeInsets.all(12),
                      child: Text(_done!))),
            ],
          ],
        ),
      ),
    );
  }
}
