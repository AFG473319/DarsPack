// App state: the Library, settings (language/font size persisted in
// SharedPreferences), current filters and share state. One ChangeNotifier
// for the whole app, exposed via AppStateScope (no extra packages).
import 'dart:io';

import 'package:darspack/core/core.dart';
import 'package:darspack/lan/lan_client.dart';
import 'package:darspack/lan/share_server.dart';
import 'package:flutter/widgets.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'l10n/strings.dart';

class AppState extends ChangeNotifier {
  AppState({Library? library, SharedPreferences? prefs})
      : _library = library,
        _prefs = prefs;

  Library? _library;
  SharedPreferences? _prefs;

  /// The library. Only valid after [init] (main shows a loading state).
  Library get library => _library!;
  bool get isReady => _library != null;

  // --- settings (persisted) ---
  String language = 'fa';
  double fontSize = 16;
  bool welcomeShown = false;
  String? lanBaseUrl;
  String? lanPin;

  // --- filters ---
  String query = '';
  int? subjectFilter;
  String? kindFilter;
  String? yearFilter;
  bool unclassifiedOnly = false;

  // --- current list ---
  List<LibraryFile> files = [];
  List<Subject> subjects = [];
  int unclassified = 0;
  int totalFiles = 0;
  bool loading = false;

  // --- multi-select ---
  final Set<int> selected = {};
  bool get selecting => selected.isNotEmpty;

  // --- share (phone as server) ---
  ShareServer? _shareServer;
  List<String> _shareUrls = [];
  bool get sharing => _shareServer?.isRunning ?? false;
  String get sharePin => _shareServer?.pin ?? '';
  int get sharePort => _shareServer?.port ?? 0;
  // start() is the only source of URLs (no public getter on ShareServer).
  List<String> get shareUrls => _shareUrls;

  String t(String key, [Map<String, Object>? args]) =>
      AppStrings.t(key, language, args);

  Future<void> init() async {
    _prefs ??= await SharedPreferences.getInstance();
    language = _prefs!.getString('language') ?? 'fa';
    if (language != 'fa' && language != 'en') language = 'fa';
    fontSize = _prefs!.getDouble('fontSize') ?? 16;
    welcomeShown = _prefs!.getBool('welcomeShown') ?? false;
    final saved = await LanClient.loadSavedServer();
    lanBaseUrl = saved?.baseUrl;
    lanPin = saved?.pin;
    _library ??= await Library.open();
    await refresh();
  }

  Future<void> refresh() async {
    if (_library == null) return;
    loading = true;
    notifyListeners();
    files = await _library!.searchFiles(
      query: query,
      subjectId: subjectFilter,
      kind: kindFilter,
      schoolYear: yearFilter,
      unclassifiedOnly: unclassifiedOnly,
    );
    subjects = await _library!.subjectsWithCounts();
    unclassified = await _library!.unclassifiedCount();
    totalFiles =
        (await _library!.stats())['totalFiles'] as int? ?? 0;
    loading = false;
    notifyListeners();
  }

  Future<void> setLanguage(String lang) async {
    if (lang != 'fa' && lang != 'en') return;
    language = lang;
    await _prefs?.setString('language', lang);
    notifyListeners();
  }

  Future<void> setFontSize(double size) async {
    fontSize = size.clamp(12, 22);
    await _prefs?.setDouble('fontSize', fontSize);
    notifyListeners();
  }

  Future<void> markWelcomeShown() async {
    welcomeShown = true;
    await _prefs?.setBool('welcomeShown', true);
    notifyListeners();
  }

  Future<void> saveLanCredentials(String baseUrl, String pin) async {
    lanBaseUrl = baseUrl;
    lanPin = pin;
    await LanClient.saveServer(baseUrl, pin);
    notifyListeners();
  }

  void setQuery(String q) {
    query = q;
    refresh();
  }

  void setSubjectFilter(int? id) {
    subjectFilter = id;
    unclassifiedOnly = false;
    refresh();
  }

  void setUnclassifiedOnly(bool value) {
    unclassifiedOnly = value;
    if (value) subjectFilter = null;
    refresh();
  }

  void setKindFilter(String? kind) {
    kindFilter = kind;
    refresh();
  }

  void setYearFilter(String? year) {
    yearFilter = year;
    refresh();
  }

  void clearFilters() {
    query = '';
    subjectFilter = null;
    kindFilter = null;
    yearFilter = null;
    unclassifiedOnly = false;
    refresh();
  }

  void toggleSelect(int id) {
    if (selected.contains(id)) {
      selected.remove(id);
    } else {
      selected.add(id);
    }
    notifyListeners();
  }

  void selectAll() {
    selected.addAll(files.map((f) => f.id));
    notifyListeners();
  }

  void clearSelection() {
    selected.clear();
    notifyListeners();
  }

  Future<void> deleteSelected() async {
    for (final id in selected.toList()) {
      await _library!.deleteFile(id);
    }
    selected.clear();
    await refresh();
  }

  /// Imports files and returns the per-file results (duplicates name
  /// their twin in [ImportResult.messageFa]).
  Future<List<ImportResult>> importPicked(List<File> picked) async {
    final results = await _library!.importFiles(picked);
    await refresh();
    return results;
  }

  Future<List<String>> startSharing() async {
    _shareServer ??= ShareServer(_library!);
    _shareUrls = await _shareServer!.start();
    notifyListeners();
    return _shareUrls;
  }

  Future<void> stopSharing() async {
    await _shareServer?.stop();
    _shareUrls = [];
    notifyListeners();
  }
}

/// Inherited access to the AppState (no provider package in pubspec).
class AppStateScope extends InheritedNotifier<AppState> {
  const AppStateScope({super.key, required AppState state, required super.child})
      : super(notifier: state);

  static AppState of(BuildContext context) {
    final scope =
        context.dependOnInheritedWidgetOfExactType<AppStateScope>();
    assert(scope != null, 'AppStateScope not found in widget tree');
    return scope!.notifier!;
  }
}
