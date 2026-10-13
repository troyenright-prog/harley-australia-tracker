#!/usr/bin/env python3
"""Free, low-frequency Australian Harley listing discovery via public RSS/search feeds.

This does not bypass logins, CAPTCHAs or access controls. Feed results are leads,
not guaranteed current listings. Provide Google Alerts RSS URLs for better coverage.
"""
import argparse
import csv
import datetime as dt
import html
import json
import os
import re
import sqlite3
import hashlib
import smtplib
import ssl
from email.message import EmailMessage
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from sources import PublicClient, DEALERS, discover_dealer, plain

ROOT = Path(__file__).resolve().parent
DB = ROOT / 'listings.sqlite3'
OUTPUT = ROOT / 'results.csv'
EXCLUDE = re.compile(r'\b(?:iron[ -]*883|xl[ -]*883\w*|forty[ -]*eight|xl[ -]*1200[ -]*(?:x|xs|c|cx|t|n|r|l))\b', re.I)
PRICE = re.compile(r'(?:A\$|AUD\s*|\$)\s*(\d{1,3}(?:,\d{3})+|\d+)(?:\.00)?(?![\d,])')
YEAR = re.compile(r'\b((?:19|20)\d{2})\b')
KM = re.compile(r'\b(\d{1,3}(?:,\d{3})+|\d+)\s*(?:km|kms|kilometres)\b', re.I)
YEARS = {'Iron 1200': range(2018, 2022), 'Seventy-Two': range(2012, 2017)}


def classify(text):
    t = plain(text).lower().replace('\u2011', '-').replace('\u2013', '-').replace('\u2014', '-')
    if EXCLUDE.search(t):
        return None
    iron = bool(re.search(r'\bxl[ -]*1200[ -]*ns\b|\biron[ -]*1200\b|\b1200[ -]+iron\b', t))
    seventy = bool(re.search(r'\bxl[ -]*1200[ -]*v\b|\bseventy[ -]*two\b|\bsportster\s+72\b|\b72\s+sportster\b', t))
    if iron and seventy:
        return None
    if iron:
        return 'Iron 1200'
    if seventy:
        return 'Seventy-Two'
    return None


def clean_link(link):
    p = urllib.parse.urlsplit(link)
    if p.scheme not in ('https', 'http') or not p.hostname or p.username or p.password:
        raise ValueError('Invalid listing URL')
    qs = urllib.parse.parse_qs(p.query)
    if p.hostname in ('www.google.com', 'www.google.com.au', 'google.com') and 'url' in qs:
        return clean_link(qs['url'][0])
    host = p.hostname.lower()
    if host in ('m.facebook.com', 'www.facebook.com', 'web.facebook.com'):
        host = 'facebook.com'
    filtered = sorted((k,v) for k, values in qs.items() for v in values if not k.startswith('utm_') and k not in ('fbclid','gclid','ref','referral_code','mibextid'))
    if host == 'facebook.com' and '/marketplace/item/' in p.path:
        filtered = []
    return urllib.parse.urlunsplit(('https', host, p.path.rstrip('/'), urllib.parse.urlencode(filtered), ''))


def fetch_feed(url):
    # Google Alerts explicitly offers RSS delivery; no search-page scraping.
    p = urllib.parse.urlsplit(url)
    if p.scheme != 'https' or p.hostname != 'www.google.com' or not p.path.startswith('/alerts/feeds/'):
        raise ValueError('Only user-created Google Alerts RSS feeds are supported')
    body = PublicClient().raw(url)
    return parse_feed(body)


def parse_feed(body):
    root = ET.fromstring(body)
    if root.tag.split('}')[-1] not in ('rss', 'feed'):
        raise ValueError('Not RSS/Atom')
    for item in root.findall('.//item'):
        yield (item.findtext('title') or '', item.findtext('description') or '', item.findtext('link') or '')
    ns = {'a': 'http://www.w3.org/2005/Atom'}
    for item in root.findall('.//a:entry',ns):
        el = next((x for x in item.findall('a:link', ns) if x.get('rel', 'alternate') == 'alternate'), None)
        yield (item.findtext('a:title', default='', namespaces=ns), item.findtext('a:content', default='', namespaces=ns) or item.findtext('a:summary', default='', namespaces=ns), el.get('href','') if el is not None else '')


def feeds():
    # Feed URLs can contain personal identifiers: keep them in a secret or ignored local file.
    config = ROOT / 'feeds.txt'
    content = os.environ.get('ALERT_FEEDS', '') + '\n'
    if config.exists(): content += config.read_text(encoding='utf-8')
    for line in content.splitlines():
        line = line.strip()
        if line and not line.startswith('#'):
            yield None, 'Custom RSS', line


def init(db):
    db.execute('''CREATE TABLE IF NOT EXISTS listings (
        url TEXT PRIMARY KEY, model TEXT NOT NULL, title TEXT NOT NULL,
        description TEXT, source TEXT, price_aud INTEGER, year INTEGER,
        kilometres INTEGER, first_seen TEXT NOT NULL, last_seen TEXT NOT NULL,
        status TEXT DEFAULT 'Discovered', last_price_change TEXT)''')
    db.execute('''CREATE TABLE IF NOT EXISTS prices (
        url TEXT NOT NULL, observed_at TEXT NOT NULL, price_aud INTEGER NOT NULL,
        PRIMARY KEY(url,observed_at,price_aud))''')
    columns = {r[1] for r in db.execute('PRAGMA table_info(listings)')}
    for column in ('location', 'vin', 'seller', 'stock_number', 'price_basis', 'duplicate_of', 'last_checked', 'last_direct_observed'):
        if column not in columns:
            db.execute(f'ALTER TABLE listings ADD COLUMN {column} TEXT')
    db.execute('''CREATE TABLE IF NOT EXISTS events (
        id TEXT PRIMARY KEY, observed_at TEXT, kind TEXT, url TEXT,
        old_price INTEGER, new_price INTEGER, sent_at TEXT)''')
    db.execute('''CREATE TABLE IF NOT EXISTS scans (
        observed_at TEXT PRIMARY KEY, report TEXT NOT NULL)''')


def nmatch(regex, s):
    m = regex.search(s)
    return int(m.group(1).replace(',','')) if m else None


def ingest(db, title, description, link, source, now, **details):
    # A precise title wins over unrelated comparison models in a description.
    model = classify(title)
    if not model or not link.startswith(('https://','http://')):
        return None
    if re.search(r'\b(?:wanted|wrecking|breaking|parts|seat|exhaust|review|manual)\b', plain(title), re.I):
        return None
    url = clean_link(link)
    combined = plain(title+' '+description)
    price, year, km = (nmatch(PRICE, combined), nmatch(YEAR, combined), nmatch(KM, combined))
    year = details.get('year') or nmatch(YEAR, plain(title))
    if year not in YEARS[model]:
        return None
    price = details.get('price_aud', price)
    km = details.get('kilometres', km)
    status = details.get('status', 'Indexed/manual lead - availability unverified')
    direct = status in ('Seller page observed', 'Seller marked unavailable')
    old_detail = db.execute('SELECT last_direct_observed FROM listings WHERE url=?', (url,)).fetchone()
    if old_detail and old_detail[0] and not direct:
        # Stale search snippets must not overwrite directly observed asking prices.
        return 'SEEN', model, None, url
    old = db.execute('SELECT price_aud FROM listings WHERE url=?',(url,)).fetchone()
    if old is None:
        db.execute('INSERT INTO listings(url,model,title,description,source,price_aud,year,kilometres,first_seen,last_seen) VALUES (?,?,?,?,?,?,?,?,?,?)',
                   (url,model,html.unescape(title),combined[:1000],source,price,year,km,now,now))
        action = 'NEW'
    else:
        changed = price is not None and old[0] is not None and old[0] != price
        db.execute('''UPDATE listings SET title=?, description=?, source=?,last_seen=?,
                      price_aud=COALESCE(?,price_aud), year=COALESCE(?,year),
                      kilometres=COALESCE(?,kilometres),last_price_change=CASE WHEN ? THEN ? ELSE last_price_change END WHERE url=?''',
                   (html.unescape(title),combined[:1000],source,now,price,year,km,changed,now,url))
        action = ('PRICE REDUCTION' if price < old[0] else 'PRICE INCREASE') if changed else 'SEEN'
    if price is not None and (old is None or old[0] != price):
        db.execute('INSERT OR IGNORE INTO prices VALUES (?,?,?)',(url,now,price))
    location = details.get('location')
    if not location:
        m = re.search(r'\b(?:NSW|QLD|VIC|TAS|SA|WA|NT|ACT)\b', combined)
        location = m[0] if m else None
    db.execute('''UPDATE listings SET status=?, location=COALESCE(?,location),
        vin=COALESCE(?,vin),seller=COALESCE(?,seller),stock_number=COALESCE(?,stock_number),
        price_basis=COALESCE(?,price_basis),last_checked=?,
        last_direct_observed=CASE WHEN ? THEN ? ELSE last_direct_observed END WHERE url=?''',
        (status,location,details.get('vin'),details.get('seller'),details.get('stock_number'),
         details.get('price_basis'),now,direct,now,url))
    vin = details.get('vin')
    duplicate = None
    if vin and re.fullmatch(r'[A-HJ-NPR-Z0-9]{17}', vin.upper()):
        duplicate = db.execute('SELECT url FROM listings WHERE upper(vin)=? AND url!=? ORDER BY first_seen,url LIMIT 1', (vin.upper(),url)).fetchone()
    if not duplicate and details.get('seller') and details.get('stock_number'):
        duplicate = db.execute('SELECT url FROM listings WHERE seller=? AND stock_number=? AND url!=? ORDER BY first_seen,url LIMIT 1',
                               (details['seller'],details['stock_number'],url)).fetchone()
    if duplicate:
        parent = db.execute('SELECT duplicate_of FROM listings WHERE url=?', (duplicate[0],)).fetchone()[0] or duplicate[0]
        if parent != url:
            db.execute('UPDATE listings SET duplicate_of=? WHERE url=?', (parent,url))
    if action in ('NEW', 'PRICE REDUCTION') and status != 'Seller marked unavailable':
        if action != 'NEW' or not duplicate:
            key = hashlib.sha256(f'{now}|{action}|{url}|{price}'.encode()).hexdigest()
            db.execute('INSERT OR IGNORE INTO events VALUES (?,?,?,?,?,?,NULL)', (key,now,action,url,old[0] if old else None,price))
    return action, model, price, url


def export(db, report):
    db.row_factory = sqlite3.Row
    rows = [dict(r) for r in db.execute('SELECT * FROM listings ORDER BY model,price_aud IS NULL,price_aud')]
    fields = ['model','year','title','price_aud','price_basis','kilometres','location','source',
              'url','first_seen','last_seen','last_direct_observed','last_checked','status','duplicate_of']
    with OUTPUT.open('w', newline='', encoding='utf-8-sig') as f:
        writer = csv.writer(f)
        writer.writerow(fields)
        # Protect spreadsheet consumers from formula injection in public listing text.
        writer.writerows([("'" + v if isinstance(v, str) and v.startswith(('=', '+', '-', '@')) else v)
                         for v in (r.get(k) for k in fields)] for r in rows)
    docs = ROOT / 'docs'
    docs.mkdir(exist_ok=True)
    template = (ROOT / 'report.html').read_text(encoding='utf-8')
    payload = json.dumps({'listings': [{k:r.get(k) for k in fields} for r in rows], 'scan': report})
    (docs / 'index.html').write_text(template.replace('__TRACKER_DATA__', payload.replace('<', '\\u003c')), encoding='utf-8')
    (ROOT / 'scan_status.json').write_text(json.dumps(report,indent=2), encoding='utf-8')
    return len(rows)


def notify(db, now):
    names = ('SMTP_HOST','SMTP_USER','SMTP_PASSWORD','MAIL_TO')
    values = [os.environ.get(n) for n in names]
    if not any(values):
        return 'not configured'
    if not all(values):
        raise ValueError('Incomplete email secrets')
    events = db.execute('''SELECT e.id,e.kind,l.model,e.old_price,e.new_price,e.url
        FROM events e JOIN listings l ON e.url=l.url WHERE e.sent_at IS NULL
        ORDER BY e.observed_at''').fetchall()
    if not events:
        return 'no pending events'
    message = EmailMessage()
    message['From'] = os.environ.get('MAIL_FROM') or values[1]
    message['To'] = values[3]
    message['Subject'] = f'Harley tracker: {len(events)} new listings / price reductions'
    lines = ['Listing leads; confirm price and availability with the seller.', '']
    for _, kind, model, old, new, url in events:
        lines.append(f'{kind}: {model} | AUD {old} -> {new}\n{url}\n')
    message.set_content('\n'.join(lines))
    with smtplib.SMTP(values[0], int(os.environ.get('SMTP_PORT') or '587'), timeout=30) as smtp:
        smtp.ehlo()
        smtp.starttls(context=ssl.create_default_context())
        smtp.ehlo()
        smtp.login(values[1], values[2])
        smtp.send_message(message)
    db.executemany('UPDATE events SET sent_at=? WHERE id=?', [(now,e[0]) for e in events])
    db.commit()
    return f'sent {len(events)} events'


def eligible_feed_link(link, text):
    try:
        p = urllib.parse.urlsplit(clean_link(link))
    except ValueError:
        return False
    host = p.hostname.removeprefix('www.')
    if host == 'bikesales.com.au':
        return p.path.startswith('/bikes/details/')
    if host == 'gumtree.com.au':
        return p.path.startswith('/s-ad/') and 'motorcycle' in p.path
    if host == 'facebook.com':
        return bool(re.match(r'/marketplace/item/\d+', p.path) and re.search(r'\b(Australia|NSW|QLD|VIC|TAS|ACT|WA|SA|NT)\b', text))
    return host in {urllib.parse.urlsplit(d[1]).hostname.removeprefix('www.') for d in DEALERS} and ('/used-bikes/' in p.path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--import-csv', help='Import manually checked Australian listing leads')
    ap.add_argument('--data-dir', type=Path, help='Separate database/report output directory')
    ap.add_argument('--notify-only', action='store_true', help='Send persisted pending notifications after saving scan history')
    args = ap.parse_args()
    global DB, OUTPUT, ROOT
    code_root = ROOT
    if args.data_dir:
        ROOT = args.data_dir.resolve()
        ROOT.mkdir(parents=True,exist_ok=True)
        DB = ROOT / 'listings.sqlite3'
        OUTPUT = ROOT / 'results.csv'
        (ROOT / 'report.html').write_text((code_root / 'report.html').read_text(encoding='utf-8'),encoding='utf-8')
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec='microseconds')
    db = sqlite3.connect(DB)
    init(db)
    if args.notify_only:
        try:
            print(json.dumps({'email': notify(db, now)}))
            return 0
        except Exception as exc:
            # SMTP errors can contain email addresses or credentials. Do not echo them.
            print(json.dumps({'email':'FAILED','type':type(exc).__name__}))
            return 1
        finally:
            db.close()
    events, health = [], []
    def accept(record):
        record = dict(record)
        url = record.pop('url')
        if record.pop('unavailable', False):
            db.execute("UPDATE listings SET status='Seller page unavailable (404/410)',last_checked=? WHERE url=?", (now,clean_link(url)))
            return False
        result = ingest(db,record.pop('title'),record.pop('description',''),url,record.pop('source','Manual'),now,**record)
        if result and result[0] != 'SEEN':
            events.append(result)
        return result is not None
    if args.import_csv:
        with open(args.import_csv,encoding='utf-8-sig',newline='') as f:
            for row in csv.DictReader(f):
                # Manual rows remain unverified; do not allow CSV to claim direct observation.
                accept({k:v for k,v in row.items() if k in ('title','description','url','source','location','seller','stock_number','vin')})
        health.append(dict(source='Manual CSV',status='manual',observed=len(events)))
    else:
        client = PublicClient()
        for name, sitemap, kind in DEALERS:
            previous = [r[0] for r in db.execute("SELECT url FROM listings WHERE source=? AND status NOT LIKE '%unavailable%'", (name,))]
            # Canonical links omit a trailing slash; request original dealership URL shape.
            if kind == 'imotor': previous = [u.rstrip('/')+'/' for u in previous]
            records, state = discover_dealer(client,name,sitemap,kind,previous)
            state['accepted'] = 0
            for record in records:
                state['accepted'] += int(accept(record))
            health.append(state)
        for i, (_, _, url) in enumerate(feeds(),1):
            state = dict(source=f'Google Alerts feed {i}',status='ok',items=0,accepted=0)
            try:
                for title, description, link in fetch_feed(url):
                    state['items'] += 1
                    if eligible_feed_link(link,title+' '+description):
                        result = ingest(db,title,description,link,'Google Alerts',now)
                        if result:
                            state['accepted'] += 1
                            if result[0] != 'SEEN': events.append(result)
            except Exception as exc:
                state.update(status='failed',error=type(exc).__name__)
            health.append(state)
    observed = sum(s.get('accepted',s.get('observed',0)) for s in health)
    failed = any(s['status'] == 'failed' for s in health)
    report = dict(observed_at=now, status='failed' if failed or not observed else 'ok',
                  observations=observed, sources=health, events=events,
                  note='Limited dealer coverage. Indexed/manual leads do not confirm availability. No automatic Bikesales, Gumtree or Facebook coverage without configured alert feeds.')
    if args.import_csv: report['status'] = 'manual import'
    if not observed: report['warning'] = 'No usable listing observations; this run does not establish that the market is empty.'
    db.execute('INSERT INTO scans VALUES (?,?)', (now,json.dumps(report)))
    db.commit()
    count = export(db,report)
    db.close()
    print(json.dumps(dict(report,records_total=count),indent=2))
    return int(report['status'] == 'failed')


if __name__ == '__main__':
    raise SystemExit(main())


