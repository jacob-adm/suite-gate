import importlib.util
import re
import tempfile
import unittest
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


if __name__ == "__main__":
    unittest.main()
