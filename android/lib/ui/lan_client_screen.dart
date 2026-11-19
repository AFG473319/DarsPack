// LAN client screen: connect to a Windows share (address + PIN,
// saved via LanClient.saveServer after the first entry), then browse,
// search, download and upload. Uses LanClient from lib/lan/. Wrong PIN
// 5× locks the IP out for 30 s — surfaced as LanPinException /
// LanLockoutException with Persian messages.
import 'dart:io';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:open_filex/open_filex.dart';

import 'package:darspack/lan/lan_client.dart';

import '../app_state.dart';
import 'theme.dart';
import 'widgets.dart';

class LanClientScreen extends StatefulWidget {
  const LanClientScreen({super.key});

  @override
  State<LanClientScreen> createState() => _LanClientScreenState();
}

class _LanClientScreenState extends State<LanClientScreen> {
  late final TextEditingController _address;
  late final TextEditingController _pin;
  LanClient? _client;
  List<RemoteFile> _files = [];
  String? _error;
  bool _busy = false;
  bool _controllersReady = false;

  // initState cannot read AppStateScope (inherited lookup is illegal
  // before initState completes); didChangeDependencies runs right after
  // with a valid context.
  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (_controllersReady) return;
    _controllersReady = true;
    final state = AppStateScope.of(context);
    _address = TextEditingController(text: state.lanBaseUrl ?? '');
    _pin = TextEditingController(text: state.lanPin ?? '');
  }

  @override
  void dispose() {
    _address.dispose();
    _pin.dispose();
    super.dispose();
  }

  Future<void> _connect(AppState state) async {
    final baseUrl = _address.text.trim();
    final pin = _pin.text.trim();
    if (baseUrl.isEmpty || pin.isEmpty) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await state.saveLanCredentials(baseUrl, pin);
      final client = LanClient(baseUrl: baseUrl, pin: pin);
      final files = await client.search();
      setState(() {
        _client = client;
        _files = files;
      });
    } catch (e) {
      setState(() => _error = e.toString());
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _download(RemoteFile remote) async {
    if (_client == null) return;
    final dest = File(
        '${Directory.systemTemp.path}/${remote.name}');
    try {
      await _client!.downloadFile(remote, dest);
      if (await dest.exists()) await OpenFilex.open(dest.path);
    } catch (e) {
      if (!mounted) return;
      setState(() => _error = e.toString());
    }
  }

  Future<void> _upload(AppState state) async {
    if (_client == null) return;
    final picked = await FilePicker.platform.pickFiles();
    if (picked == null || picked.files.first.path == null) return;
    try {
      await _client!.uploadFile(File(picked.files.first.path!),
          name: picked.files.first.name);
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(state.t('copied_done'))));
    } catch (e) {
      if (!mounted) return;
      setState(() => _error = e.toString());
    }
  }

  @override
  Widget build(BuildContext context) {
    final state = AppStateScope.of(context);
    return Scaffold(
      appBar: AppBar(title: Text(state.t('share_title'))),
      body: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            TextField(
              key: const ValueKey('lan_address'),
              controller: _address,
              decoration: const InputDecoration(
                labelText: 'نشانی سرور (مثل http://192.168.1.5:8765)',
                hintText: 'http://192.168.1.5:8765',
              ),
              textDirection: TextDirection.ltr,
            ),
            const SizedBox(height: 8),
            TextField(
              key: const ValueKey('lan_pin'),
              controller: _pin,
              decoration:
                  InputDecoration(labelText: state.t('share_pin')),
              keyboardType: TextInputType.number,
              textDirection: TextDirection.ltr,
            ),
            const SizedBox(height: 12),
            Row(
              children: [
                FilledButton(
                  key: const ValueKey('lan_connect'),
                  onPressed: _busy ? null : () => _connect(state),
                  child: Text(state.t('btn_confirm')),
                ),
                const SizedBox(width: 8),
                if (_client != null)
                  OutlinedButton.icon(
                    key: const ValueKey('lan_upload'),
                    onPressed: () => _upload(state),
                    icon: const Icon(Icons.upload),
                    label: Text(state.t('btn_import')),
                  ),
              ],
            ),
            if (_busy) ...[
              const SizedBox(height: 12),
              const LinearProgressIndicator(),
            ],
            if (_error != null) ...[
              const SizedBox(height: 12),
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(12),
                  child: Text(_error!, key: const ValueKey('lan_error')),
                ),
              ),
            ],
            const SizedBox(height: 8),
            Expanded(
              child: _client == null
                  ? EmptyState(
                      icon: Icons.wifi,
                      title: state.t('share_title'),
                      hint: state.t('share_hint'),
                    )
                  : ListView.builder(
                      itemCount: _files.length,
                      itemBuilder: (context, i) {
                        final f = _files[i];
                        return ListTile(
                          leading: CircleAvatar(child: Icon(fileIcon(f.name))),
                          title: Text(f.name),
                          subtitle: Text(
                              '${f.subject ?? state.t('unclassified')} · ${f.kind ?? 'سایر'}'),
                          trailing: IconButton(
                            icon: const Icon(Icons.download),
                            onPressed: () => _download(f),
                          ),
                        );
                      },
                    ),
            ),
          ],
        ),
      ),
    );
  }
}
