// Dark theme — Windows ui/theme.py tokens (DESIGN.md).
// bg #14161b, surface #1a1d24, surface2 #22262f, primary navy #2d3f6e,
// accent saffron #e0a83c (accent only — never large fills).
import 'package:flutter/material.dart';

class AppColors {
  static const bg = Color(0xFF14161B);
  static const surface = Color(0xFF1A1D24);
  static const surface2 = Color(0xFF22262F);
  static const surface3 = Color(0xFF2A2F39);
  static const header = Color(0xFF1E222A);
  static const border = Color(0xFF2E3440);
  static const text = Color(0xFFE9E6DF);
  static const muted = Color(0xFF9AA0AB);
  static const faint = Color(0xFF6B7280);
  static const primary = Color(0xFF2D3F6E);
  static const primaryHover = Color(0xFF3A5290);
  static const accent = Color(0xFFE0A83C);
  static const onAccent = Color(0xFF1C1508);
  static const danger = Color(0xFFD9736E);
  static const success = Color(0xFF8FD08F);
}

/// Small tinted background per kind badge (badge text stays readable).
Color kindBadgeColor(String kind) {
  switch (kind) {
    case 'جزوه':
      return const Color(0xFF3A5290);
    case 'نمونه‌سوال':
      return const Color(0xFF7A5A1E);
    case 'کاربرگ':
      return const Color(0xFF2E6B4F);
    case 'تکلیف':
      return const Color(0xFF6B3A6E);
    default:
      return const Color(0xFF3A4048);
  }
}

/// Icon per file extension (type icon in the file list).
IconData fileIcon(String name) {
  final ext = name.contains('.') ? name.split('.').last.toLowerCase() : '';
  switch (ext) {
    case 'pdf':
      return Icons.picture_as_pdf;
    case 'png':
    case 'jpg':
    case 'jpeg':
    case 'gif':
    case 'webp':
      return Icons.image;
    case 'doc':
    case 'docx':
    case 'txt':
    case 'rtf':
      return Icons.description;
    case 'xls':
    case 'xlsx':
    case 'csv':
      return Icons.table_chart;
    case 'ppt':
    case 'pptx':
      return Icons.slideshow;
    case 'zip':
    case 'rar':
    case '7z':
      return Icons.archive;
    case 'mp3':
    case 'wav':
    case 'm4a':
      return Icons.audio_file;
    case 'mp4':
    case 'mkv':
    case 'mov':
      return Icons.video_file;
    default:
      return Icons.insert_drive_file;
  }
}

ThemeData buildTheme(double fontSize) {
  final base = ThemeData.dark(useMaterial3: true);
  final scale = fontSize / 16.0;
  // fontFamily is a ThemeData constructor parameter only (not copyWith).
  return ThemeData(
    brightness: Brightness.dark,
    useMaterial3: true,
    fontFamily: 'Vazirmatn',
    scaffoldBackgroundColor: AppColors.bg,
    colorScheme: const ColorScheme.dark(
      primary: AppColors.primary,
      secondary: AppColors.accent,
      surface: AppColors.surface,
      error: AppColors.danger,
      onPrimary: AppColors.text,
      onSurface: AppColors.text,
    ),
    appBarTheme: const AppBarTheme(
      backgroundColor: AppColors.header,
      foregroundColor: AppColors.text,
      elevation: 0,
    ),
    drawerTheme: const DrawerThemeData(backgroundColor: AppColors.surface),
    cardColor: AppColors.surface,
    dividerColor: AppColors.border,
    textTheme: base.textTheme.apply(
      bodyColor: AppColors.text,
      displayColor: AppColors.text,
    ).copyWith(
      bodyMedium: base.textTheme.bodyMedium?.copyWith(fontSize: 14 * scale),
      bodyLarge: base.textTheme.bodyLarge?.copyWith(fontSize: 16 * scale),
      titleMedium: base.textTheme.titleMedium?.copyWith(fontSize: 16 * scale),
      titleLarge: base.textTheme.titleLarge?.copyWith(fontSize: 20 * scale),
    ),
    chipTheme: base.chipTheme.copyWith(
      backgroundColor: AppColors.surface2,
      selectedColor: AppColors.primary,
      labelStyle: TextStyle(color: AppColors.text, fontSize: 13 * scale),
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: AppColors.surface2,
      border: OutlineInputBorder(
        borderRadius: BorderRadius.circular(10),
        borderSide: const BorderSide(color: AppColors.border),
      ),
      enabledBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(10),
        borderSide: const BorderSide(color: AppColors.border),
      ),
      focusedBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(10),
        borderSide: const BorderSide(color: AppColors.accent),
      ),
      hintStyle: const TextStyle(color: AppColors.muted),
    ),
    elevatedButtonTheme: ElevatedButtonThemeData(
      style: ElevatedButton.styleFrom(
        backgroundColor: AppColors.primary,
        foregroundColor: AppColors.text,
      ),
    ),
    floatingActionButtonTheme: const FloatingActionButtonThemeData(
      backgroundColor: AppColors.primary,
      foregroundColor: AppColors.text,
    ),
  );
}
