// Trash screen: deleted files are kept here until permanently emptied.
// Restore selected, or empty the whole trash (with confirmation).
import 'package:flutter/material.dart';

import '../app_state.dart';
import '../l10n/strings.dart';
import 'package:darspack/core/core.dart';
import 'theme.dart';
import 'widgets.dart';

class TrashScreen extends StatefulWidget {
  const TrashScreen({super.key});

  @override
  State<TrashScreen> createState() => _TrashScreenState();
}

class _TrashScreenState extends State<TrashScreen> {
  final Set<String> _selected = {};

  Future<void> _restoreSelected(AppState state) async {
    final messenger = ScaffoldMessenger.of(context);
    if (_selected.isEmpty) {
      messenger.showSnackBar(
          SnackBar(content: Text(state.t('trash_no_selection'))));
      return;
    }
    var ok = 0;
    for (final name in _selected.toList()) {
      try {
        await state.library.restoreTrash(name);
        ok++;
      } catch (_) {}
    }
    setState(_selected.clear);
    await state.refresh();
    if (!mounted) return;
    messenger.showSnackBar(SnackBar(
        content: Text(state.t('trash_restore_done',
            {'0': AppStrings.num(ok, state.language)}))));
  }

  Future<void> _emptyTrash(AppState state) async {
    final messenger = ScaffoldMessenger.of(context);
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text(state.t('trash_empty_btn')),
        content: Text(state.t('trash_empty_confirm')),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(ctx, false),
              child: Text(state.t('cancel'))),
          TextButton(
              onPressed: () => Navigator.pop(ctx, true),
              child: Text(state.t('btn_delete'))),
        ],
      ),
    );
    if (ok != true) return;
    final count = (await state.library.listTrash()).length;
    await state.library.emptyTrash();
    setState(_selected.clear);
    await state.refresh();
    if (!mounted) return;
    messenger.showSnackBar(SnackBar(
        content: Text(state.t('trash_empty_done',
            {'0': AppStrings.num(count, state.language)}))));
  }

  @override
  Widget build(BuildContext context) {
    final state = AppStateScope.of(context);
    return Scaffold(
      appBar: AppBar(
        title: Text(state.t('trash_title')),
        actions: [
          IconButton(
            key: const ValueKey('trash_restore'),
            icon: const Icon(Icons.restore),
            tooltip: state.t('trash_restore_btn'),
            onPressed: () => _restoreSelected(state),
          ),
          IconButton(
            key: const ValueKey('trash_empty'),
            icon: const Icon(Icons.delete_forever),
            tooltip: state.t('trash_empty_btn'),
            onPressed: () => _emptyTrash(state),
          ),
        ],
      ),
      body: FutureBuilder<List<TrashEntry>>(
        future: state.library.listTrash(),
        builder: (context, snap) {
          if (snap.connectionState == ConnectionState.waiting) {
            return const Center(child: CircularProgressIndicator());
          }
          final entries = snap.data ?? const [];
          if (entries.isEmpty) {
            return EmptyState(
              icon: Icons.delete_outline,
              title: state.t('trash_empty_state'),
              hint: state.t('trash_empty_hint'),
            );
          }
          return ListView.builder(
            itemCount: entries.length,
            itemBuilder: (context, i) {
              final e = entries[i];
              final checked = _selected.contains(e.trashName);
              return CheckboxListTile(
                key: ValueKey('trash_${e.trashName}'),
                value: checked,
                onChanged: (v) => setState(() {
                  if (v == true) {
                    _selected.add(e.trashName);
                  } else {
                    _selected.remove(e.trashName);
                  }
                }),
                secondary: CircleAvatar(
                  backgroundColor: Theme.of(context).colorScheme.surface,
                  child: Icon(fileIcon(e.originalName)),
                ),
                title: Text(e.originalName),
                subtitle: Text(
                  '${e.subjectName.isEmpty ? state.t('unclassified') : e.subjectName} · ${formatSize(e.size, state.language)}',
                ),
              );
            },
          );
        },
      ),
    );
  }
}
