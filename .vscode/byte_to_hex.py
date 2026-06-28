import re
import sys
from typing import Any


def convert_bytes_to_hex(text) -> str:
    """
    Converts byte strings to hexadecimal notation.
    Example: b"#\x85\x005\nW\x07X" → b"23 85 00 35 0a 57 07 58"
    """

    def replace_match(match) -> str | Any:
        byte_str = match.group(0)
        try:
            # Safe alternative to eval()
            inner = byte_str[2:-1]  # Remove b" and "
            import codecs

            decoded_bytes: str = codecs.escape_decode(inner)[0]
            hex_values: str = "\\x".join(f"{b:02x}" for b in decoded_bytes)
            return f'b"\\x{hex_values}"'
        except Exception as e:
            print(f"⚠️ Error with '{byte_str}': {e}", file=sys.stderr)
            return byte_str  # Return original in case of error

    # Pattern for byte strings: b"..." or b'...'
    pattern = r'b"([^"]*)"|b\'([^\']*)\''
    return re.sub(pattern, replace_match, text)


if __name__ == "__main__":
    # If text is passed as an argument (e.g., from the task)
    if len(sys.argv) > 1:
        text = sys.argv[1]
    else:
        # If no argument, use stdin
        text= sys.stdin.read()

    converted: str = convert_bytes_to_hex(text)
    print(converted)
