import unittest
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tracker import classify,clean_link,ingest,init
import sqlite3

class Tests(unittest.TestCase):
 def test_iron(self): self.assertEqual(classify('2019 Harley Iron 1200 XL1200NS'),'Iron 1200')
 def test_seventy_two(self): self.assertEqual(classify('2014 Harley Seventy-Two XL1200V'),'Seventy-Two')
 def test_883_excluded(self): self.assertIsNone(classify('Harley iron 883 XL883N'))
 def test_48_excluded(self): self.assertIsNone(classify('Harley Forty-Eight XL1200X'))
 def test_ambiguous_1200(self): self.assertIsNone(classify('Harley Davidson Sportster 1200'))
 def test_url(self): self.assertEqual(clean_link('https://example.com/bike/?utm_source=x&v=2'),'https://example.com/bike?v=2')
 def test_price_history(self):
  db=sqlite3.connect(':memory:');init(db)
  x='https://example.com/one'
  self.assertEqual(ingest(db,'2019 Iron 1200 $15,000','2000 km',x,'test','t1')[0],'NEW')
  self.assertEqual(ingest(db,'2019 Iron 1200 $14,500','2000 km',x,'test','t2')[0],'PRICE REDUCTION')
  self.assertEqual(db.execute('SELECT COUNT(*) FROM prices').fetchone()[0],2)
if __name__ == '__main__':unittest.main()
