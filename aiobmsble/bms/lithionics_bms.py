def _feed_notify(self, data: bytes) -> list[str]:
    """Return any complete CRLF-terminated ASCII lines."""
    self._rx += data
    lines: list[str] = []
    while b"\r\n" in self._rx:
        raw, self._rx = self._rx.split(b"\r\n", 1)
        if not raw:
            continue
        try:
            lines.append(raw.decode("ascii", errors="strict"))
        except UnicodeDecodeError:
            # ignore garbage
            continue
    return lines


def _parse_line(self, line: str) -> None:
    line = line.strip()
    if not line or line == "ERROR":
        return

    if line.startswith("&"):
        # "&,1,317,035859,0136,2300,FF05,8700"
        self._last_status_line = line
        return

    # "1362,340,341,341,340,37,41,0,99,000000"
    parts = line.split(",")
    if len(parts) < 9:
        return  # or raise in debug mode

    pack_cv = int(parts[0])
    self.voltage = pack_cv / 100.0

    # heuristic: next 4 are cells (12V pack)
    cell_cvs = [int(x) for x in parts[1:5]]
    self.cell_voltages = [cv / 100.0 for cv in cell_cvs]

    self.temp_1 = int(parts[5])
    self.temp_2 = int(parts[6])

    # current scaling unknown; start with integer A
    self.current = int(parts[7])

    self.soc = int(parts[8])

    # optional flags
    self.flags_raw = parts[9] if len(parts) > 9 else None
