"""Binance public-archive parser: in-memory zip, header row, microsecond timestamps normalised to ms."""
import io
import unittest
import zipfile

from pionex_lab.data import binance_vision as bv


class ParseTests(unittest.TestCase):
    def test_parse_zip_microseconds_and_header(self):
        csv = "open_time,o\n1700000000000000,1,2,0.5,1.5,10,0,20,0,0,0,0\n1700000086400000,0,0,0,0,1,0,1,0,0,0,0\n"
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("x.csv", csv)
        rows = bv.parse_zip(buf.getvalue())
        self.assertEqual(rows, [(1700000000000, 1.0, 2.0, 0.5, 1.5, 10.0, 20.0)])



if __name__ == "__main__":
    unittest.main()
