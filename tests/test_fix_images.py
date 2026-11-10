import contextlib
import hashlib
import importlib.util
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image

SPEC = importlib.util.spec_from_file_location('fix_images', Path(__file__).resolve().parents[1] / 'fix_images.py')
app = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(app)


class ConversionTests(unittest.TestCase):
    def run_app(self, root):
        stream = io.StringIO()
        with patch.object(sys, 'argv', ['fix_images.py', str(root), '--keep-background']), contextlib.redirect_stdout(stream):
            code = app.main()
        return code, stream.getvalue()

    def test_conversion_preserves_originals_and_skips_rerun(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'nested').mkdir()
            (root / 'empty').mkdir()
            Image.new('RGBA', (120, 200), (220, 30, 20, 255)).save(root / 'nested' / 'product.png')
            before = app.sha256_file(root / 'nested' / 'product.png')
            code, log = self.run_app(root)
            target = root / 'Fixed images' / 'nested' / 'product.jpg'
            self.assertEqual(code, 0)
            self.assertIn('JPGs saved this run: 1', log)
            with Image.open(target) as image:
                self.assertEqual(image.size, (600, 399))
                self.assertEqual(image.mode, 'RGB')
                self.assertTrue(all(v > 245 for v in image.getpixel((0, 0))))
                self.assertGreater(image.getpixel((300, 199))[0], 180)
            self.assertEqual(before, app.sha256_file(root / 'nested' / 'product.png'))
            output_before = target.read_bytes()
            code, log = self.run_app(root)
            self.assertEqual(code, 0)
            self.assertIn('JPGs saved this run: 0', log)
            self.assertEqual(output_before, target.read_bytes())
            self.assertEqual(len(list((root / 'Fixed images').rglob('*.jpg'))), 1)

    def test_same_stem_and_corrupt_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            Image.new('RGB', (100, 100), 'red').save(root / 'item.png')
            Image.new('RGB', (100, 100), 'blue').save(root / 'item.jpg')
            (root / 'broken.png').write_bytes(b'not an image')
            code, log = self.run_app(root)
            self.assertEqual(code, 1)
            self.assertIn('Errors: 1', log)
            self.assertEqual(len(list((root / 'Fixed images').glob('*.jpg'))), 2)

    def test_transparent_margins_trimmed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'item.png'
            im = Image.new('RGBA', (400, 400))
            im.paste((0, 150, 0, 255), (160, 100, 240, 300))
            im.save(path)
            result = app.prepare_image(path, None, False)
            self.assertEqual(result.size, (600, 399))
            self.assertEqual(result.getpixel((300, 199)), (0, 150, 0))
            self.assertEqual(result.getpixel((0, 0)), (255, 255, 255))


if __name__ == '__main__':
    unittest.main()
