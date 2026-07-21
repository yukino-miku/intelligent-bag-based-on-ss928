from pathlib import Path
import tempfile
import unittest

from ss928_backend.model_conversion.prepare_calibration_list import (
    calibration_images,
    write_image_list,
)


class CalibrationImageListTest(unittest.TestCase):
    def test_list_is_deterministic_absolute_and_limited(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "nested").mkdir()
            for name in ("c.jpg", "a.jpeg", "nested/b.JPG"):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"jpeg fixture")
            (root / "ignored.png").write_bytes(b"png fixture")

            output = root / "image_ref_list.txt"
            images = write_image_list(root, output, 2)

            self.assertEqual(2, len(images))
            self.assertTrue(all(path.is_absolute() for path in images))
            self.assertEqual(
                [str(path) for path in images],
                output.read_text(encoding="utf-8").splitlines(),
            )

    def test_rejects_too_few_jpegs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "one.jpg").write_bytes(b"jpeg fixture")

            with self.assertRaisesRegex(ValueError, "need at least 2"):
                calibration_images(root, 2)


if __name__ == "__main__":
    unittest.main()
