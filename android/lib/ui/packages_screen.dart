// Packages screen: export a درس‌پک package (selected files or the
// current filter results), verify a package, import a package.
// After an export, the just-made file can be verified with one tap
// (no picker needed) — that also drives the verify-report screenshot.
import 'dart:io';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';

import '../app_state.dart';
import '../l10n/strings.dart';
import 'package:darspack/core/core.dart';
import 'package:darspack/core/manifest.dart' as manifest;

class PackagesScreen extends StatefulWidget {
  const PackagesScreen({super.key});

  @override
  State<PackagesScreen> createState() => _PackagesScreenState();
}

class _PackagesScreenState extends State<PackagesScreen> {
  String? _lastExport;
  VerifyReport? _lastReport;
  String? _lastReportName;
  int _lastChecked = 0;
  String? _importNote;
  bool _busy = false;

  Future<void> _export(AppState state) async {
    setState(() => _busy = true);
    try {
      final ids = state.selected.isNotEmpty
          ? state.selected.toList()
          : state.files.map((f) => f.id).toList();
      final file = await state.library.exportPackage(ids);
      setState(() {
        _lastExport = file.path;
        _lastReport = null;
        _importNote = state
            .t('export_done')
            .replaceFirst('{}', AppStrings.num(ids.length, state.language))
            .replaceFirst('{}', file.path.split('/').last);
      });
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _verifyLast(AppState state) async {
    if (_lastExport == null) return;
    setState(() => _busy = true);
    try {
      final file = File(_lastExport!);
      final report = await state.library.verifyPackage(file);
      final count = await _manifestCount(file);
      setState(() {
        _lastReport = report;
        _lastReportName = _lastExport!.split('/').last;
        _lastChecked = count;
      });
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  /// Manifest entry count for the «N files checked» line (0 if unreadable).
  Future<int> _manifestCount(File file) async {
    try {
      return (await manifest.readManifest(file)).length;
    } catch (_) {
      return 0;
    }
  }

  Future<void> _verifyPicked(AppState state) async {
    final picked = await FilePicker.platform.pickFiles(
      type: FileType.custom,
      allowedExtensions: ['zip'],
    );
    if (picked == null || picked.files.first.path == null) return;
    setState(() => _busy = true);
    try {
      final file = File(picked.files.first.path!);
      final report = await state.library.verifyPackage(file);
      final count = await _manifestCount(file);
      setState(() {
        _lastReport = report;
        _lastReportName = picked.files.first.name;
        _lastChecked = count;
      });
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _importPackage(AppState state) async {
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
      setState(() => _importNote =
          '${state.t('pkg_imported')} ($imported)');
      await state.refresh();
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final state = AppStateScope.of(context);
    final scopeLabel = state.selected.isNotEmpty
        ? state.t('export_scope_selected',
            {'{}': AppStrings.num(state.selected.length, state.language)})
        : state.t('export_scope_filtered',
            {'{}': AppStrings.num(state.files.length, state.language)});
    return Scaffold(
      appBar: AppBar(title: Text(state.t('btn_packages'))),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(state.t('export_header_sub'),
                style: const TextStyle(color: Colors.grey)),
            const SizedBox(height: 8),
            Text(scopeLabel),
            const SizedBox(height: 16),
            FilledButton.icon(
              key: const ValueKey('pkg_export'),
              onPressed: _busy ? null : () => _export(state),
              icon: const Icon(Icons.archive),
              label: Text(state.t('btn_export')),
            ),
            if (_lastExport != null) ...[
              const SizedBox(height: 8),
              SelectableText(_lastExport!),
              const SizedBox(height: 8),
              OutlinedButton.icon(
                key: const ValueKey('pkg_verify_last'),
                onPressed: _busy ? null : () => _verifyLast(state),
                icon: const Icon(Icons.verified),
                label: Text(state.t('btn_verify')),
              ),
            ],
            const SizedBox(height: 12),
            OutlinedButton.icon(
              key: const ValueKey('pkg_verify_pick'),
              onPressed: _busy ? null : () => _verifyPicked(state),
              icon: const Icon(Icons.fact_check),
              label: Text(state.t('verify_pick')),
            ),
            const SizedBox(height: 12),
            OutlinedButton.icon(
              key: const ValueKey('pkg_import'),
              onPressed: _busy ? null : () => _importPackage(state),
              icon: const Icon(Icons.unarchive),
              label: Text(state.t('btn_import_pkg')),
            ),
            if (_busy) ...[
              const SizedBox(height: 16),
              const LinearProgressIndicator(),
            ],
            if (_importNote != null) ...[
              const SizedBox(height: 16),
              Card(
                  child: Padding(
                      padding: const EdgeInsets.all(12),
                      child: Text(_importNote!))),
            ],
            if (_lastReport != null) ...[
              const SizedBox(height: 16),
              Card(
                key: const ValueKey('verify_report'),
                child: Padding(
                  padding: const EdgeInsets.all(12),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(state.t('verify_header_title'),
                          style: const TextStyle(
                              fontSize: 18, fontWeight: FontWeight.bold)),
                      const SizedBox(height: 4),
                      Text(
                          '${state.t('verify_file_label')} ${_lastReportName ?? ''}'),
                      const SizedBox(height: 8),
                      Text(
                        _lastReport!.ok
                            ? state.t('verify_ok')
                            : state.t('verify_count_bad', {
                                '0': AppStrings.num(
                                    _lastChecked, state.language),
                                '1': AppStrings.num(
                                    _lastReport!.problems.length,
                                    state.language),
                              }),
                        style: TextStyle(
                          color: _lastReport!.ok ? Colors.green : Colors.red,
                        ),
                      ),
                      if (_lastReport!.problems.isNotEmpty) ...[
                        const SizedBox(height: 8),
                        Text(state.t('verify_problems')),
                        ..._lastReport!.problems.map((p) => Text('• $p')),
                      ],
                    ],
                  ),
                ),
              ),
            ],
          ],
        ),
      ),
    );
  }
}
