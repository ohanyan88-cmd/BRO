"""Read the text out of a PDF, or say plainly that it could not be read.

A decoder and nothing else: no network, no filesystem, no execution. It is a separate
module from acquisition because it is a pure function of bytes, and because getting it
wrong is dangerous in a specific way -- BRO verifies a quote against the text it extracted,
so an extraction that drops or mistakes letters produces a quote that verifies perfectly
and is not what the source says. Every design choice here follows from that.

Modern PDFs pack most objects into compressed object streams, so the objects a naive regex
finds are the few that were left outside. Fonts map byte codes to glyphs through their own
encoding, so the bytes inside a text-showing operator are not characters until a font says
which ones they are. This reads both: the object table including object streams, and each
font's /ToUnicode CMap or standard encoding.

Where a font offers no usable map, the glyphs it drew are counted as unreadable rather than
guessed at. Enough of those and the whole extraction is refused.
"""
from __future__ import annotations

import re
import zlib

# A page whose glyphs mostly came from fonts we could not map is not a page we read.
MAX_UNMAPPED_SHARE = 0.02
MIN_EXTRACTED_CHARACTERS = 200

_OBJ = re.compile(rb"(\d+)\s+(\d+)\s+obj\b", re.DOTALL)
_STREAM = re.compile(rb"stream\r?\n", re.DOTALL)
_TOUNICODE_REF = re.compile(rb"/ToUnicode\s+(\d+)\s+\d+\s+R")
_ENCODING_NAME = re.compile(rb"/Encoding\s*/(\w+)")
_SUBTYPE = re.compile(rb"/Subtype\s*/(\w+)")
_FONT_RESOURCE = re.compile(rb"/([A-Za-z0-9_.+-]+)\s+(\d+)\s+\d+\s+R")
_BFCHAR = re.compile(rb"beginbfchar(.*?)endbfchar", re.DOTALL)
_BFRANGE = re.compile(rb"beginbfrange(.*?)endbfrange", re.DOTALL)
_HEX = re.compile(rb"<([0-9A-Fa-f\s]*)>")
_CODESPACE = re.compile(rb"begincodespacerange(.*?)endcodespacerange", re.DOTALL)
# Text operators, in the order a content stream uses them.
_TEXT_OPS = re.compile(
    rb"/([A-Za-z0-9_.+-]+)\s+[\d.]+\s+Tf"          # 1: font selection
    rb"|\((?:\\.|[^\\()])*\)\s*(?:Tj|')"           # literal shown
    rb"|<([0-9A-Fa-f\s]+)>\s*(?:Tj|')"             # hex string shown
    rb"|\[((?:[^\[\]\\]|\\.)*)\]\s*TJ"             # array shown
    rb"|(-?[\d.]+)\s+(-?[\d.]+)\s+(Td|TD)"          # positioned move: tx ty
    rb"|(T\*)",                                     # next line
    re.DOTALL)
# A TJ array interleaves strings with horizontal adjustments in thousandths of an em.
# Those adjustments are where the spaces are: a PDF usually draws "one two" as two runs
# separated by a kern, not as a run containing a space character. Ignoring them is how an
# extractor produces ArtificialIntelligenceRiskManagement.
_ARRAY_PIECE = re.compile(rb"\((?:\\.|[^\\()])*\)|<([0-9A-Fa-f\s]+)>|(-?[\d.]+)")
# Below this, the gap is wide enough to be a word break rather than kerning. Measured
# against NIST AI 100-1 and the Attention paper, where real word gaps run -140 to -400
# and intra-word kerns stay above -60.
WORD_GAP = -90.0

# WinAnsi differs from Latin-1 only in 0x80-0x9F, and those differences are punctuation a
# technical document actually uses -- quotation marks, dashes, the ellipsis.
_WINANSI_HIGH = {
    0x80: "€", 0x82: "‚", 0x83: "ƒ", 0x84: "„", 0x85: "…",
    0x86: "†", 0x87: "‡", 0x88: "ˆ", 0x89: "‰", 0x8A: "Š",
    0x8B: "‹", 0x8C: "Œ", 0x8E: "Ž", 0x91: "‘", 0x92: "’",
    0x93: "“", 0x94: "”", 0x95: "•", 0x96: "–", 0x97: "—",
    0x98: "˜", 0x99: "™", 0x9A: "š", 0x9B: "›", 0x9C: "œ",
    0x9E: "ž", 0x9F: "Ÿ",
}


def _unescape(raw: bytes) -> bytes:
    """Undo PDF literal-string escaping. Returns bytes: they are codes, not characters yet."""
    out = bytearray()
    index = 0
    while index < len(raw):
        byte = raw[index]
        if byte != 0x5C:
            out.append(byte)
            index += 1
            continue
        nxt = raw[index + 1:index + 2]
        simple = {b"n": b"\n", b"r": b"\r", b"t": b"\t", b"b": b"\b", b"f": b"\f",
                  b"(": b"(", b")": b")", b"\\": b"\\"}
        if nxt in simple:
            out += simple[nxt]
            index += 2
        elif nxt.isdigit():
            octal = raw[index + 1:index + 4]
            digits = bytes(c for c in octal if 0x30 <= c <= 0x37)
            out.append(int(digits, 8) & 0xFF if digits else 0)
            index += 1 + len(digits)
        else:
            index += 2
    return bytes(out)


def _inflate(header: bytes, raw: bytes) -> bytes:
    if b"/FlateDecode" not in header:
        return raw
    for attempt in (raw, raw.lstrip(b"\r\n")):
        try:
            return zlib.decompress(attempt)
        except zlib.error:
            try:
                return zlib.decompressobj().decompress(attempt)
            except zlib.error:
                continue
    return b""


class _Document:
    """The object table, including the objects hidden inside compressed object streams."""

    def __init__(self, body: bytes) -> None:
        self.body = body
        self.objects: dict[int, bytes] = {}
        self.streams: dict[int, bytes] = {}
        self._read_plain()
        self._read_object_streams()

    def _read_plain(self) -> None:
        for match in _OBJ.finditer(self.body):
            number = int(match.group(1))
            end = self.body.find(b"endobj", match.end())
            chunk = self.body[match.end():end if end > 0 else len(self.body)]
            stream = _STREAM.search(chunk)
            if stream is None:
                self.objects[number] = chunk
                continue
            header = chunk[:stream.start()]
            stop = chunk.find(b"endstream", stream.end())
            self.objects[number] = header
            self.streams[number] = _inflate(header, chunk[stream.end():stop if stop > 0 else len(chunk)])

    def _read_object_streams(self) -> None:
        for number, data in list(self.streams.items()):
            header = self.objects.get(number, b"")
            if b"/ObjStm" not in header or not data:
                continue
            count = _first_int(header, rb"/N\s+(\d+)")
            first = _first_int(header, rb"/First\s+(\d+)")
            if count is None or first is None:
                continue
            try:
                numbers = [int(token) for token in data[:first].split()]
            except ValueError:
                continue
            pairs = [(numbers[i], numbers[i + 1]) for i in range(0, min(len(numbers), 2 * count), 2)]
            for index, (num, offset) in enumerate(pairs):
                stop = first + (pairs[index + 1][1] if index + 1 < len(pairs) else len(data) - first)
                self.objects.setdefault(num, data[first + offset:stop])


def _first_int(text: bytes, pattern: bytes) -> int | None:
    match = re.search(pattern, text)
    return int(match.group(1)) if match else None


class _Font:
    """One font's answer to: what character did this byte code draw?"""

    def __init__(self, mapping: dict[int, str], width: int, encoding: str) -> None:
        self.mapping = mapping
        self.width = width          # code size in bytes: 1 for simple fonts, 2 for Type0
        self.encoding = encoding    # "cmap", "winansi", "standard" or "" when unreadable

    @property
    def readable(self) -> bool:
        return bool(self.mapping) or self.encoding in ("winansi", "standard")

    def decode(self, codes: bytes) -> tuple[str, int]:
        """Return the text and the number of glyphs this font could not account for."""
        out: list[str] = []
        unmapped = 0
        step = self.width
        for index in range(0, len(codes) - (len(codes) % step), step):
            code = int.from_bytes(codes[index:index + step], "big")
            if code in self.mapping:
                out.append(self.mapping[code])
            elif self.encoding == "winansi" and step == 1:
                out.append(_WINANSI_HIGH.get(code) or bytes([code]).decode("latin-1"))
            elif self.encoding == "standard" and step == 1 and 32 <= code < 127:
                out.append(chr(code))
            else:
                unmapped += 1
        return "".join(out), unmapped


def _parse_cmap(data: bytes) -> tuple[dict[int, str], int]:
    """Read a /ToUnicode CMap into code -> text, and the code width it declares."""
    mapping: dict[int, str] = {}
    width = 1
    space = _CODESPACE.search(data)
    if space:
        first = _HEX.search(space.group(1))
        if first:
            digits = re.sub(rb"\s", b"", first.group(1))
            width = max(1, len(digits) // 2)
    for block in _BFCHAR.findall(data):
        hexes = [re.sub(rb"\s", b"", h) for h in _HEX.findall(block)]
        for index in range(0, len(hexes) - 1, 2):
            code = _as_int(hexes[index])
            text = _as_text(hexes[index + 1])
            if code is not None and text:
                mapping[code] = text
    for block in _BFRANGE.findall(data):
        for low, high, destination in _bfrange_rows(block):
            if low is None or high is None or high - low > 65535:
                continue
            if isinstance(destination, list):
                for offset, item in enumerate(destination):
                    if low + offset <= high and item:
                        mapping[low + offset] = item
            elif destination:
                base = destination
                for offset in range(high - low + 1):
                    if len(base) == 1:
                        mapping[low + offset] = chr(ord(base) + offset)
                    else:
                        mapping[low + offset] = base if offset == 0 else base
    return mapping, width


def _bfrange_rows(block: bytes):
    index = 0
    while index < len(block):
        hexes = _HEX.search(block, index)
        if hexes is None:
            return
        low = _as_int(re.sub(rb"\s", b"", hexes.group(1)))
        second = _HEX.search(block, hexes.end())
        if second is None:
            return
        high = _as_int(re.sub(rb"\s", b"", second.group(1)))
        rest = block[second.end():].lstrip()
        if rest.startswith(b"["):
            close = block.find(b"]", second.end())
            items = [_as_text(re.sub(rb"\s", b"", h)) for h in _HEX.findall(block[second.end():close])]
            yield low, high, items
            index = close + 1
        else:
            third = _HEX.search(block, second.end())
            if third is None:
                return
            yield low, high, _as_text(re.sub(rb"\s", b"", third.group(1)))
            index = third.end()


def _as_int(digits: bytes) -> int | None:
    try:
        return int(digits, 16) if digits else None
    except ValueError:
        return None


def _as_text(digits: bytes) -> str:
    if not digits or len(digits) % 2:
        return ""
    try:
        raw = bytes.fromhex(digits.decode("ascii"))
    except ValueError:
        return ""
    text = raw.decode("utf-16-be", "ignore")
    return "".join(character for character in text if character != "\x00")


def _font_of(document: _Document, number: int) -> _Font:
    header = document.objects.get(number, b"")
    subtype = _SUBTYPE.search(header)
    is_type0 = bool(subtype and subtype.group(1) == b"Type0")
    reference = _TOUNICODE_REF.search(header)
    mapping: dict[int, str] = {}
    width = 2 if is_type0 else 1
    if reference:
        data = document.streams.get(int(reference.group(1)), b"")
        if data:
            mapping, declared = _parse_cmap(data)
            # Only a composite font addresses glyphs with multi-byte codes. A simple font is
            # one byte per code whatever its CMap's codespace happens to say, and trusting the
            # codespace there made every single-byte code miss its entry.
            if mapping:
                width = (declared if declared in (1, 2) else 2) if is_type0 else 1
    if mapping:
        return _Font(mapping, width, "cmap")
    name = _ENCODING_NAME.search(header)
    if not is_type0 and name and name.group(1) == b"WinAnsiEncoding":
        return _Font({}, 1, "winansi")
    if not is_type0 and b"/Type1" in header:
        return _Font({}, 1, "standard")
    return _Font({}, width, "")


def extract_text(body: bytes, *, max_pages: int = 200,
                 max_characters: int = 400_000) -> tuple[str, bool, str]:
    """Extract a PDF's text. Returns (text, complete, reason); text is empty on refusal."""
    if not body.startswith(b"%PDF-"):
        return "", False, "not a PDF document"
    document = _Document(body)
    pages = [number for number, header in document.objects.items()
             if re.search(rb"/Type\s*/Page\b", header)]
    if len(pages) > max_pages:
        return "", False, f"PDF has {len(pages)} pages, over the {max_pages}-page ceiling"

    fonts: dict[int, _Font] = {}
    pieces: list[str] = []
    unmapped = 0
    mapped = 0
    truncated = ""
    for number in sorted(pages):
        header = document.objects.get(number, b"")
        resources = _resources_of(document, header)
        for content in _contents_of(document, header):
            text, gaps, drawn = _read_content(content, resources, document, fonts)
            unmapped += gaps
            mapped += drawn
            if text:
                pieces.append(text)
            if sum(len(piece) for piece in pieces) >= max_characters:
                truncated = f"stopped at the {max_characters}-character extraction ceiling"
                break
        if truncated:
            break

    text = re.sub(r"[ \t]{2,}", " ", "\n".join(pieces)).strip()
    text = re.sub(r"\n{3,}", "\n\n", text)
    total = mapped + unmapped
    if total and unmapped / total > MAX_UNMAPPED_SHARE:
        return "", False, (
            f"{unmapped} of {total} glyphs came from fonts with no usable character map. "
            "Guessing them would produce a quote that verifies against the wrong text, so "
            "the extraction is refused. OCR is not attempted.")
    if len(text) < MIN_EXTRACTED_CHARACTERS:
        return "", False, ("no extractable text layer: the pages are images, or the content "
                           "streams could not be read. OCR is not attempted.")
    return text[:max_characters], not truncated, truncated


def _resources_of(document: _Document, header: bytes) -> dict[bytes, int]:
    """Map the /F1-style names a content stream uses to the font objects they mean."""
    match = re.search(rb"/Resources\s+(\d+)\s+\d+\s+R", header)
    resources = document.objects.get(int(match.group(1)), b"") if match else header
    fonts = re.search(rb"/Font\s*<<(.*?)>>", resources, re.DOTALL)
    if fonts is None:
        reference = re.search(rb"/Font\s+(\d+)\s+\d+\s+R", resources)
        if reference is None:
            return {}
        block = document.objects.get(int(reference.group(1)), b"")
    else:
        block = fonts.group(1)
    return {name: int(number) for name, number in _FONT_RESOURCE.findall(block)}


def _contents_of(document: _Document, header: bytes):
    single = re.search(rb"/Contents\s+(\d+)\s+\d+\s+R", header)
    if single:
        data = document.streams.get(int(single.group(1)))
        if data:
            yield data
        return
    array = re.search(rb"/Contents\s*\[(.*?)\]", header, re.DOTALL)
    if array:
        for number in re.findall(rb"(\d+)\s+\d+\s+R", array.group(1)):
            data = document.streams.get(int(number))
            if data:
                yield data


def _read_content(content: bytes, resources: dict[bytes, int], document: _Document,
                  fonts: dict[int, _Font]) -> tuple[str, int, int]:
    out: list[str] = []
    current: _Font | None = None
    unmapped = 0
    mapped = 0
    for match in _TEXT_OPS.finditer(content):
        name, hex_string, array = match.group(1), match.group(2), match.group(3)
        vertical, next_line = match.group(5), match.group(7)
        if name is not None:
            number = resources.get(name)
            if number is not None:
                if number not in fonts:
                    fonts[number] = _font_of(document, number)
                current = fonts[number]
            else:
                current = None
            continue
        if next_line is not None:
            out.append("\n")
            continue
        if vertical is not None:
            # Td and TD carry (tx, ty). A PDF uses them for horizontal repositioning within
            # a line as often as for a new line, and treating every one as a line break cut
            # 1.5% of the words in NIST SP 800-207 in half -- "incl uding", "reso urces".
            try:
                moved = abs(float(vertical))
            except ValueError:
                moved = 1.0
            out.append("\n" if moved > 0.0 else " ")
            continue
        codes: list[bytes | str] = []
        if hex_string is not None:
            codes.append(_hex_bytes(hex_string))
        elif array is not None:
            for piece in _ARRAY_PIECE.finditer(array):
                if piece.group(2) is not None:
                    try:
                        adjustment = float(piece.group(2))
                    except ValueError:
                        continue
                    if adjustment <= WORD_GAP:
                        codes.append(" ")
                    continue
                codes.append(_hex_bytes(piece.group(1)) if piece.group(1)
                             else _unescape(piece.group(0)[1:-1]))
        else:
            codes.append(_unescape(match.group(0)[match.group(0).index(b"(") + 1:
                                                 match.group(0).rindex(b")")]))
        for chunk in codes:
            if not chunk:
                continue
            if isinstance(chunk, str):
                out.append(chunk)
                continue
            if current is None or not current.readable:
                unmapped += max(1, len(chunk) // (current.width if current else 1))
                continue
            text, gaps = current.decode(chunk)
            unmapped += gaps
            mapped += max(0, len(chunk) // current.width - gaps)
            out.append(text)
    return "".join(out), unmapped, mapped


def _hex_bytes(digits: bytes) -> bytes:
    cleaned = re.sub(rb"\s", b"", digits or b"")
    if len(cleaned) % 2:
        cleaned += b"0"
    try:
        return bytes.fromhex(cleaned.decode("ascii"))
    except ValueError:
        return b""
