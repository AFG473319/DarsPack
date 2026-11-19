// Backup & restore screen: create a full backup ZIP (manifest +
// files + catalog snapshot + index.html), restore one from a ZIP
// (the library keeps a safety copy first — see data layer), and
// verify a package's integrity.
import 'dart:io';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';

import '../app_state.dart';

class BackupScreen extends StatefulWidget {
  const BackupScreen({super.key});

  @override
  State<BackupScreen> createState() => _BackupScreenState();
}

class _BackupScreenState extends State<BackupScreen> {
  String? _lastBackup;
  String? _verifyResult;
  bool _busy = false;

  Future<void> _createBackup(AppState state) async {
    setState(() => _busy = true);
    try {
      final file = await state.library.exportBackup();
      setState(() => _lastBackup = file.path);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _restore(AppState state) async {
    final picked = await FilePicker.platform.pickFiles(
      type: FileType.custom,
      allowedExtensions: ['zip'],
    );
    if (picked == null || picked.files.first.path == null) return;
    setState(() => _busy = true);
    try {
      final results =
          await state.library.importPackage(File(picked.files.first.path!));
      final imported = results.where((r) => r.isImported).length;
      if (!mounted) return;
      setState(() => _verifyResult =
          '${state.t('pkg_imported')} ($imported)');
      await state.refresh();
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _verify(AppState state) async {
    final picked = await FilePicker.platform.pickFiles(
      type: FileType.custom,
      allowedExtensions: ['zip'],
    );
    if (picked == null || picked.files.first.path == null) return;
    setState(() => _busy = true);
    try {
      final report = await state.library
          .verifyPackage(File(picked.files.first.path!));
      if (!mounted) return;
      setState(() => _verifyResult = report.ok
          ? state.t('verify_ok')
          : '${state.t('verify_problems')}\n${report.problems.join('\n')}');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final state = AppStateScope.of(context);
    return Scaffold(
      appBar: AppBar(title: Text(state.t('btn_import_pkg'))),
      body: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(state.t('export_header_sub'),
                style: const TextStyle(color: Colors.grey)),
            const SizedBox(height: 16),
            FilledButton.icon(
              key: const ValueKey('backup_create'),
              onPressed: _busy ? null : () => _createBackup(state),
              icon: const Icon(Icons.backup),
              label: Text(state.t('btn_export')),
            ),
            if (_lastBackup != null) ...[
              const SizedBox(height: 8),
              SelectableText(_lastBackup!),
            ],
            const SizedBox(height: 12),
            OutlinedButton.icon(
              key: const ValueKey('backup_restore'),
              onPressed: _busy ? null : () => _restore(state),
              icon: const Icon(Icons.restore),
              label: Text(state.t('btn_import_pkg')),
            ),
            const SizedBox(height: 12),
            OutlinedButton.icon(
              key: const ValueKey('backup_verify'),
              onPressed: _busy ? null : () => _verify(state),
              icon: const Icon(Icons.verified),
              label: Text(state.t('btn_verify')),
            ),
            if (_busy) ...[
              const SizedBox(height: 16),
              const LinearProgressIndicator(),
            ],
            if (_verifyResult != null) ...[
              const SizedBox(height: 16),
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(12),
                  child: Text(_verifyResult!),
                ),
              ),
            ],
            const Spacer(),
            Text(
              state.t('settings_restart'),
              style: const TextStyle(color: Colors.grey, fontSize: 12),
            ),
          ],
        ),
      ),
    );
  }
}
