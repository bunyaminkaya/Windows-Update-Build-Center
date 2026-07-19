from __future__ import annotations

import ctypes
import locale
import platform
from dataclasses import dataclass


LANGUAGE_OPTIONS = [
    ("Türkçe", "tr-tr"),
    ("English (United States)", "en-us"),
    ("English (United Kingdom)", "en-gb"),
    ("Deutsch", "de-de"),
    ("Français", "fr-fr"),
    ("Español", "es-es"),
    ("Italiano", "it-it"),
    ("Português (Brasil)", "pt-br"),
    ("Português (Portugal)", "pt-pt"),
    ("Nederlands", "nl-nl"),
    ("Polski", "pl-pl"),
    ("Русский", "ru-ru"),
    ("Українська", "uk-ua"),
    ("العربية", "ar-sa"),
    ("日本語", "ja-jp"),
    ("한국어", "ko-kr"),
    ("中文 (简体)", "zh-cn"),
    ("中文 (繁體)", "zh-tw"),
]

LANGUAGE_CODE_TO_NAME = {
    code.lower(): name
    for name, code in LANGUAGE_OPTIONS
}


@dataclass(frozen=True, slots=True)
class SystemProfile:
    architecture: str
    language_code: str
    language_name: str


class SystemProfileService:
    _cached: SystemProfile | None = None

    @classmethod
    def current(cls) -> SystemProfile:
        if cls._cached is None:
            cls._cached = SystemProfile(
                architecture=cls.detect_architecture(),
                language_code=cls.detect_language_code(),
                language_name="",
            )
            cls._cached = SystemProfile(
                architecture=cls._cached.architecture,
                language_code=cls._cached.language_code,
                language_name=cls.language_name_for_code(
                    cls._cached.language_code
                ),
            )
        return cls._cached

    @staticmethod
    def detect_architecture() -> str:
        machine = (platform.machine() or "").strip().lower()

        if machine in {"arm64", "aarch64"}:
            return "ARM64"
        if machine in {"amd64", "x86_64", "x64"}:
            return "x64"
        if machine in {"x86", "i386", "i686"}:
            return "x86"

        # Windows Python process architecture can differ from OS architecture.
        # PROCESSOR_ARCHITEW6432 reflects the native OS architecture when present.
        import os
        native = (
            os.environ.get("PROCESSOR_ARCHITEW6432")
            or os.environ.get("PROCESSOR_ARCHITECTURE")
            or ""
        ).lower()
        if "arm64" in native:
            return "ARM64"
        if "amd64" in native:
            return "x64"
        if "86" in native:
            return "x86"
        return "x64"

    @staticmethod
    def detect_language_code() -> str:
        # Use the Windows UI language first. This follows the language the user
        # actually sees in Windows rather than only the regional format.
        try:
            buffer = ctypes.create_unicode_buffer(85)
            length = ctypes.windll.kernel32.GetUserDefaultLocaleName(
                buffer,
                len(buffer),
            )
            if length:
                value = buffer.value.strip().replace("_", "-").lower()
                if value:
                    return value
        except Exception:
            pass

        try:
            value = locale.getlocale()[0]
            if value:
                return value.replace("_", "-").lower()
        except Exception:
            pass

        return "en-us"

    @staticmethod
    def language_name_for_code(code: str) -> str:
        normalized = (code or "").lower()
        if normalized in LANGUAGE_CODE_TO_NAME:
            return LANGUAGE_CODE_TO_NAME[normalized]

        language_prefix = normalized.split("-", 1)[0]
        for known_code, name in LANGUAGE_CODE_TO_NAME.items():
            if known_code.split("-", 1)[0] == language_prefix:
                return name

        return "English (United States)"

    @staticmethod
    def language_options() -> list[str]:
        return [name for name, _ in LANGUAGE_OPTIONS]
