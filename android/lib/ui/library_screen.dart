// Home / library screen: subject chips («همه» + «بدون درس» with count +
// one chip per subject with counts), kind filter, search field, file list
// (type icon + kind badge + chapter/lesson + size). Tap opens with the
// system viewer (open_filex); long-press starts multi-select with
// delete / reclassify actions. Navigation lives in the drawer.
import 'package:flutter/material.dart';
import 'package:open_filex/open_filex.dart';

import '../app_state.dart';
import '../l10n/strings.dart';
import 'backup_screen.dart';
import 'classify_sheet.dart';
import 'duplicates_screen.dart';
import 'exam_pack_screen.dart';
import 'file_detail_sheet.dart';
import 'help_screen.dart';
import 'import_screen.dart';
import 'lan_client_screen.dart';
import 'packages_screen.dart';
import 'settings_screen.dart';
import 'share_screen.dart';
import 'stats_screen.dart';
import 'activity_screen.dart';
import 'trash_screen.dart';
import 'welcome_screen.dart';
import 'package:darspack/core/core.dart';
import 'theme.dart';
import 'widgets.dart';

class LibraryScreen extends StatefulWidget {
  const LibraryScreen({super.key});

  @override
  State<LibraryScreen> createState() => _LibraryScreenState();
}

class _LibraryScreenState extends State<LibraryScreen> {
  final _searchController = TextEditingController();

  @override
  void dispose() {
    _searchController.dispose();
    super.dispose();
  }

  Future<void> _openFile(AppState state, LibraryFile file) async {
    final stored = state.library.storedFileFor(file);
    if (await stored.exists()) {
      await OpenFilex.open(stored.path);
    } else {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(state.t('empty_search'))),
      );
    }
  }

  /// After an import flow returns results, offer the classify sheet
  /// for the newly imported files (subject as suggestion only).
  Future<void> _classifyImported(
      AppState state, List<ImportResult>? results) async {
    if (results == null || !results.any((r) => r.isImported)) return;
    final files = <LibraryFile>[];
    for (final r in results.where((r) => r.isImported)) {
      final f = await state.library.getFile(r.fileId ?? -1);
      if (f != null) files.add(f);
    }
    if (files.isEmpty || !mounted) return;
    await showClassifySheet(context, state, files);
  }

  Future<void> _confirmDelete(AppState state) async {
    final count = state.selected.length;
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text(state.t('delete_title')),
        content: Text(state.t(
          'delete_confirm_many',
          {'count': AppStrings.num(count, state.language)},
        )),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: Text(state.t('cancel')),
          ),
          TextButton(
            onPressed: () => Navigator.pop(ctx, true),
            child: Text(state.t('btn_delete')),
          ),
        ],
      ),
    );
    if (ok == true) {
      await state.deleteSelected();
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(
          content: Text(state.t(
              'delete_done_many', {'count': AppStrings.num(count, state.language)}))));
    }
  }

  void _go(Widget screen) {
    Navigator.pop(context); // close drawer
    Navigator.push(context, MaterialPageRoute(builder: (_) => screen));
  }

  @override
  Widget build(BuildContext context) {
    final state = AppStateScope.of(context);
    final lang = state.language;
    return AnimatedBuilder(
      animation: state,
      builder: (context, _) {
        final selecting = state.selecting;
        return Scaffold(
          appBar: AppBar(
            title: selecting
                ? Text(AppStrings.num(state.selected.length, lang))
                : Text(state.t('app_title')),
            actions: [
              if (selecting) ...[
                IconButton(
                  key: const ValueKey('action_edit'),
                  icon: const Icon(Icons.edit),
                  tooltip: state.t('bulk_edit_menu'),
                  onPressed: () async {
                    final ids = state.selected.toList();
                    if (ids.length == 1) {
                      final file = await state.library.getFile(ids.first);
                      if (file != null && context.mounted) {
                        await showFileDetailSheet(context, state, file);
                      }
                    } else {
                      await showBulkEditSheet(context, state, ids);
                    }
                    state.clearSelection();
                  },
                ),
                IconButton(
                  key: const ValueKey('action_delete'),
                  icon: const Icon(Icons.delete),
                  tooltip: state.t('btn_delete'),
                  onPressed: () => _confirmDelete(state),
                ),
                IconButton(
                  icon: const Icon(Icons.close),
                  onPressed: state.clearSelection,
                ),
              ] else ...[
                IconButton(
                  key: const ValueKey('btn_import'),
                  icon: const Icon(Icons.add),
                  tooltip: state.t('btn_import'),
                  onPressed: () async {
                    final results = await Navigator.push<List<ImportResult>>(
                      context,
                      MaterialPageRoute(builder: (_) => const ImportScreen()),
                    );
                    await _classifyImported(state, results);
                  },
                ),
                IconButton(
                  icon: const Icon(Icons.help_outline),
                  tooltip: state.t('btn_help'),
                  onPressed: () => Navigator.push(
                    context,
                    MaterialPageRoute(builder: (_) => const HelpScreen()),
                  ),
                ),
              ],
            ],
          ),
          drawer: _buildDrawer(state),
          body: Column(
            children: [
              Padding(
                padding: const EdgeInsets.fromLTRB(12, 8, 12, 4),
                child: TextField(
                  key: const ValueKey('search_field'),
                  controller: _searchController,
                  onChanged: state.setQuery,
                  decoration: InputDecoration(
                    hintText: state.t('search_placeholder'),
                    prefixIcon: const Icon(Icons.search),
                    suffixIcon: state.query.isEmpty
                        ? null
                        : IconButton(
                            icon: const Icon(Icons.clear),
                            tooltip: state.t('clear_search'),
                            onPressed: () {
                              _searchController.clear();
                              state.setQuery('');
                            },
                          ),
                  ),
                ),
              ),
              _buildChips(state),
              _buildKindRow(state),
              Expanded(child: _buildList(state)),
              _buildStatusBar(state),
            ],
          ),
          floatingActionButton: selecting
              ? null
              : FloatingActionButton(
                  key: const ValueKey('fab_import'),
                  tooltip: state.t('btn_import'),
                  onPressed: () async {
                    final results = await Navigator.push<List<ImportResult>>(
                      context,
                      MaterialPageRoute(builder: (_) => const ImportScreen()),
                    );
                    await _classifyImported(state, results);
                  },
                  child: const Icon(Icons.add),
                ),
        );
      },
    );
  }

  Widget _buildChips(AppState state) {
    final lang = state.language;
    final chips = <Widget>[
      ChoiceChip(
        key: const ValueKey('chip_all'),
        label: Text(state.t('all_subjects')),
        selected: state.subjectFilter == null && !state.unclassifiedOnly,
        onSelected: (_) => state.setSubjectFilter(null),
      ),
      ChoiceChip(
        key: const ValueKey('chip_unclassified'),
        label: Text(
            '${state.t('unclassified')} (${AppStrings.num(state.unclassified, lang)})'),
        selected: state.unclassifiedOnly,
        onSelected: (_) => state.setUnclassifiedOnly(true),
      ),
    ];
    for (final s in state.subjects) {
      if (s.fileCount == 0) continue;
      chips.add(ChoiceChip(
        key: ValueKey('chip_subject_${s.id}'),
        label: Text('${s.name} (${AppStrings.num(s.fileCount, lang)})'),
        selected: state.subjectFilter == s.id,
        onSelected: (_) => state.setSubjectFilter(s.id),
      ));
    }
    return SizedBox(
      height: 44,
      child: ListView(
        scrollDirection: Axis.horizontal,
        padding: const EdgeInsets.symmetric(horizontal: 8),
        children: chips
            .map((c) => Padding(
                padding: const EdgeInsets.symmetric(horizontal: 3), child: c))
            .toList(),
      ),
    );
  }

  Widget _buildKindRow(AppState state) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 2),
      child: Row(
        children: [
          Expanded(
            child: DropdownButtonFormField<String?>(
              key: ValueKey('kind_${state.kindFilter}'),
              initialValue: state.kindFilter,
              decoration: InputDecoration(
                labelText: state.t('col_kind'),
                contentPadding:
                    const EdgeInsets.symmetric(horizontal: 12, vertical: 0),
              ),
              items: [
                DropdownMenuItem(value: null, child: Text(state.t('all_kinds'))),
                for (final k in ['جزوه', 'نمونه‌سوال', 'کاربرگ', 'تکلیف', 'سایر'])
                  DropdownMenuItem(value: k, child: Text(k)),
              ],
              onChanged: state.setKindFilter,
            ),
          ),
          if (state.query.isNotEmpty ||
              state.subjectFilter != null ||
              state.kindFilter != null ||
              state.unclassifiedOnly)
            TextButton(
              onPressed: () {
                _searchController.clear();
                state.clearFilters();
              },
              child: Text(state.t('clear_search')),
            ),
        ],
      ),
    );
  }

  Widget _buildList(AppState state) {
    if (state.loading && state.files.isEmpty) {
      return const Center(child: CircularProgressIndicator());
    }
    if (state.files.isEmpty) {
      return EmptyState(
        icon: state.query.isEmpty ? Icons.folder_open : Icons.search_off,
        title: state.t(state.query.isEmpty ? 'empty_library' : 'empty_search'),
        hint: state.query.isEmpty ? state.t('empty_fresh_desc') : null,
      );
    }
    return ListView.separated(
      key: const ValueKey('file_list'),
      itemCount: state.files.length,
      separatorBuilder: (_, __) =>
          const Divider(height: 1, color: AppColors.border),
      itemBuilder: (context, i) {
        final file = state.files[i];
        return FileTile(
          file: file,
          lang: state.language,
          selected: state.selected.contains(file.id),
          onTap: () {
            if (state.selecting) {
              state.toggleSelect(file.id);
            } else {
              _openFile(state, file);
            }
          },
          onLongPress: () => state.toggleSelect(file.id),
        );
      },
    );
  }

  Widget _buildStatusBar(AppState state) {
    final lang = state.language;
    final shown = state.files.length;
    final text = state.query.isEmpty &&
            state.subjectFilter == null &&
            state.kindFilter == null &&
            !state.unclassifiedOnly
        ? state.t('status_files').replaceFirst('{}', AppStrings.num(shown, lang))
        : state.t('status_files_filtered', {
            '0': AppStrings.num(shown, lang),
            '1': AppStrings.num(state.totalFiles, lang),
          });
    return Container(
      width: double.infinity,
      color: AppColors.header,
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
      child: Text(text, style: const TextStyle(color: AppColors.muted)),
    );
  }

  Drawer _buildDrawer(AppState state) {
    Widget item(String key, IconData icon, String label, VoidCallback onTap,
        {String? badge}) {
      return ListTile(
        key: ValueKey(key),
        leading: Icon(icon),
        title: Text(label),
        trailing: badge == null
            ? null
            : Container(
                padding:
                    const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                decoration: BoxDecoration(
                  color: AppColors.accent,
                  borderRadius: BorderRadius.circular(12),
                ),
                child: Text(badge,
                    style: const TextStyle(color: AppColors.onAccent)),
              ),
        onTap: onTap,
      );
    }

    return Drawer(
      child: ListView(
        children: [
          DrawerHeader(
            decoration: const BoxDecoration(color: AppColors.header),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisAlignment: MainAxisAlignment.end,
              children: [
                Text(state.t('app_title'),
                    style: const TextStyle(fontSize: 24)),
                Text(state.t('app_subtitle'),
                    style: const TextStyle(color: AppColors.muted)),
              ],
            ),
          ),
          item('nav_library', Icons.folder, state.t('nav_all_files'),
              () => Navigator.pop(context)),
          item(
              'nav_unclassified',
              Icons.label_off,
              state.t('nav_unclassified'),
              () {
                Navigator.pop(context);
                state.setUnclassifiedOnly(true);
              },
              badge: state.unclassified == 0
                  ? null
                  : AppStrings.num(state.unclassified, state.language)),
          const Divider(),
          item('nav_packages', Icons.archive, state.t('nav_packages'),
              () => _go(const PackagesScreen())),
          item('nav_exam_pack', Icons.school, state.t('btn_exam_pack'),
              () => _go(const ExamPackScreen())),
          item('nav_duplicates', Icons.copy_all, state.t('nav_duplicates'),
              () => _go(const DuplicatesScreen())),
          item('nav_trash', Icons.delete, state.t('nav_trash'),
              () => _go(const TrashScreen())),
          item('nav_backup', Icons.backup, state.t('btn_import_pkg'),
              () => _go(const BackupScreen())),
          const Divider(),
          item('nav_share', Icons.wifi, state.t('nav_wifi_share'),
              () => _go(const ShareScreen())),
          item('nav_lan_client', Icons.phone_android, state.t('share_title'),
              () => _go(const LanClientScreen())),
          item('nav_stats', Icons.bar_chart, state.t('nav_stats'),
              () => _go(const StatsScreen())),
          item('nav_history', Icons.history, state.t('nav_history'),
              () => _go(const ActivityScreen())),
          const Divider(),
          item('nav_settings', Icons.settings, state.t('nav_settings'),
              () => _go(const SettingsScreen())),
          item('nav_help', Icons.help, state.t('btn_help'),
              () => _go(const HelpScreen())),
          item('nav_welcome', Icons.tour, state.t('btn_tour'),
              () => _go(const WelcomeScreen())),
          item('nav_about', Icons.info, state.t('btn_about'), () {
            Navigator.pop(context);
            showAboutDialog(
              context: context,
              applicationName: state.t('app_title'),
              applicationVersion: '0.1.0',
              children: [
                Text(state.t('about_text', {'{}': '0.1.0'})),
              ],
            );
          }),
        ],
      ),
    );
  }
}
