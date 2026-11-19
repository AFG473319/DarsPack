// Import screen: file_picker multi-pick, progress, per-file results
// (including duplicates naming the twin). After a successful import the
// user can open the classify sheet for the new files.
import 'dart:io';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';

import '../app_state.dart';
import 'classify_sheet.dart';
import 'package:darspack/core/core.dart';
import 'widgets.dart';

class ImportScreen extends StatefulWidget {
  const ImportScreen({super.key});

  @override
  State<ImportScreen> createState() => _ImportScreenState();
}

class _ImportScreenState extends State<ImportScreen> {
  bool _running = false;
  bool _keepDuplicates = false;
  List<ImportResult> _results = [];
  String _progress = '';

  Future<void> _pickAndImport() async {
    final state = AppStateScope.of(context);
    final picked = await FilePicker.platform.pickFiles(allowMultiple: true);
    if (picked == null || picked.files.isEmpty) return;
    final files = picked.files
        .where((f) => f.path != null)
        .map((f) => File(f.path!))
        .toList();
    if (files.isEmpty) return;
    setState(() {
      _running = true;
      _results = [];
    });
    final results = <ImportResult>[];
    for (var i = 0; i < files.length; i++) {
      setState(() {
        // «{}/{}: {}» — positional braces, filled left to right.
        _progress = state
            .t('import_running')
            .replaceFirst('{}', '${i + 1}')
            .replaceFirst('{}', '${files.length}')
            .replaceFirst('{}', files[i].path.split('/').last);
      });
      final r = await state.library.importFile(
        files[i],
        keepDuplicate: _keepDuplicates,
      );
      results.add(r);
      setState(() => _results = List.of(results));
    }
    await state.refresh();
    setState(() {
      _running = false;
      _progress = '';
    });
  }

  @override
  Widget build(BuildContext context) {
    final state = AppStateScope.of(context);
    final imported = _results.where((r) => r.isImported).toList();
    final dups = _results.where((r) => r.isDuplicate).length;
    final errs = _results.where((r) => r.status == 'error').length;
    return Scaffold(
      appBar: AppBar(title: Text(state.t('import_title'))),
      body: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(state.t('import_hint')),
            const SizedBox(height: 12),
            Row(
              children: [
                FilledButton.icon(
                  key: const ValueKey('import_pick'),
                  onPressed: _running ? null : _pickAndImport,
                  icon: const Icon(Icons.file_open),
                  label: Text(state.t('import_pick_files')),
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: CheckboxListTile(
                    value: _keepDuplicates,
                    onChanged: (v) =>
                        setState(() => _keepDuplicates = v ?? false),
                    title: Text(state.t('import_keep'),
                        style: const TextStyle(fontSize: 13)),
                    controlAffinity: ListTileControlAffinity.leading,
                    contentPadding: EdgeInsets.zero,
                  ),
                ),
              ],
            ),
            if (_running) ...[
              const SizedBox(height: 12),
              const LinearProgressIndicator(),
              const SizedBox(height: 4),
              Text(_progress),
            ],
            if (_results.isNotEmpty) ...[
              const SizedBox(height: 12),
              Text(
                // «{} فایل وارد شد · {} تکراری رد شد · {} خطا»
                state
                    .t('import_done')
                    .replaceFirst('{}', '${imported.length}')
                    .replaceFirst('{}', '$dups')
                    .replaceFirst('{}', '$errs'),
                style: const TextStyle(fontWeight: FontWeight.bold),
              ),
              Text(
                '✓ ${imported.length} · ⧉ $dups · ✗ $errs',
                style: const TextStyle(color: Colors.grey),
              ),
              const SizedBox(height: 8),
              if (imported.isNotEmpty)
                FilledButton(
                  key: const ValueKey('import_classify'),
                  onPressed: () async {
                    final files = <LibraryFile>[];
                    for (final r in imported) {
                      final f =
                          await state.library.getFile(r.fileId ?? -1);
                      if (f != null) files.add(f);
                    }
                    if (files.isEmpty || !context.mounted) return;
                    final saved = await showClassifySheet(
                        context, state, files);
                    // Saved here → pop with an empty list so the library
                    // screen does not offer the classify sheet a 2nd time.
                    if (saved == true && context.mounted) {
                      Navigator.pop(context, <ImportResult>[]);
                    }
                  },
                  child: Text(state.t('classify_title')),
                ),
            ],
            const SizedBox(height: 8),
            Expanded(
              child: _results.isEmpty
                  ? EmptyState(
                      icon: Icons.upload_file,
                      title: state.t('import_title'),
                      hint: state.t('import_hint'),
                    )
                  : ListView.builder(
                      itemCount: _results.length,
                      itemBuilder: (context, i) {
                        final r = _results[i];
                        final icon = r.isImported
                            ? Icons.check_circle
                            : r.isDuplicate
                                ? Icons.copy_all
                                : Icons.error;
                        final color = r.isImported
                            ? Colors.green
                            : r.isDuplicate
                                ? Colors.amber
                                : Colors.red;
                        return ListTile(
                          leading: Icon(icon, color: color),
                          title: Text(
                            r.fileId != null
                                ? '#${r.fileId}'
                                : state.t('import_title'),
                            maxLines: 1,
                          ),
                          subtitle: Text(r.messageFa),
                        );
                      },
                    ),
            ),
            Row(
              children: [
                TextButton(
                  onPressed: () => Navigator.pop(context, _results),
                  child: Text(state.t('close')),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}
