"""Real-time Meeting Assistant (Menthol) modules.

Submoduly se načítají líně (PEP 562) — import balíčku `src` sám o sobě
nenatáhne těžké závislosti (whisper/torch). To výrazně zrychluje start,
zvlášť když se používá Google STT a Whisper vůbec není potřeba.
"""
import importlib

_LAZY = {
    "AudioCapture": ".audio_capture",
    "Transcriber": ".transcriber",
    "LLMHandler": ".llm_handler",
    "TerminalUI": ".ui",
    "HotkeyListener": ".hotkey",
}


def __getattr__(name):
    """Načte submodul až při prvním použití daného symbolu."""
    if name in _LAZY:
        module = importlib.import_module(_LAZY[name], __name__)
        return getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = list(_LAZY)
