// Activity screen: two tabs — activity history and learned hint rules
// (token→subject memory; pre-fill only, never auto-applied).
import 'package:darspack/core/core.dart';
import 'package:flutter/material.dart';

import '../app_state.dart';
import '../l10n/strings.dart';
import 'widgets.dart';

class ActivityScreen extends StatelessWidget {
  const ActivityScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final state = AppStateScope.of(context);
    return DefaultTabController(
      length: 2,
      child: Scaffold(
        appBar: AppBar(
          title: Text(state.t('history_title')),
          bottom: TabBar(
            tabs: [
              Tab(text: state.t('history_title')),
              Tab(text: state.t('hints_title')),
            ],
          ),
        ),
        body: TabBarView(
          children: [
            _HistoryTab(key: const ValueKey('activity_history')),
            _HintsTab(key: const ValueKey('activity_hints')),
          ],
        ),
      ),
    );
  }
}

class _HistoryTab extends StatelessWidget {
  const _HistoryTab({super.key});

  @override
  Widget build(BuildContext context) {
    final state = AppStateScope.of(context);
    return FutureBuilder<List<ActivityEntry>>(
      future: state.library.activityLog(limit: 100),
      builder: (context, snap) {
        if (snap.connectionState == ConnectionState.waiting) {
          return const Center(child: CircularProgressIndicator());
        }
        final rows = snap.data ?? const [];
        if (rows.isEmpty) {
          return EmptyState(
              icon: Icons.history, title: state.t('history_empty'));
        }
        return ListView.builder(
          itemCount: rows.length,
          itemBuilder: (context, i) {
            final r = rows[i];
            final ts = DateTime.tryParse(r.ts);
            final time = ts == null
                ? ''
                : '${ts.hour}:${ts.minute.toString().padLeft(2, '0')}';
            return ListTile(
              leading: const Icon(Icons.history),
              title: Text(r.action),
              subtitle: Text(r.detail),
              trailing: Text(
                time,
                style: const TextStyle(color: Colors.grey),
              ),
            );
          },
        );
      },
    );
  }
}

class _HintsTab extends StatelessWidget {
  const _HintsTab({super.key});

  @override
  Widget build(BuildContext context) {
    final state = AppStateScope.of(context);
    return FutureBuilder<Map<String, LearnedHint>>(
      future: state.library.loadHints(),
      builder: (context, snap) {
        if (snap.connectionState == ConnectionState.waiting) {
          return const Center(child: CircularProgressIndicator());
        }
        final rules = snap.data ?? const {};
        return Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Padding(
              padding: const EdgeInsets.all(16),
              child: Text(state.t('hints_explain')),
            ),
            Expanded(
              child: rules.isEmpty
                  ? EmptyState(
                      icon: Icons.lightbulb_outline,
                      title: state.t('hints_empty'))
                  : ListView.builder(
                      itemCount: rules.length,
                      itemBuilder: (context, i) {
                        final token = rules.keys.elementAt(i);
                        final rule = rules[token]!;
                        return ListTile(
                          leading: const Icon(Icons.lightbulb),
                          title: Text(token),
                          subtitle: Text(rule.subject),
                          trailing: Text(state.t('hints_hits',
                              {'{}': AppStrings.num(rule.hits, state.language)})),
                        );
                      },
                    ),
            ),
          ],
        );
      },
    );
  }
}
