import json
import os
import sqlite3
import sys
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path
from unittest.mock import patch, MagicMock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import tracker
from sources import discover_dealer, parse_dealer, PublicClient


class RegressionTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:'); tracker.init(self.db)

    def tearDown(self): self.db.close()

    def add(self,title='2019 Iron 1200 $15000',description='12044 km QLD',url='https://example.com/bike',now='t1',**kw):
        return tracker.ingest(self.db,title,description,url,'test',now,**kw)

    def test_year_boundaries(self):
        for model,good,bad in [('Iron 1200',[2018,2021],[2017,2022]),('Seventy-Two',[2012,2016],[2011,2017])]:
            for year in good: self.assertIsNotNone(self.add(f'{year} {model}',url=f'https://example.com/{model}/{year}'))
            for year in bad: self.assertIsNone(self.add(f'{year} {model}'))
        self.assertIsNone(self.add('Iron 1200','Serviced in 2019'))

    def test_model_aliases_and_conflicts(self):
        for name in ['XL 1200 NS','XL-1200-NS','Iron–1200','1200 Iron']:
            self.assertEqual(tracker.classify(name),'Iron 1200')
        for name in ['XL 1200 V','Seventy‑Two','Sportster 72','72 Sportster']:
            self.assertEqual(tracker.classify(name),'Seventy-Two')
        for name in ['Iron 883 1200 conversion','XL1200X','Iron 1200 / Seventy Two']:
            self.assertIsNone(tracker.classify(name))

    def test_title_controls_model(self):
        self.assertIsNotNone(self.add(description='Similar styling to Iron 883'))
        self.assertIsNone(self.add('2019 Iron 883', 'Iron 1200 also available'))
        self.assertIsNone(self.add('2019 Iron 1200 exhaust parts'))

    def test_odometer_and_unlimited_price(self):
        self.add('2019 Iron 1200 $1,234,567','123456 km QLD')
        self.assertEqual(self.db.execute('SELECT price_aud,kilometres,location FROM listings').fetchone(),(1234567,123456,'QLD'))

    def test_price_events_and_missing_price(self):
        self.add(); self.add('2019 Iron 1200 $14000',now='t2'); self.add('2019 Iron 1200 $16000',now='t3'); self.add('2019 Iron 1200',now='t4')
        self.assertEqual(self.db.execute('SELECT price_aud,first_seen,last_seen FROM listings').fetchone(),(16000,'t1','t4'))
        self.assertEqual([r[0] for r in self.db.execute('SELECT kind FROM events ORDER BY observed_at')],['NEW','PRICE REDUCTION'])
        self.assertEqual(self.db.execute('SELECT count(*) FROM prices').fetchone()[0],3)

    def test_duplicate_vin_retains_ads(self):
        self.add(vin='5HD1LF3G1FC420470')
        self.add(url='https://another.com/bike',vin='5HD1LF3G1FC420470',now='t2')
        self.add(vin='5HD1LF3G1FC420470',now='t3')
        self.assertEqual(self.db.execute('SELECT count(*) FROM listings').fetchone()[0],2)
        self.assertEqual(self.db.execute('SELECT count(*) FROM events').fetchone()[0],1)
        self.assertIsNone(self.db.execute("SELECT duplicate_of FROM listings WHERE url='https://example.com/bike'").fetchone()[0])

    def test_index_cannot_overwrite_direct_price(self):
        self.add(status='Seller page observed')
        self.add('2019 Iron 1200 $5000',now='t2')
        self.assertEqual(self.db.execute('SELECT price_aud,last_seen FROM listings').fetchone(),(15000,'t1'))

    def test_url_alias_and_unsafe(self):
        self.assertEqual(tracker.clean_link('https://m.facebook.com/marketplace/item/123/?ref=search'), 'https://facebook.com/marketplace/item/123')
        with self.assertRaises(ValueError): tracker.clean_link('javascript:alert(1)')
        with self.assertRaises(ValueError): tracker.clean_link('https://user:pass@example.com/x')

    def test_feed_content_and_alternate(self):
        feed='<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>2019 Iron 1200</title><content>$15000</content><link rel="self" href="x"/><link rel="alternate" href="https://example.com"/></entry></feed>'
        self.assertEqual(list(tracker.parse_feed(feed))[0],('2019 Iron 1200','$15000','https://example.com'))
        with self.assertRaises(ValueError): list(tracker.parse_feed('<html/>'))

    def test_search_pages_foreign_and_bad_domains_rejected(self):
        for url in ['https://www.bikesales.com.au/bikes/harley-davidson/','https://bikesales.com.au.evil.com/bikes/details/test','https://facebook.com/marketplace/item/123']:
            self.assertFalse(tracker.eligible_feed_link(url,'2019 Iron 1200 USA'))
        self.assertTrue(tracker.eligible_feed_link('https://facebook.com/marketplace/item/123','2019 Iron 1200 QLD'))

    def test_source_errors_not_empty_success(self):
        client=MagicMock(); client.get.side_effect=ValueError('blocked')
        records,state=discover_dealer(client,'test','https://example.com/sitemap.xml','imotor')
        self.assertEqual(state['status'],'failed'); self.assertEqual(records,[])
        client.get.side_effect=None;client.get.return_value='<urlset/>'
        self.assertEqual(discover_dealer(client,'test','https://example.com/sitemap.xml','imotor')[1]['status'],'failed')

    def test_robots_denial_stops_fetch(self):
        client=PublicClient()
        with patch.object(client,'raw',return_value='User-agent: *\nDisallow: /') as raw:
            with self.assertRaises(ValueError): client.get('https://example.com/listing')
            self.assertEqual(raw.call_count,1)

    def test_dealer_structured_data_and_unavailable(self):
        item=dict(year=2019,make='Harley-Davidson',model='Iron 1200',price=18000,odometer=12345,sellerSuburb='Brisbane',sellerState='QLD',sellerPostcode='4000',active=True,archived=False)
        body='window.pageData='+json.dumps({'result':{'serverData':{'stockItem':item}}})+';'
        r=parse_dealer(body,'https://example.com','imotor')
        self.assertEqual((r['price_aud'],r['kilometres'],r['location']),(18000,12345,'Brisbane, QLD, 4000'))
        with self.assertRaises(ValueError):parse_dealer('<html>Challenge</html>','https://example.com','imotor')

    def test_email_receipts_and_retry(self):
        self.add()
        env=dict(SMTP_HOST='smtp.example.com',SMTP_USER='a@example.com',SMTP_PASSWORD='test',MAIL_TO='b@example.com')
        with patch.dict(os.environ,env),patch('tracker.smtplib.SMTP') as smtp:
            smtp.return_value.__enter__.return_value.send_message.side_effect=OSError('down')
            with self.assertRaises(OSError):tracker.notify(self.db,'t2')
            self.assertIsNone(self.db.execute('SELECT sent_at FROM events').fetchone()[0])
            smtp.return_value.__enter__.return_value.send_message.side_effect=None
            self.assertEqual(tracker.notify(self.db,'t3'),'sent 1 events')
            self.assertEqual(tracker.notify(self.db,'t4'),'no pending events')

    def test_report_escapes_script(self):
        self.add(description='</script><script>alert(1)</script>')
        report=dict(status='ok',observations=1,observed_at='2026-10-13',sources=[],note='</script>')
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'report.html').write_text((tracker.ROOT/'report.html').read_text(encoding='utf-8'),encoding='utf-8')
            with patch.object(tracker,'ROOT',root),patch.object(tracker,'OUTPUT',root/'results.csv'):
                tracker.export(self.db,report)
                output=(root/'docs/index.html').read_text(encoding='utf-8')
                self.assertIn('\\u003c/script>',output)

    def test_report_model_choices(self):
        class Options(HTMLParser):
            def __init__(self):
                super().__init__(); self.model=False; self.option=False; self.values=[]
            def handle_starttag(self,tag,attrs):
                if tag=='select': self.model=dict(attrs).get('id')=='model'
                if tag=='option' and self.model: self.option=True
            def handle_endtag(self,tag):
                if tag=='select': self.model=False
                if tag=='option': self.option=False
            def handle_data(self,data):
                if self.model and self.option:self.values.append(data)
        parser=Options();parser.feed((tracker.ROOT/'report.html').read_text(encoding='utf-8'))
        self.assertEqual(parser.values,['Both models','Iron 1200','Seventy-Two'])

if __name__=='__main__': unittest.main()
