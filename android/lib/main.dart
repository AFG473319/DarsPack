// DarsPack Android entry point: MaterialApp, fa locale by default, RTL,
// dark theme, home = library screen. Opens the Library on start and
// shows a loading state while opening; first run shows the welcome tour.
import 'package:flutter/material.dart';

import 'app_state.dart';
import 'ui/library_screen.dart';
import 'ui/theme.dart';
import 'ui/welcome_screen.dart';

void main() {
  runApp(const DarsPackApp());
}

class DarsPackApp extends StatefulWidget {
  /// Injected state (tests pass a seeded AppState); null builds a real one.
  final AppState? state;
  const DarsPackApp({super.key, this.state});

  @override
  State<DarsPackApp> createState() => _DarsPackAppState();
}

class _DarsPackAppState extends State<DarsPackApp> {
  late final AppState _state;
  late final Future<void> _init;
  bool _welcomePushed = false;

  @override
  void initState() {
    super.initState();
    _state = widget.state ?? AppState();
    _init = _state.isReady ? Future.value() : _state.init();
  }

  @override
  Widget build(BuildContext context) {
    return AppStateScope(
      state: _state,
      child: AnimatedBuilder(
        animation: _state,
        builder: (context, _) => MaterialApp(
          title: 'درس‌پک',
          locale: Locale(_state.language),
          theme: buildTheme(_state.fontSize),
          darkTheme: buildTheme(_state.fontSize),
          themeMode: ThemeMode.dark,
          debugShowCheckedModeBanner: false,
          builder: (context, child) => Directionality(
            textDirection: _state.language == 'fa'
                ? TextDirection.rtl
                : TextDirection.ltr,
            child: child ?? const SizedBox.shrink(),
          ),
          home: FutureBuilder<void>(
            future: _init,
            builder: (context, snap) {
              if (snap.connectionState != ConnectionState.done) {
                return const Scaffold(
                  body: Center(child: CircularProgressIndicator()),
                );
              }
              if (!_state.welcomeShown && !_welcomePushed) {
                _welcomePushed = true;
                WidgetsBinding.instance.addPostFrameCallback((_) {
                  if (context.mounted) {
                    Navigator.push(
                      context,
                      MaterialPageRoute(
                          builder: (_) => const WelcomeScreen()),
                    );
                  }
                });
              }
              return const LibraryScreen();
            },
          ),
        ),
      ),
    );
  }
}
