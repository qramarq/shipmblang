"""Generate a simple geometric terminal mark; no external image dependencies."""
from pathlib import Path
import struct
import zlib

SIZE = 1024


def chunk(kind, data):
    return struct.pack('!I', len(data)) + kind + data + struct.pack('!I', zlib.crc32(kind + data) & 0xffffffff)


rows = []
for y in range(SIZE):
    row = bytearray(b'\x00')
    for x in range(SIZE):
        chevron = 245 <= x <= 475 and (abs(y - (x + 100)) < 40 or abs(y - (1050 - x)) < 40)
        underline = 550 <= x <= 775 and 615 <= y <= 683
        row.extend((47, 57, 47) if chevron or underline else (255, 237, 170))
    rows.append(row)
png = b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('!2I5B', SIZE, SIZE, 8, 2, 0, 0, 0))
png += chunk(b'IDAT', zlib.compress(b''.join(rows))) + chunk(b'IEND', b'')
(Path(__file__).resolve().parents[1] / 'assets/shipmb-icon.png').write_bytes(png)
