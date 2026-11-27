import re
import unittest
from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parent.parent
DIAGRAMS = ROOT / "docs" / "diagrams"


class DiagramsTest(unittest.TestCase):
    def test_every_source_has_a_rendered_image_any_viewer_can_draw(self):
        sources = sorted(DIAGRAMS.glob("*.mmd"))
        self.assertTrue(sources)
        for source in sources:
            svg = source.with_suffix(".svg").read_text()
            root = ElementTree.fromstring(svg)
            self.assertTrue(root.tag.endswith("svg"), source.name)
            # HTML labels are dropped by many image viewers; the labels must be SVG text.
            self.assertNotIn("foreignObject", svg, source.name)
            self.assertIn('fill="#ffffff"', svg, source.name)

    def test_pages_show_images_not_mermaid_code(self):
        pages = [ROOT / "README.md", *sorted((ROOT / "docs").glob("*.md"))]
        shown = set()
        for page in pages:
            text = page.read_text()
            self.assertNotIn("```mermaid", text, page.name)
            shown.update(re.findall(r"diagrams/(\w+)\.svg", text))
        self.assertEqual(shown, {p.stem for p in DIAGRAMS.glob("*.mmd")})


if __name__ == "__main__":
    unittest.main()
