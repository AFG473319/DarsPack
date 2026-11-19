// File detail / edit sheet: note, tags, reclassify, delete → trash.
// Plus the bulk-edit sheet for multi-selected files.
import 'package:flutter/material.dart';
import 'package:open_filex/open_filex.dart';

import '../app_state.dart';
import 'package:darspack/core/core.dart';
import 'widgets.dart';

/// Detail + edit sheet for one file.
Future<void> showFileDetailSheet(
    BuildContext context, AppState state, LibraryFile file) {
  return showModalBottomSheet(
    context: context,
    isScrollControlled: true,
    builder: (_) => _FileDetailSheet(state: state, file: file),
  );
}

class _FileDetailSheet extends StatefulWidget {
  final AppState state;
  final LibraryFile file;
  const _FileDetailSheet({required this.state, required this.file});

  @override
  State<_FileDetailSheet> createState() => _FileDetailSheetState();
}

class _FileDetailSheetState extends State<_FileDetailSheet> {
  late String? _subject;
  late String _chapter;
  late String _lesson;
  late String _kind;
  late final TextEditingController _note;
  late final TextEditingController _tags;

  @override
  void initState() {
    super.initState();
    _subject = widget.file.subjectName;
    _chapter = widget.file.chapter?.toString() ?? '';
    _lesson = widget.file.lesson?.toString() ?? '';
    _kind = widget.file.kind ?? 'سایر';
    _note = TextEditingController(text: widget.file.note);
    _tags = TextEditingController(text: widget.file.tags.join('، '));
  }

  @override
  void dispose() {
    _note.dispose();
    _tags.dispose();
    super.dispose();
  }

  int? _subjectIdFor(String? name) {
    if (name == null) return null;
    for (final s in widget.state.subjects) {
      if (s.name == name) return s.id;
    }
    return null;
  }

  Future<void> _save() async {
    await widget.state.library.updateFileMeta(
      widget.file.id,
      subjectId: _subjectIdFor(_subject),
      chapter: int.tryParse(_chapter),
      lesson: int.tryParse(_lesson),
      kind: _kind,
      note: _note.text,
      tags: _tags.text
          .split(RegExp(r'[،,]'))
          .map((t) => t.trim())
          .where((t) => t.isNotEmpty)
          .toList(),
      clearSubject: _subject == null,
    );
    await widget.state.refresh();
    if (mounted) Navigator.pop(context);
  }

  Future<void> _delete() async {
    final messenger = ScaffoldMessenger.of(context);
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text(widget.state.t('delete_title')),
        content: Text(widget.state.t(
            'delete_confirm', {'name': widget.file.originalName})),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(ctx, false),
              child: Text(widget.state.t('cancel'))),
          TextButton(
              onPressed: () => Navigator.pop(ctx, true),
              child: Text(widget.state.t('btn_delete'))),
        ],
      ),
    );
    if (ok == true) {
      await widget.state.library.deleteFile(widget.file.id);
      await widget.state.refresh();
      if (!mounted) return;
      Navigator.pop(context);
      messenger.showSnackBar(SnackBar(
          content: Text(widget.state.t(
              'delete_done', {'name': widget.file.originalName}))));
    }
  }

  @override
  Widget build(BuildContext context) {
    final state = widget.state;
    final file = widget.file;
    final subjects = state.subjects.map((s) => s.name).toList();
    return Padding(
      padding: EdgeInsets.only(
        left: 16,
        right: 16,
        top: 16,
        bottom: MediaQuery.of(context).viewInsets.bottom + 16,
      ),
      child: SingleChildScrollView(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(file.originalName,
                style:
                    const TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
            const SizedBox(height: 4),
            Text(
              [
                if (file.subjectName != null) file.subjectName!,
                if (file.chapterLesson.isNotEmpty) file.chapterLesson,
                if (file.schoolYear != null) file.schoolYear!,
              ].join(' · '),
              style: const TextStyle(color: Colors.grey),
            ),
            const SizedBox(height: 12),
            DropdownButtonFormField<String?>(
              key: const ValueKey('detail_subject'),
              initialValue: _subject,
              decoration:
                  InputDecoration(labelText: state.t('meta_subject')),
              items: [
                DropdownMenuItem(
                    value: null, child: Text(state.t('unclassified'))),
                for (final s in subjects)
                  DropdownMenuItem(value: s, child: Text(s)),
              ],
              onChanged: (v) => setState(() => _subject = v),
            ),
            const SizedBox(height: 8),
            Row(
              children: [
                Expanded(
                  child: TextFormField(
                    initialValue: _chapter,
                    keyboardType: TextInputType.number,
                    decoration:
                        InputDecoration(labelText: state.t('col_chapter')),
                    onChanged: (v) => _chapter = v,
                  ),
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: TextFormField(
                    initialValue: _lesson,
                    keyboardType: TextInputType.number,
                    decoration:
                        InputDecoration(labelText: state.t('meta_lesson')),
                    onChanged: (v) => _lesson = v,
                  ),
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: DropdownButtonFormField<String>(
                    initialValue: _kind,
                    decoration:
                        InputDecoration(labelText: state.t('col_kind')),
                    items: [
                      for (final k in kinds)
                        DropdownMenuItem(value: k, child: Text(k)),
                    ],
                    onChanged: (v) => setState(() => _kind = v ?? 'سایر'),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 8),
            TextField(
              controller: _note,
              decoration: InputDecoration(
                labelText: state.t('meta_note'),
                hintText: state.t('meta_note_placeholder'),
              ),
              maxLines: 2,
            ),
            const SizedBox(height: 8),
            TextField(
              controller: _tags,
              decoration: InputDecoration(
                labelText: state.t('meta_tags_short'),
                hintText: state.t('meta_tags_placeholder'),
              ),
            ),
            const SizedBox(height: 16),
            Row(
              children: [
                IconButton(
                  key: const ValueKey('detail_open'),
                  icon: const Icon(Icons.open_in_new),
                  tooltip: state.t('menu_open'),
                  onPressed: () async {
                    final stored = state.library.storedFileFor(file);
                    if (await stored.exists()) {
                      await OpenFilex.open(stored.path);
                    }
                  },
                ),
                IconButton(
                  key: const ValueKey('detail_delete'),
                  icon: const Icon(Icons.delete, color: Colors.red),
                  tooltip: state.t('btn_delete'),
                  onPressed: _delete,
                ),
                const Spacer(),
                FilledButton(
                  key: const ValueKey('detail_save'),
                  onPressed: _save,
                  child: Text(state.t('btn_save')),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

/// Bulk-edit sheet: chosen values apply to all [ids]; fields left at
/// «بدون تغییر» are untouched.
Future<void> showBulkEditSheet(
    BuildContext context, AppState state, List<int> ids) {
  return showModalBottomSheet(
    context: context,
    isScrollControlled: true,
    builder: (_) => _BulkEditSheet(state: state, ids: ids),
  );
}

class _BulkEditSheet extends StatefulWidget {
  final AppState state;
  final List<int> ids;
  const _BulkEditSheet({required this.state, required this.ids});

  @override
  State<_BulkEditSheet> createState() => _BulkEditSheetState();
}

class _BulkEditSheetState extends State<_BulkEditSheet> {
  String? _subject; // null = no change
  String _chapter = '';
  String _lesson = '';
  String? _kind;

  int? _subjectIdFor(String? name) {
    if (name == null) return null;
    for (final s in widget.state.subjects) {
      if (s.name == name) return s.id;
    }
    return null;
  }

  Future<void> _save() async {
    final messenger = ScaffoldMessenger.of(context);
    for (final id in widget.ids) {
      await widget.state.library.updateFileMeta(
        id,
        subjectId: _subjectIdFor(_subject),
        chapter: _chapter.isEmpty ? null : int.tryParse(_chapter),
        lesson: _lesson.isEmpty ? null : int.tryParse(_lesson),
        kind: _kind,
      );
    }
    await widget.state.refresh();
    if (!mounted) return;
    Navigator.pop(context);
    messenger.showSnackBar(SnackBar(
        content: Text(widget.state.t('bulk_edit_done',
            {'count': widget.ids.length.toString()}))));
  }

  @override
  Widget build(BuildContext context) {
    final state = widget.state;
    final subjects = state.subjects.map((s) => s.name).toList();
    return Padding(
      padding: EdgeInsets.only(
        left: 16,
        right: 16,
        top: 16,
        bottom: MediaQuery.of(context).viewInsets.bottom + 16,
      ),
      child: SingleChildScrollView(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(state.t('bulk_edit_title'),
                style: const TextStyle(fontSize: 20)),
            const SizedBox(height: 4),
            Text(state.t('bulk_edit_hint',
                {'count': widget.ids.length.toString()})),
            const SizedBox(height: 12),
            DropdownButtonFormField<String?>(
              key: const ValueKey('bulk_subject'),
              initialValue: _subject,
              decoration:
                  InputDecoration(labelText: state.t('bulk_subject')),
              items: [
                DropdownMenuItem(
                    value: null, child: Text(state.t('bulk_none'))),
                for (final s in subjects)
                  DropdownMenuItem(value: s, child: Text(s)),
              ],
              onChanged: (v) => setState(() => _subject = v),
            ),
            const SizedBox(height: 8),
            Row(
              children: [
                Expanded(
                  child: TextFormField(
                    key: const ValueKey('bulk_chapter'),
                    keyboardType: TextInputType.number,
                    decoration: InputDecoration(
                        labelText: state.t('bulk_chapter')),
                    onChanged: (v) => _chapter = v,
                  ),
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: TextFormField(
                    key: const ValueKey('bulk_lesson'),
                    keyboardType: TextInputType.number,
                    decoration: InputDecoration(
                        labelText: state.t('bulk_lesson')),
                    onChanged: (v) => _lesson = v,
                  ),
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: DropdownButtonFormField<String?>(
                    key: const ValueKey('bulk_kind'),
                    initialValue: _kind,
                    decoration:
                        InputDecoration(labelText: state.t('bulk_kind')),
                    items: [
                      DropdownMenuItem(
                          value: null, child: Text(state.t('bulk_none'))),
                      for (final k in kinds)
                        DropdownMenuItem(value: k, child: Text(k)),
                    ],
                    onChanged: (v) => setState(() => _kind = v),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 16),
            Row(
              children: [
                TextButton(
                  onPressed: () => Navigator.pop(context),
                  child: Text(state.t('cancel')),
                ),
                const Spacer(),
                FilledButton(
                  key: const ValueKey('bulk_save'),
                  onPressed: _save,
                  child: Text(state.t('btn_save')),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}
