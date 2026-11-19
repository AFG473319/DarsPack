// Duplicates screen: R1 exact duplicates, R2 version conflicts
// (same name, different content), R3 rename hints (same content,
// different names). Flag only — nothing is ever auto-deleted.
import 'package:darspack/core/core.dart';
import 'package:flutter/material.dart';

import '../app_state.dart';
import 'widgets.dart';

class DuplicatesScreen extends StatelessWidget {
  const DuplicatesScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final state = AppStateScope.of(context);
    return DefaultTabController(
      length: 3,
      child: Scaffold(
        appBar: AppBar(
          title: Text(state.t('btn_dups')),
          bottom: TabBar(
            tabs: [
              Tab(text: state.t('dups_tab1')),
              Tab(text: state.t('dups_tab2')),
              Tab(text: state.t('dups_tab3')),
            ],
          ),
        ),
        body: TabBarView(
          children: [
            _GroupsTab(
              key: const ValueKey('dups_tab_exact'),
              load: () async => (await state.library.duplicateGroups())
                  .map((g) => (g.labelFa, g.files))
                  .toList(),
              emptySub: state.t('dups_clean_sub1'),
            ),
            _GroupsTab(
              key: const ValueKey('dups_tab_conflicts'),
              load: () async => (await state.library.versionConflicts())
                  .map((g) => (g.labelFa, g.files))
                  .toList(),
              emptySub: state.t('dups_clean_sub2'),
            ),
            _GroupsTab(
              key: const ValueKey('dups_tab_renames'),
              load: () async => (await state.library.renameHints())
                  .map((g) => (g.labelFa, g.files))
                  .toList(),
              emptySub: state.t('dups_clean_sub3'),
            ),
          ],
        ),
      ),
    );
  }
}

class _GroupsTab extends StatelessWidget {
  final Future<List<(String, List<LibraryFile>)>> Function() load;
  final String emptySub;
  const _GroupsTab({super.key, required this.load, required this.emptySub});

  @override
  Widget build(BuildContext context) {
    final state = AppStateScope.of(context);
    return FutureBuilder<List<(String, List<LibraryFile>)>>(
      future: load(),
      builder: (context, snap) {
        if (snap.connectionState == ConnectionState.waiting) {
          return const Center(child: CircularProgressIndicator());
        }
        final groups = snap.data ?? const [];
        if (groups.isEmpty) {
          return EmptyState(
            icon: Icons.check_circle_outline,
            title: state.t('dups_clean_msg'),
            hint: emptySub,
          );
        }
        return ListView.builder(
          itemCount: groups.length,
          itemBuilder: (context, i) {
            final (title, files) = groups[i];
            return Card(
              margin: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Padding(
                    padding: const EdgeInsets.fromLTRB(12, 12, 12, 4),
                    child: Text(title,
                        style: const TextStyle(fontWeight: FontWeight.bold)),
                  ),
                  ...files.map((f) => FileTile(
                        file: f,
                        lang: state.language,
                        onTap: () {},
                      )),
                  const SizedBox(height: 6),
                ],
              ),
            );
          },
        );
      },
    );
  }
}
