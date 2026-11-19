// Help screen: quick guide, phone (Wi-Fi) guide and FAQ tabs.
// The Windows keyboard-shortcuts and MCP tabs are desktop-only and are
// intentionally not ported; the MCP intro text is kept out of the
// Android help (no MCP server ships in the APK).
import 'package:flutter/material.dart';

import '../app_state.dart';

class HelpScreen extends StatelessWidget {
  const HelpScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final state = AppStateScope.of(context);
    return DefaultTabController(
      length: 3,
      child: Scaffold(
        appBar: AppBar(
          title: Text(state.t('help_dialog_title')),
          bottom: TabBar(
            tabs: [
              Tab(text: state.t('help_tab_quick')),
              Tab(text: state.t('help_tab_phone')),
              Tab(text: state.t('help_tab_faq')),
            ],
          ),
        ),
        body: TabBarView(
          children: [
            _HelpPage(
              key: const ValueKey('help_quick'),
              text: state.t('help_text'),
            ),
            _HelpPage(
              key: const ValueKey('help_phone'),
              text: [
                state.t('help_phone_title'),
                '',
                state.t('help_phone_step1_t'),
                state.t('help_phone_step1_d'),
                '',
                state.t('help_phone_step2_t'),
                state.t('help_phone_step2_d'),
                '',
                state.t('help_phone_step3_t'),
                state.t('help_phone_step3_d'),
                '',
                state.t('help_phone_note'),
              ].join('\n'),
            ),
            _HelpPage(
              key: const ValueKey('help_faq'),
              text: [
                state.t('help_faq_q1'),
                state.t('help_faq_a1'),
                '',
                state.t('help_faq_q2'),
                state.t('help_faq_a2'),
                '',
                state.t('help_faq_q3'),
                state.t('help_faq_a3'),
                '',
                state.t('help_faq_q4'),
                state.t('help_faq_a4'),
              ].join('\n'),
            ),
          ],
        ),
      ),
    );
  }
}

class _HelpPage extends StatelessWidget {
  final String text;
  const _HelpPage({super.key, required this.text});

  @override
  Widget build(BuildContext context) {
    // The Windows strings carry <b>…</b> / <br> markup; strip tags for
    // plain-text display on mobile.
    final plain = text
        .replaceAll(RegExp(r'<br\s*/?>'), '\n')
        .replaceAll(RegExp(r'<[^>]+>'), '');
    return SingleChildScrollView(
      padding: const EdgeInsets.all(16),
      child: Text(plain, style: const TextStyle(fontSize: 15, height: 1.8)),
    );
  }
}
