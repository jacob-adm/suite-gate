import importlib.util
import re
import struct
import tempfile
import unittest
import zlib
from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("screenshots", ROOT / "scripts" / "screenshots.py")
screenshots = importlib.util.module_from_spec(spec)
spec.loader.exec_module(screenshots)

SVG = "{http://www.w3.org/2000/svg}"


def text_lines(svg):
    root = ElementTree.fromstring(svg)
    return [t.text for t in root.iter(SVG + "text")][1:]  # first text is the title bar


class RenderTest(unittest.TestCase):
    def test_output_keeps_columns_and_markup_characters(self):
        svg = screenshots.render("t", "tool <a> & b", "x\ty\n  z\n", 1)
        lines = [line.replace(" ", " ") for line in text_lines(svg)]
        self.assertEqual(lines, ["$ tool <a> & b", "x       y", "  z", "# exit status 1"])

    def test_long_lines_wrap_at_terminal_width(self):
        svg = screenshots.render("t", "c", "a" * (screenshots.MAX_COLS + 5) + "\n", 0)
        lines = text_lines(svg)
        self.assertEqual([len(line) for line in lines[1:3]], [screenshots.MAX_COLS, 5])

    def test_empty_output_shows_only_command_and_status(self):
        self.assertEqual(len(text_lines(screenshots.render("t", "c", "", 0))), 2)


class LeakTest(unittest.TestCase):
    def test_temporary_and_home_paths_are_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            self.assertEqual(screenshots.leaks("clean output\n", base), [])
            self.assertIn(str(base), screenshots.leaks(f"saved to {base}/x\n", base))
            self.assertIn(str(Path.home()), screenshots.leaks(f"{Path.home()}/.zshrc", base))


class CommittedScreenshotsTest(unittest.TestCase):
    def test_every_listed_screenshot_exists_and_names_no_local_path(self):
        directory = ROOT / "docs" / "screenshots"
        for name, *_ in screenshots.SHOTS:
            svg = (directory / f"{name}.svg").read_text()
            ElementTree.fromstring(svg)
            self.assertIsNone(re.search(r"/(Users|home|private|tmp)/", svg), name)

    def test_committed_report_screenshot_is_a_readable_png(self):
        path = ROOT / "docs" / "screenshots" / screenshots.PMA_PNG
        if not path.exists():
            self.skipTest("no report screenshot committed")
        width, _, rows = screenshots.png_rows(path.read_bytes())
        self.assertGreater(width, 0)
        self.assertGreater(len(rows), 0)


def chunk(kind, body):
    return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))


class TrimBottomTest(unittest.TestCase):
    WHITE, INK = b"\xff\xff\xff", b"\x10\x20\x30"

    def image(self, ink_rows, height=40, width=6):
        rows = [(self.INK if y in ink_rows else self.WHITE) * width for y in range(height)]
        return screenshots.png_encode(width, 3, rows)

    def test_keeps_content_and_margin_and_drops_the_rest(self):
        width, channels, rows = screenshots.png_rows(screenshots.trim_bottom(self.image({2, 9}), margin=4))
        self.assertEqual((width, channels, len(rows)), (6, 3, 14))
        self.assertEqual(rows[9], self.INK * 6)
        self.assertEqual(rows[13], self.WHITE * 6)

    def test_content_reaching_the_bottom_is_not_cut(self):
        _, _, rows = screenshots.png_rows(screenshots.trim_bottom(self.image({0, 38}), margin=4))
        self.assertEqual(len(rows), 40)

    def test_decodes_every_png_row_filter(self):
        # The same two rows written with filters 1, 2, 3 and 4 decode to the original pixels.
        width, rows = 3, [bytes([10, 20, 30] * 3), bytes([40, 50, 60, 70, 80, 90, 100, 110, 120])]
        prev, raw = bytes(width * 3), b""
        for kind in (1, 2, 3, 4):
            for row in rows:
                out = bytearray()
                for i in range(width * 3):
                    a = row[i - 3] if i >= 3 else 0
                    b, c = prev[i], prev[i - 3] if i >= 3 else 0
                    p = a + b - c
                    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                    pred = {1: a, 2: b, 3: (a + b) // 2,
                            4: a if pa <= pb and pa <= pc else b if pb <= pc else c}[kind]
                    out.append((row[i] - pred) & 255)
                raw += bytes([kind]) + bytes(out)
                prev = row
        png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, 8, 8, 2, 0, 0, 0))
               + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
        self.assertEqual(screenshots.png_rows(png)[2], rows * 4)


if __name__ == "__main__":
    unittest.main()
