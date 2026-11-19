// Classify sheet (after import): per file, subject / chapter / lesson /
// kind pre-filled from suggestions (core suggest() on the filename
// stem, plus learned hints). The subject is NEVER pre-applied as
// stored data — it is only a suggested choice the user confirms; files
// left without a subject stay in «بدون درس».
import 'package:darspack/core/core.dart';
import 'package:flutter/material.dart';

import '../app_state.dart';
import 'widgets.dart';

/// Shows the classify sheet for freshly imported [files]; returns true
/// when the user saved (not "later").
Future<bool?> showClassifySheet(
    BuildContext context, AppState state, List<LibraryFile> files) {
  return showModalBottomSheet<bool>(
    context: context,
    isScrollControlled: true,
    backgroundColor: Theme.of(context).colorScheme.surface,
    builder: (_) => ClassifySheet(state: state, files: files),
  );
}

class ClassifySheet extends StatefulWidget {
  final AppState state;
  final List<LibraryFile> files;
  const ClassifySheet({super.key, required this.state, required this.files});

  @override
  State<ClassifySheet> createState() => _ClassifySheetState();
}

class _ClassifySheetState extends State<ClassifySheet> {
  List<_Row>? _rows;

  @override
  void initState() {
    super.initState();
    _initRows();
  }

  Future<void> _initRows() async {
    final learned = await widget.state.library.loadHints();
    if (!mounted) return;
    setState(() {
      _rows = widget.files.map((f) {
        final stem = f.originalName.contains('.')
            ? f.originalName.substring(0, f.originalName.lastIndexOf('.'))
            : f.originalName;
        final s = suggest(stem, learned: learned);
        return _Row(
          file: f,
          // Subject suggestion only — never stored until the user saves.
          subject: s.subject,
          chapter: (f.chapter ?? s.chapter)?.toString() ?? '',
          lesson: (f.lesson ?? s.lesson)?.toString() ?? '',
          kind: f.kind ?? s.kind ?? 'سایر',
        );
      }).toList();
    });
  }

  int? _subjectIdFor(String? name) {
    if (name == null) return null;
    for (final s in widget.state.subjects) {
      if (s.name == name) return s.id;
    }
    return null;
  }

  Future<void> _save() async {
    final rows = _rows;
    if (rows == null) return;
    for (final row in rows) {
      await widget.state.library.updateFileMeta(
        row.file.id,
        subjectId: _subjectIdFor(row.subject),
        chapter: int.tryParse(row.chapter),
        lesson: int.tryParse(row.lesson),
        kind: row.kind,
        clearSubject: row.subject == null,
      );
    }
    await widget.state.refresh();
    if (mounted) Navigator.pop(context, true);
  }

  void _applyFirstToAll() {
    final rows = _rows;
    if (rows == null || rows.isEmpty) return;
    final first = rows.first;
    setState(() {
      for (final r in rows.skip(1)) {
        r.subject = first.subject;
        r.chapter = first.chapter;
        r.lesson = first.lesson;
        r.kind = first.kind;
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    final state = widget.state;
    final subjects = state.subjects.map((s) => s.name).toList();
    final rows = _rows;
    return DraggableScrollableSheet(
      expand: false,
      initialChildSize: 0.85,
      builder: (context, scroll) => Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(state.t('classify_title'),
                style: const TextStyle(fontSize: 20)),
            const SizedBox(height: 4),
            Text(state.t('classify_hint'),
                style: const TextStyle(color: Colors.grey)),
            const SizedBox(height: 8),
            if (rows != null && rows.length > 1)
              Row(
                children: [
                  Text(state.t('bulk_caption')),
                  const SizedBox(width: 8),
                  OutlinedButton(
                    key: const ValueKey('classify_apply_first'),
                    onPressed: _applyFirstToAll,
                    child: Text(state.t('bulk_edit_menu')),
                  ),
                ],
              ),
            const SizedBox(height: 8),
            Expanded(
              child: rows == null
                  ? const Center(child: CircularProgressIndicator())
                  : ListView.builder(
                      controller: scroll,
                      itemCount: rows.length,
                      itemBuilder: (context, i) =>
                          _rowCard(rows[i], subjects, state),
                    ),
            ),
            Row(
              children: [
                TextButton(
                  key: const ValueKey('classify_later'),
                  onPressed: () => Navigator.pop(context, false),
                  child: Text(state.t('classify_later')),
                ),
                const Spacer(),
                FilledButton(
                  key: const ValueKey('classify_save'),
                  onPressed: _save,
                  child: Text(state.t('classify_save')),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  Widget _rowCard(_Row row, List<String> subjects, AppState state) {
    return Card(
      margin: const EdgeInsets.symmetric(vertical: 6),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              row.file.originalName,
              style: const TextStyle(fontWeight: FontWeight.bold),
            ),
            const SizedBox(height: 8),
            DropdownButtonFormField<String?>(
              initialValue: row.subject,
              decoration: InputDecoration(labelText: state.t('meta_subject')),
              items: [
                DropdownMenuItem(
                    value: null, child: Text(state.t('unclassified'))),
                for (final s in subjects)
                  DropdownMenuItem(value: s, child: Text(s)),
              ],
              onChanged: (v) => setState(() => row.subject = v),
            ),
            const SizedBox(height: 8),
            Row(
              children: [
                Expanded(
                  child: TextFormField(
                    initialValue: row.chapter,
                    keyboardType: TextInputType.number,
                    decoration:
                        InputDecoration(labelText: state.t('col_chapter')),
                    onChanged: (v) => row.chapter = v,
                  ),
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: TextFormField(
                    initialValue: row.lesson,
                    keyboardType: TextInputType.number,
                    decoration:
                        InputDecoration(labelText: state.t('meta_lesson')),
                    onChanged: (v) => row.lesson = v,
                  ),
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: DropdownButtonFormField<String>(
                    initialValue: row.kind,
                    decoration:
                        InputDecoration(labelText: state.t('col_kind')),
                    items: [
                      for (final k in kinds)
                        DropdownMenuItem(value: k, child: Text(k)),
                    ],
                    onChanged: (v) =>
                        setState(() => row.kind = v ?? 'سایر'),
                  ),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class _Row {
  final LibraryFile file;
  String? subject;
  String chapter;
  String lesson;
  String kind;
  _Row({
    required this.file,
    this.subject,
    this.chapter = '',
    this.lesson = '',
    this.kind = 'سایر',
  });
}
