"""Low-frequency, public dealer inventory; no browser sessions or private APIs."""
import html
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
import xml.etree.ElementTree as ET

AGENT = 'HarleyListingMonitor/2.0'
DEALERS = [
    ('Bikebiz', 'https://www.bikebiz.com.au/used-bikes-sitemap.xml', 'bikebiz'),
    ('Brisans', 'https://www.stock.brisans.com.au/sitemap-stock.xml', 'imotor'),
    ('Harley-Heaven', 'https://www.stock.harleyheaven.com.au/sitemap-stock.xml', 'imotor'),
]
TARGET = re.compile(r'xl[- ]?1200[- ]?(?:ns|v)\b|iron[- ]?1200|seventy[- ]?two|sportster[- ]72', re.I)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('Redirect refused; review source URL')


class PublicClient:
    def __init__(self):
        self.robots = {}
        self.last_request = {}
        self.opener = urllib.request.build_opener(NoRedirect)

    def raw(self, url):
        p = urllib.parse.urlsplit(url)
        if p.scheme != 'https' or p.username or p.password:
            raise ValueError('HTTPS without credentials required')
        delay = max(0, 1.0 - (time.monotonic() - self.last_request.get(p.netloc, 0)))
        time.sleep(delay)
        self.last_request[p.netloc] = time.monotonic()
        req = urllib.request.Request(url, headers={'User-Agent': AGENT})
        with self.opener.open(req, timeout=20) as response:
            data = response.read(5_000_001)
        if len(data) > 5_000_000:
            raise ValueError('Response exceeds size limit')
        return data.decode('utf-8-sig')

    def get(self, url):
        p = urllib.parse.urlsplit(url)
        origin = f'{p.scheme}://{p.netloc}'
        if origin not in self.robots:
            # Fail closed if robots cannot be retrieved, rather than assuming permission.
            policy = urllib.robotparser.RobotFileParser()
            policy.parse(self.raw(origin + '/robots.txt').splitlines())
            self.robots[origin] = policy
        policy = self.robots[origin]
        if not policy.can_fetch(AGENT, url):
            raise ValueError('Disallowed by robots.txt')
        delay = policy.crawl_delay(AGENT) or 0
        if delay > 1:
            time.sleep(max(0, delay - (time.monotonic() - self.last_request.get(p.netloc, 0))))
        return self.raw(url)


def plain(value):
    value = re.sub(r'<(?:script|style)\b[^>]*>.*?</(?:script|style)>', ' ', value, flags=re.S | re.I)
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]*>', ' ', value))).strip()


def parse_dealer(body, url, kind):
    if kind == 'imotor':
        if 'window.pageData=' not in body:
            raise ValueError('Dealer page structure changed: missing stock data')
        data = json.JSONDecoder().raw_decode(body.split('window.pageData=', 1)[1])[0]
        item = data['result']['serverData']['stockItem']
        title = f"{item['year']} {item['make']} {item['model']}"
        return dict(title=title, description='', url=url,
                    year=item['year'], price_aud=item.get('price') or None,
                    kilometres=item.get('odometer'),
                    location=', '.join(str(item.get(k) or '') for k in ['sellerSuburb', 'sellerState', 'sellerPostcode']).strip(', '),
                    vin=item.get('vin'), stock_number=item.get('stockNumber'),
                    seller=item.get('sellerName'), price_basis=item.get('priceQualifier'),
                    status='Seller page observed' if item.get('active') is True and not item.get('archived') else 'Seller marked unavailable')
    # Scope extraction to the actual bike section, away from navigation and related products.
    text = plain(body)
    match = re.search(r'\b(20\d{2} Harley-Davidson (?:Iron|Seventy).*?)\s+\$\s*([\d,]+)\s+Body\b', text)
    if not match:
        raise ValueError('Dealer page structure changed: missing bike/price block')
    detail = text[match.start():].split('Contact us Apply for finance', 1)[0]
    km = re.search(r'Odometer\s+([\d,]+)', detail)
    location = re.search(r'Location\s+(.*?)\s+Contact us', detail)
    if not location:
        location = re.search(r'Location\s+(.*)$', detail)
    stock = re.search(r'Stock#\s+(\S+)', detail)
    return dict(title=match[1], description='', url=url, year=int(match[1][:4]),
                price_aud=int(match[2].replace(',', '')),
                kilometres=int(km[1].replace(',', '')) if km else None,
                location=location[1] if location else None,
                seller='Bikebiz', stock_number=stock[1] if stock else None,
                status='Seller page observed', price_basis='As advertised')


def discover_dealer(client, name, sitemap, kind, previous_urls=()):
    health = dict(source=name, status='ok', inventory_urls=0, candidates=0, observed=0, errors=[])
    records = []
    try:
        root = ET.fromstring(client.get(sitemap))
        if root.tag.split('}')[-1] != 'urlset':
            raise ValueError('Expected stock URL sitemap')
        urls = [el.text for el in root.iter() if el.tag.split('}')[-1] == 'loc' and el.text]
        health['inventory_urls'] = len(urls)
        if not urls:
            raise ValueError('Empty inventory sitemap; cannot validate source')
        origin = urllib.parse.urlsplit(sitemap).netloc
        candidates = {u for u in urls if TARGET.search(urllib.parse.unquote(u))}
        candidates.update(previous_urls)
        health['candidates'] = len(candidates)
        if len(candidates) > 60:
            raise ValueError('Candidate safety limit exceeded; review source')
        for url in sorted(candidates):
            try:
                if urllib.parse.urlsplit(url).netloc != origin:
                    raise ValueError('Cross-origin sitemap URL refused')
                record = parse_dealer(client.get(url), url, kind)
                record['source'] = name
                records.append(record)
                health['observed'] += 1
            except urllib.error.HTTPError as exc:
                if exc.code in (404, 410):
                    records.append(dict(url=url, unavailable=True))
                else:
                    health['errors'].append(f'HTTP {exc.code}: {url}')
            except Exception as exc:
                health['errors'].append(f'{type(exc).__name__}: {url}')
        if health['errors']:
            health['status'] = 'failed'
    except Exception as exc:
        health['status'] = 'failed'
        health['errors'].append(f'{type(exc).__name__}: inventory unavailable or invalid')
    return records, health
