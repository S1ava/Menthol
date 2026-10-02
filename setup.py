"""py2app konfigurace — staví Menthol.app s vlastní identitou (ne 'Python').

Build:  python setup.py py2app     (dělá install.sh v izolovaném build venv)
"""
from setuptools import setup

APP = ["menthol_app.py"]
DATA_FILES = ["config.example.json"]

OPTIONS = {
    "argv_emulation": False,
    "iconfile": "assets/menthol.icns",
    "plist": {
        "CFBundleName": "Menthol",
        "CFBundleDisplayName": "Menthol",
        "CFBundleIdentifier": "cz.mrvka.menthol",
        "CFBundleVersion": "1.0",
        "CFBundleShortVersionString": "1.0",
        "LSUIElement": True,            # jen v horní liště, žádná ikona v Docku
        "LSMinimumSystemVersion": "12.0",
        "NSHumanReadableCopyright": "Menthol",
        # V zabaleném appce bývá default kódování ASCII → český config/log by
        # padal na Unicode. PYTHONUTF8=1 vynutí UTF-8 pro open() i stdio.
        "LSEnvironment": {"PYTHONUTF8": "1", "LANG": "en_US.UTF-8"},
    },
    # Celé balíky přibalit natvrdo (lazy importy by modulegraph nemusel chytit).
    "packages": [
        "rumps",
        "anthropic",
        "httpx",
        "pydantic",
        "requests",
        "certifi",
        "charset_normalizer",
        "idna",
        "urllib3",
        "websockets",
    ],
    "includes": [
        "src",
        "src.menubar",
        "src.main",
        "src.overlay",
        "src.keychain",
        "src.config",
        "src.llm_handler",
        "src.trigger_classifier",
        "src.caption_server",
        "src.ui",
        "src.transcript_logger",
        "src.hotkey_native",
        "AppKit",
        "Foundation",
        "Quartz",
        "PyObjCTools",
        "objc",
    ],
}

setup(
    app=APP,
    data_files=DATA_FILES,
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
