"""Terminal UI for real-time display."""
import os
import sys
from typing import Optional


class TerminalUI:
    """Display real-time transcript and suggestions side-by-side."""

    # ANSI color codes
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    WHITE = "\033[97m"
    RESET = "\033[0m"
    BOLD = "\033[1m"
    CLEAR_SCREEN = "\033[2J"
    MOVE_CURSOR = "\033[H"

    def __init__(self, width: int = 40):
        self.width = width
        self.transcript = ""
        self.suggestion = ""
        self.status = "🎤 Listening..."
        self._last_display = ""

    def update_transcript(self, text: str):
        """Update transcript (left side)."""
        self.transcript = text

    def update_suggestion(self, text: str):
        """Update suggestion (right side)."""
        self.suggestion = text

    def update_status(self, status: str):
        """Update status message."""
        self.status = status

    def _wrap_text(self, text: str, width: int, indent: int = 0) -> list:
        """Wrap text to fit width."""
        if not text:
            return []

        indent_str = " " * indent
        words = text.split()
        lines = []
        current_line = ""

        for word in words:
            if len(current_line) + len(word) + 1 <= width - indent:
                current_line += word + " "
            else:
                if current_line:
                    lines.append(indent_str + current_line.strip())
                current_line = word + " "

        if current_line:
            lines.append(indent_str + current_line.strip())

        return lines

    def _pad_line(self, text: str, width: int) -> str:
        """Pad line to exact width."""
        return text.ljust(width)

    def render(self):
        """Render the UI."""
        # Clear screen
        os.system("clear" if os.name == "posix" else "cls")

        # Header
        print(f"{self.BOLD}{self.YELLOW}Real-Time Meeting Assistant{self.RESET}")
        print(f"Status: {self.status}")
        print("─" * (self.width * 2 + 3))
        print()

        # Get terminal width for columns
        col_width = self.width

        # Wrap both sides
        transcript_lines = self._wrap_text(self.transcript, col_width)
        suggestion_lines = self._wrap_text(self.suggestion, col_width)

        # Pad to same height
        max_lines = max(len(transcript_lines), len(suggestion_lines))
        while len(transcript_lines) < max_lines:
            transcript_lines.append("")
        while len(suggestion_lines) < max_lines:
            suggestion_lines.append("")

        # Print side-by-side
        print(f"{self.BOLD}TRANSCRIPT{self.RESET}".ljust(col_width + 2) + f"{self.BOLD}SUGGESTION{self.RESET}")
        print("─" * col_width + "  " + "─" * col_width)

        for t_line, s_line in zip(transcript_lines, suggestion_lines):
            t_padded = self._pad_line(t_line, col_width)
            s_colored = f"{self.GREEN}{s_line}{self.RESET}"
            s_padded = self._pad_line(s_line, col_width)
            print(f"{t_padded}  {s_colored}")

        print()
        print("─" * (self.width * 2 + 3))
        print(f"{self.YELLOW}Press Cmd+Shift+H to get suggestion | Ctrl+C to quit{self.RESET}")

    def render_minimal(self):
        """Render minimal version (just status updates)."""
        print(f"\r{self.status:<80}", end="", flush=True)
