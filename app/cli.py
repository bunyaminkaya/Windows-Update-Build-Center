"""Komut satırı seçenekleri.

  main.py --version                 Sürümü yazar ve çıkar
  main.py --installed               Bu bilgisayardaki Windows build'ini yazar ve çıkar
  main.py --latest [--channel retail] [--limit 10] [--json]
                                    En yeni yayınları arayüz açmadan listeler ve çıkar
  main.py --page "İndirme Yöneticisi" --minimized --no-update-check
                                    Arayüzü verilen sayfada / küçültülmüş / denetimsiz açar
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from app import i18n
from app.version import APP_NAME, APP_VERSION

_ = i18n.tr


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="main.py", description=APP_NAME, add_help=True)
    p.add_argument("--version", action="store_true", help=_("Sürümü yazıp çık"))
    p.add_argument("--installed", action="store_true", help=_("Bu bilgisayardaki Windows build'ini yazıp çık"))
    p.add_argument("--latest", action="store_true", help=_("En yeni yayınları yazıp çık (arayüz açılmaz)"))
    p.add_argument("--channel", default="", help=_("--latest için kanal süzgeci (ör. retail, preview, beta, dev, canary)"))
    p.add_argument("--limit", type=int, default=10, help=_("--latest için en çok kaç kayıt (varsayılan 10)"))
    p.add_argument("--json", action="store_true", help=_("Çıktıyı JSON olarak ver"))
    p.add_argument("--page", default="", help=_("Açılışta gösterilecek sayfanın adı"))
    p.add_argument("--minimized", action="store_true", help=_("Pencereyi küçültülmüş (veya tepside) başlat"))
    p.add_argument("--no-update-check", action="store_true", help=_("Program güncelleme denetimini bu açılışta atla"))
    return p


def parse(argv=None):
    args, _unknown = build_parser().parse_known_args(argv)
    return args


def wants_console(args) -> bool:
    return bool(args.version or args.installed or args.latest)


def _attach_console() -> None:
    """Pencereli (konsolsuz) .exe içinden çalışırken çıktının bir konsola gitmesini sağlar."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        if ctypes.windll.kernel32.AttachConsole(-1):
            sys.stdout = open("CONOUT$", "w", encoding="utf-8")
            sys.stderr = sys.stdout
    except Exception:
        pass


def run(args) -> int:
    """Konsol komutlarını çalıştırır; çıkış kodunu döner."""
    if sys.stdout is None or not getattr(sys.stdout, "isatty", lambda: True)():
        _attach_console()
    if args.version:
        print(f"{APP_NAME} {APP_VERSION}")
        return 0
    if args.installed:
        from services.local_build_service import LocalBuildService
        local = LocalBuildService.current()
        if local is None:
            print(_("Bu bilgisayardaki Windows sürümü okunamadı (yalnızca Windows'ta çalışır)."), file=sys.stderr)
            return 1
        data = {"product": local.product, "version": local.display_version, "build": local.full, "edition": local.edition}
        print(json.dumps(data, ensure_ascii=False) if args.json else f"{local.product} {local.display_version} • Build {local.full}")
        return 0
    if args.latest:
        from services.build_tracker_service import BuildTrackerService
        try:
            records, _last = BuildTrackerService().fetch()
        except Exception as exc:
            records, _last, _when = BuildTrackerService.load_cache()
            if not records:
                print(_("Kayıtlar alınamadı: {}").replace("{}", str(exc)), file=sys.stderr)
                return 1
            print(_("(Çevrimdışı: önbellekten gösteriliyor — {})").replace("{}", str(exc)), file=sys.stderr)
        wanted = args.channel.strip().lower()
        if wanted:
            records = [r for r in records if wanted in (r.channel or "").lower()]
        records = sorted(records, key=lambda r: (r.release_date, r.build_number), reverse=True)[: max(1, args.limit)]
        if args.json:
            print(json.dumps([{
                "build": r.build_number, "kb": r.kb_number, "version": r.windows_version,
                "channel": r.channel, "date": r.release_date,
            } for r in records], ensure_ascii=False, indent=2))
        else:
            for r in records:
                print(f"{r.release_date}  {r.build_number:<14} {r.kb_number or '—':<10} {r.windows_version or '—':<6} {r.channel}")
        return 0
    return 0
