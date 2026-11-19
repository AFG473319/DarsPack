// Share screen (phone as server): start/stop the embedded shelf HTTP
// server (lib/lan/share_server.dart), show the random 6-digit PIN
// (Latin digits, exactly as typed) and a QR code of the URL with
// ?pin=… (the server's own URLs carry no PIN).
import 'package:flutter/material.dart';
import 'package:qr_flutter/qr_flutter.dart';

import '../app_state.dart';
import '../l10n/strings.dart';

class ShareScreen extends StatefulWidget {
  const ShareScreen({super.key});

  @override
  State<ShareScreen> createState() => _ShareScreenState();
}

class _ShareScreenState extends State<ShareScreen> {
  bool _busy = false;

  Future<void> _toggle(AppState state) async {
    setState(() => _busy = true);
    try {
      if (state.sharing) {
        await state.stopSharing();
      } else {
        await state.startSharing();
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final state = AppStateScope.of(context);
    return AnimatedBuilder(
      animation: state,
      builder: (context, _) {
        final sharing = state.sharing;
        final url = state.shareUrls.isNotEmpty ? state.shareUrls.first : '';
        // QR per DESIGN.md: http://<lan-ip>:<port>/?pin=…
        final qrData = url.isEmpty ? '' : '$url?pin=${state.sharePin}';
        return Scaffold(
          appBar: AppBar(title: Text(state.t('share_title'))),
          body: SingleChildScrollView(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  sharing
                      ? state.t('share_status_live').replaceFirst(
                          '{}', AppStrings.num(state.sharePort, state.language))
                      : state.t('share_off'),
                  style: const TextStyle(fontSize: 16),
                ),
                const SizedBox(height: 16),
                FilledButton.icon(
                  key: const ValueKey('share_toggle'),
                  onPressed: _busy ? null : () => _toggle(state),
                  icon: Icon(sharing ? Icons.stop : Icons.wifi),
                  label: Text(state.t(
                      sharing ? 'btn_stop_share' : 'btn_share')),
                ),
                if (sharing) ...[
                  const SizedBox(height: 24),
                  Text(state.t('share_pin'),
                      style: const TextStyle(fontSize: 16)),
                  const SizedBox(height: 4),
                  // PIN in Latin digits, exactly as typed.
                  SelectableText(
                    state.sharePin,
                    key: const ValueKey('share_pin'),
                    style: const TextStyle(
                        fontSize: 40,
                        fontWeight: FontWeight.bold,
                        letterSpacing: 8),
                  ),
                  const SizedBox(height: 16),
                  Text(state.t('share_urls')),
                  const SizedBox(height: 4),
                  SelectableText(url),
                  const SizedBox(height: 16),
                  Text(state.t('qr_caption')),
                  const SizedBox(height: 8),
                  Center(
                    child: Container(
                      color: Colors.white,
                      padding: const EdgeInsets.all(12),
                      child: QrImageView(
                        key: const ValueKey('share_qr'),
                        data: qrData,
                        version: QrVersions.auto,
                        size: 220,
                      ),
                    ),
                  ),
                  const SizedBox(height: 16),
                  Text(state.t('share_hint'),
                      style: const TextStyle(color: Colors.grey)),
                ],
              ],
            ),
          ),
        );
      },
    );
  }
}
