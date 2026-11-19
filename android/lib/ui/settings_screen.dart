// Settings screen: language fa/en, font size slider, library info,
// about. Font size applies immediately; language applies immediately
// too on Android (unlike the Windows restart note).
import 'package:flutter/material.dart';

import '../app_state.dart';
import '../l10n/strings.dart';

class SettingsScreen extends StatelessWidget {
  const SettingsScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final state = AppStateScope.of(context);
    return AnimatedBuilder(
      animation: state,
      builder: (context, _) => Scaffold(
        appBar: AppBar(title: Text(state.t('settings_title'))),
        body: ListView(
          padding: const EdgeInsets.all(16),
          children: [
            Text(state.t('settings_lang'),
                style: const TextStyle(fontSize: 16)),
            RadioGroup<String>(
              groupValue: state.language,
              onChanged: (v) {
                if (v != null) state.setLanguage(v);
              },
              child: Column(
                children: [
                  RadioListTile<String>(
                    key: const ValueKey('lang_fa'),
                    title: const Text('فارسی'),
                    value: 'fa',
                  ),
                  RadioListTile<String>(
                    key: const ValueKey('lang_en'),
                    title: const Text('English'),
                    value: 'en',
                  ),
                ],
              ),
            ),
            const Divider(),
            Text(
                '${state.t('settings_font')}: ${AppStrings.num(state.fontSize.round(), state.language)}'),
            Slider(
              key: const ValueKey('font_slider'),
              value: state.fontSize,
              min: 12,
              max: 22,
              divisions: 10,
              label: '${state.fontSize.round()}',
              onChanged: state.setFontSize,
            ),
            const Divider(),
            ListTile(
              title: Text(state.t('settings_lib')),
              subtitle: Text(state
                  .t('status_files')
                  .replaceFirst('{}',
                      AppStrings.num(state.totalFiles, state.language))),
            ),
            ListTile(
              title: Text(state.t('btn_about')),
              subtitle: Text(state.t('about_text', {'{}': '0.1.0'})),
            ),
            const Divider(),
            Text(state.t('settings_restart'),
                style: const TextStyle(color: Colors.grey, fontSize: 12)),
          ],
        ),
      ),
    );
  }
}
