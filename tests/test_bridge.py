import re, subprocess, sys, tempfile, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from print_bridge.render import LabelSpec, render_pdf  # noqa: E402
from print_bridge.printer import PrintSettings, build_job, to_png  # noqa: E402

HERE = Path(__file__).resolve().parent


class BridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        subprocess.run([sys.executable, str(HERE / "make_pdf.py"), cls.tmp], check=True)

    def test_4x6_fills_label(self):
        [bmp] = render_pdf(f"{self.tmp}/label-4x6.pdf", LabelSpec())
        self.assertEqual((bmp.width, bmp.height), (812, 1218))
        self.assertEqual(len(bmp.data()), 102 * 1218)
        black = sum(8 - bin(b).count("1") for b in bmp.data())
        self.assertGreater(black, 5000)

    def test_a4_landscape_label_is_cropped_and_rotated(self):
        pages = render_pdf(f"{self.tmp}/a4-sheet.pdf", LabelSpec())
        self.assertEqual(len(pages), 2)
        bmp = pages[0]
        # The label's border should reach close to every edge of the 4x6 after crop + rotate.
        rows_with_ink = [i for i, r in enumerate(bmp.rows) if r != b"\xff" * bmp.row_bytes]
        self.assertLess(rows_with_ink[0], 40)
        self.assertGreater(rows_with_ink[-1], bmp.height - 40)

    def test_tspl_job_layout(self):
        [bmp] = render_pdf(f"{self.tmp}/label-4x6.pdf", LabelSpec())
        job = build_job([bmp, bmp], PrintSettings(), copies=3)
        self.assertTrue(job.startswith(b"SIZE 101.6 mm,152.4 mm\r\nGAP 3 mm,0 mm\r\n"))
        self.assertEqual(job.count(b"CLS\r\n"), 2)
        self.assertEqual(job.count(b"PRINT 1,3\r\n"), 2)
        m = re.search(rb"BITMAP 0,0,(\d+),(\d+),0,", job)
        w, h = int(m[1]), int(m[2])
        self.assertEqual(job[m.end():m.end() + w * h], bmp.data())
        self.assertEqual(job[m.end() + w * h:m.end() + w * h + 2], b"\r\n")

    def test_png_preview(self):
        [bmp] = render_pdf(f"{self.tmp}/label-4x6.pdf", LabelSpec())
        self.assertTrue(to_png(bmp).startswith(b"\x89PNG\r\n\x1a\n"))


if __name__ == "__main__":
    unittest.main()
