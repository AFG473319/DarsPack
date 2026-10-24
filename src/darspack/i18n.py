"""Minimal i18n: two plain dictionaries and a global language switch.

No framework, no .ts files — the whole mechanism is one dict lookup the
anyone can explain in one sentence. UI strings live here; data values
(subject names, kinds) are stored in Persian in the database and shown
as-is regardless of language.
"""
from __future__ import annotations

_current = "fa"   # Persian-first; switchable at runtime

STRINGS = {
    "fa": {
        "app_title": "درس‌پک",
        "search_placeholder": "جست‌جو… (فارسی یا انگلیسی، با اعداد فارسی یا لاتین)",
        "all_subjects": "همه‌ی درس‌ها",
        "all_kinds": "همه‌ی انواع",
        "col_name": "نام فایل",
        "col_subject": "درس",
        "col_chapter": "فصل",
        "col_kind": "نوع",
        "col_size": "اندازه",
        "col_date": "تاریخ ورود",
        "btn_import": "وارد کردن…",
        "btn_export": "خروجی بسته‌ی درس‌پک…",
        "btn_verify": "راستی‌آزمایی بسته…",
        "btn_import_pkg": "خواندن یک بسته…",
        "btn_dups": "تکراری‌ها و تضادها",
        "btn_share": "اشتراک‌گذاری در شبکه",
        "btn_stop_share": "قطع اشتراک‌گذاری",
        "btn_edit_meta": "ویرایش اطلاعات",
        "btn_about": "درباره ما",
        "btn_help": "راهنما",
        "btn_feedback": "بازخورد",
        "btn_settings": "تنظیمات",
        "status_files": "{} فایل در کتابخانه",
        "share_title": "اشتراک‌گذاری در شبکه‌ی محلی",
        "share_pin": "رمز اتصال (PIN)",
        "share_urls": "این نشانی را روی گوشی (در همان Wi-Fi) باز کنید:",
        "share_hint": "سرور فقط تا وقتی این پنجره باز است روشن می‌ماند. رمز هر بار تصادفی است.",
        "share_off": "سرور خاموش است.",
        "import_title": "وارد کردن فایل‌ها",
        "import_pick_files": "انتخاب فایل‌ها",
        "import_pick_folder": "انتخاب پوشه",
        "import_keep": "فایل‌های تکراری را هم نگه دار",
        "import_running": "در حال وارد کردن: {}",
        "import_done": "{} فایل وارد شد · {} تکراری رد شد · {} خطا",
        "export_title": "خروجی بسته‌ی درس‌پک",
        "export_scope_selected": "فقط فایل‌های انتخاب‌شده ({})",
        "export_scope_filtered": "همه‌ی نتیجه‌های فیلتر فعلی ({})",
        "export_done": "بسته ساخته شد: {} فایل\nشناسه‌ی manifest: {}",
        "verify_ok": "بسته سالم است — همه‌ی فایل‌ها کامل و دست‌نخورده‌اند.",
        "verify_problems": "مشکلات یافت‌شده:",
        "verify_pick": "انتخاب بسته (.zip)",
        "pkg_import_btn": "وارد کردن محتوای این بسته",
        "pkg_imported": "محتوای بسته وارد کتابخانه شد (تکراری‌ها رد شدند).",
        "dups_tab1": "تکراری کامل",
        "dups_tab2": "نسخه‌های متفاوت، نام یکسان",
        "dups_tab3": "یک محتوا، نام‌های مختلف",
        "meta_title": "ویرایش اطلاعات فایل",
        "meta_subject": "درس",
        "meta_chapter": "فصل",
        "meta_kind": "نوع",
        "meta_tags": "برچسب‌ها (با ویرگول جدا کنید)",
        "meta_note": "یادداشت",
        "settings_title": "تنظیمات",
        "settings_lang": "زبان / Language",
        "settings_font": "اندازه‌ی فونت",
        "settings_lib": "پوشه‌ی کتابخانه",
        "settings_restart": "تغییر زبان و پوشه‌ی کتابخانه بعد از اجرای دوباره اعمال می‌شود.",
        "about_text": "درس‌پک {}\nنویسنده: AFG473319\n\nسازمان‌دهنده‌ی آفلاین فایل‌های درسی — فارسی‌اول، بدون نیاز به اینترنت.",
        "help_text": "۱) فایل‌ها را با «وارد کردن» به کتابخانه اضافه کنید — پیشنهاد درس و فصل از روی نام فایل داده می‌شود و قابل ویرایش است.\n"
                     "۲) با جعبه‌ی جست‌جو فایل‌ها را پیدا کنید؛ اعداد فارسی و لاتین یکسانند.\n"
                     "۳) «تکراری‌ها و تضادها» فقط پرچم می‌گذارد؛ هیچ فایلی خودکار حذف یا بازنویسی نمی‌شود.\n"
                     "۴) «خروجی بسته» یک ZIP با فهرست و هش هر فایل می‌سازد؛ «راستی‌آزمایی» سالم بودن بسته را بعد از کپی چک می‌کند.\n"
                     "۵) «اشتراک‌گذاری در شبکه» یک صفحه‌ی وب برای گوشی‌های همان Wi-Fi باز می‌کند — با رمز.",
        "feedback_title": "بازخورد شما",
        "feedback_placeholder": "چه چیزی خوب بود؟ چه چیزی باید بهتر شود؟",
        "feedback_thanks": "ممنون! بازخورد شما ذخیره شد.",
        "err_no_selection": "اول یک فایل انتخاب کنید.",
        "ok": "باشه",
        "cancel": "لغو",
    },
    "en": {
        "app_title": "DarsPack",
        "search_placeholder": "Search… (Persian or English, Persian or Latin digits)",
        "all_subjects": "All subjects",
        "all_kinds": "All kinds",
        "col_name": "File name",
        "col_subject": "Subject",
        "col_chapter": "Chapter",
        "col_kind": "Kind",
        "col_size": "Size",
        "col_date": "Imported",
        "btn_import": "Import…",
        "btn_export": "Export package…",
        "btn_verify": "Verify package…",
        "btn_import_pkg": "Open a package…",
        "btn_dups": "Duplicates & conflicts",
        "btn_share": "Share on network",
        "btn_stop_share": "Stop sharing",
        "btn_edit_meta": "Edit info",
        "btn_about": "About",
        "btn_help": "Help",
        "btn_feedback": "Feedback",
        "btn_settings": "Settings",
        "status_files": "{} files in library",
        "share_title": "Local network sharing",
        "share_pin": "Pairing PIN",
        "share_urls": "Open this address on a phone on the same Wi-Fi:",
        "share_hint": "The server runs only while this window is open. A fresh random PIN is generated each time.",
        "share_off": "Server is off.",
        "import_title": "Import files",
        "import_pick_files": "Choose files",
        "import_pick_folder": "Choose folder",
        "import_keep": "Also keep duplicate files",
        "import_running": "Importing: {}",
        "import_done": "{} imported · {} duplicates skipped · {} errors",
        "export_title": "Export package",
        "export_scope_selected": "Selected files only ({})",
        "export_scope_filtered": "All current filter results ({})",
        "export_done": "Package created: {} files\nmanifest id: {}",
        "verify_ok": "Package is intact — every file complete and unchanged.",
        "verify_problems": "Problems found:",
        "verify_pick": "Choose a package (.zip)",
        "pkg_import_btn": "Import this package's contents",
        "pkg_imported": "Package contents imported (duplicates were skipped).",
        "dups_tab1": "Exact duplicates",
        "dups_tab2": "Different versions, same name",
        "dups_tab3": "Same content, different names",
        "meta_title": "Edit file info",
        "meta_subject": "Subject",
        "meta_chapter": "Chapter",
        "meta_kind": "Kind",
        "meta_tags": "Tags (comma separated)",
        "meta_note": "Note",
        "settings_title": "Settings",
        "settings_lang": "Language / زبان",
        "settings_font": "Font size",
        "settings_lib": "Library folder",
        "settings_restart": "Language and library folder changes apply after restart.",
        "about_text": "DarsPack {}\nAuthor: AFG473319\n\nOffline-first organizer for school materials — Persian-first, no internet required.",
        "help_text": "1) Use Import to copy files into the library — subject/chapter is suggested from the filename and editable.\n"
                     "2) Find files with the search box; Persian and Latin digits match each other.\n"
                     "3) Duplicates & conflicts are only flagged — nothing is ever auto-deleted or overwritten.\n"
                     "4) Export builds a ZIP with an index and a per-file hash; Verify checks a copied package's integrity.\n"
                     "5) Share on network opens a web page for phones on the same Wi-Fi — protected by a PIN.",
        "feedback_title": "Your feedback",
        "feedback_placeholder": "What worked? What should be better?",
        "feedback_thanks": "Thank you! Your feedback was saved.",
        "err_no_selection": "Select a file first.",
        "ok": "OK",
        "cancel": "Cancel",
    },
}


def set_language(lang: str) -> None:
    global _current
    _current = lang if lang in STRINGS else "fa"


def language() -> str:
    return _current


def tr(key: str) -> str:
    return STRINGS[_current].get(key, STRINGS["fa"].get(key, key))
