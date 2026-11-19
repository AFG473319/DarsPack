// Welcome / onboarding: 3 slides (safe local library, smart
// classification, offline + phone sharing), shown on first run.
import 'package:flutter/material.dart';

import '../app_state.dart';

class WelcomeScreen extends StatefulWidget {
  const WelcomeScreen({super.key});

  @override
  State<WelcomeScreen> createState() => _WelcomeScreenState();
}

class _WelcomeScreenState extends State<WelcomeScreen> {
  final _controller = PageController();
  int _page = 0;

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final state = AppStateScope.of(context);
    final slides = [
      (state.t('welcome_slide1_title'), state.t('welcome_slide1_desc'),
          Icons.folder),
      (state.t('welcome_slide2_title'), state.t('welcome_slide2_desc'),
          Icons.label),
      (state.t('welcome_slide3_title'), state.t('welcome_slide3_desc'),
          Icons.wifi),
    ];
    return Scaffold(
      appBar: AppBar(title: Text(state.t('welcome_title'))),
      body: Column(
        children: [
          Padding(
            padding: const EdgeInsets.all(16),
            child: Text(state.t('welcome_subtitle'),
                textAlign: TextAlign.center,
                style: const TextStyle(color: Colors.grey)),
          ),
          Expanded(
            child: PageView.builder(
              key: const ValueKey('welcome_pager'),
              controller: _controller,
              itemCount: slides.length,
              onPageChanged: (i) => setState(() => _page = i),
              itemBuilder: (context, i) {
                final (title, desc, icon) = slides[i];
                return Padding(
                  padding: const EdgeInsets.all(24),
                  child: Column(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      Icon(icon, size: 72),
                      const SizedBox(height: 24),
                      Text(title,
                          textAlign: TextAlign.center,
                          style: const TextStyle(fontSize: 20)),
                      const SizedBox(height: 12),
                      Text(desc,
                          textAlign: TextAlign.center,
                          style: const TextStyle(
                              fontSize: 15, height: 1.8)),
                    ],
                  ),
                );
              },
            ),
          ),
          Text(state.t('welcome_step', {
            '0': (_page + 1).toString(),
            '1': slides.length.toString(),
          })),
          const SizedBox(height: 12),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16),
            child: Row(
              children: [
                if (_page > 0)
                  TextButton(
                    key: const ValueKey('welcome_prev'),
                    onPressed: () => _controller.previousPage(
                        duration: const Duration(milliseconds: 300),
                        curve: Curves.easeInOut),
                    child: Text(state.t('welcome_prev')),
                  ),
                const Spacer(),
                FilledButton(
                  key: ValueKey(
                      _page == slides.length - 1 ? 'welcome_start' : 'welcome_next'),
                  onPressed: () async {
                    if (_page == slides.length - 1) {
                      await state.markWelcomeShown();
                      if (context.mounted) Navigator.pop(context);
                    } else {
                      _controller.nextPage(
                          duration: const Duration(milliseconds: 300),
                          curve: Curves.easeInOut);
                    }
                  },
                  child: Text(state.t(_page == slides.length - 1
                      ? 'welcome_start'
                      : 'welcome_next')),
                ),
              ],
            ),
          ),
          const SizedBox(height: 24),
        ],
      ),
    );
  }
}
