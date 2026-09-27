"""Provider worker. Reads one JSON request on stdin; writes one JSON result.
Network and image decoding run outside GNOME Shell. No wallpaper settings are changed here.
"""
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import random
import re
import socket
import sys
import urllib.error
import urllib.parse
import urllib.request

MAX_IMAGE = 25 * 1024 * 1024
MAX_JSON = 2 * 1024 * 1024
CATEGORIES = {
    'nature': 'nature landscape', 'mountains': 'mountains', 'ocean': 'ocean beach',
    'forest': 'forest trees', 'animals': 'animals wildlife', 'city': 'city architecture',
    'space': 'space astronomy', 'abstract': 'abstract',
}


def public_url(url):
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != 'https' or not parts.hostname or parts.username or parts.password or parts.port not in (None, 443):
        raise ValueError('Provider returned an invalid HTTPS image address')
    addresses = socket.getaddrinfo(parts.hostname, 443, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
        raise ValueError('Provider image address must be on the public internet')
    return url


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        public_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(url, limit):
    public_url(url)
    request = urllib.request.Request(url, headers={'User-Agent': 'LunaWallpaper/0.1', 'Accept': '*/*'})
    try:
        with urllib.request.build_opener(SafeRedirect()).open(request, timeout=25) as response:
            data = response.read(limit + 1)
            if len(data) > limit:
                raise ValueError('Provider response exceeds the download size limit')
            return data
    except urllib.error.HTTPError as error:
        raise ValueError(f'Provider returned HTTP {error.code}; check its settings or try again later') from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise ValueError('Cannot reach the provider; check your connection and try again') from None


def api(base, params):
    return json.loads(fetch(base + '?' + urllib.parse.urlencode(params), MAX_JSON))


def query_for(config):
    categories = [c for c in config.get('categories', []) if c in CATEGORIES]
    category = CATEGORIES[random.choice(categories)] if categories else ''
    return ' '.join(filter(None, [category, config.get('query', '').strip()]))


def bing(config, daily=False):
    market = config.get('bing-market', 'en-US')
    if not re.fullmatch(r'[a-z]{2}-[A-Z]{2}', market):
        raise ValueError('Bing market must look like en-US or sv-SE')
    images = api('https://www.bing.com/HPImageArchive.aspx', {'format': 'js', 'idx': 0, 'n': 1 if daily else 8, 'mkt': market}).get('images', [])
    categories = config.get('categories', [])
    query = config.get('query', '').casefold().split()
    if not daily:
        def matches(item):
            text = f"{item.get('title', '')} {item.get('copyright', '')}".casefold()
            return (not categories or any(any(word in text for word in CATEGORIES.get(c, c).split()) for c in categories)) and all(word in text for word in query)
        images = [item for item in images if matches(item)]
    return [{'url': urllib.parse.urljoin('https://www.bing.com', item['url']),
             'title': item.get('copyright') or item.get('title', 'Bing wallpaper'),
             'source': item.get('copyrightlink', 'https://www.bing.com'), 'provider': 'Bing'} for item in images]


def wallhaven(config):
    data = api('https://wallhaven.cc/api/v1/search', {'q': query_for(config), 'categories': '100', 'purity': '100', 'sorting': 'random', 'atleast': '1920x1080'})
    return [{'url': item['path'], 'title': f"Wallhaven {item['id']} · {item.get('resolution', '')}",
             'source': item['url'], 'provider': 'Wallhaven'} for item in data.get('data', [])]


def candidates(config):
    if config.get('action') == 'daily':
        return bing(config, daily=True)
    providers = list(dict.fromkeys(config.get('providers', ['bing'])))
    random.shuffle(providers)
    errors = []
    for name in providers:
        if name not in ('bing', 'wallhaven'):
            continue
        try:
            results = globals()[name](config)
            random.shuffle(results)
            history = list(dict.fromkeys([config.get('current-url', ''), *config.get('recent-urls', [])]))
            recency = {url: len(history) - index for index, url in enumerate(history) if url}
            results.sort(key=lambda image: recency.get(image['url'], 0))
            if results:
                yield from results[:5]
            else:
                errors.append(f'{name}: no matching images')
        except (ValueError, KeyError, TypeError) as error:
            errors.append(f'{name}: {error}')
    if errors:
        raise ValueError('; '.join(errors))


def save_image(data, directory):
    import gi
    gi.require_version('GdkPixbuf', '2.0')
    from gi.repository import GdkPixbuf
    loader = GdkPixbuf.PixbufLoader.new()
    too_large = []
    def size_prepared(obj, width, height):
        if width * height > 80_000_000 or width > 20000 or height > 20000:
            too_large.append(True)
            obj.set_size(1, 1)
    loader.connect('size-prepared', size_prepared)
    try:
        loader.write(data)
        loader.close()
        pixbuf = loader.get_pixbuf()
        if too_large or pixbuf is None or pixbuf.get_width() < 640 or pixbuf.get_height() < 360:
            raise ValueError('Image has unsupported dimensions (minimum 640 × 360)')
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        path = directory / (hashlib.sha256(data).hexdigest() + '.jpg')
        temporary = path.with_suffix('.tmp')
        pixbuf.savev(str(temporary), 'jpeg', ['quality'], ['95'])
        os.chmod(temporary, 0o600)
        temporary.replace(path)
        return str(path)
    except Exception:
        raise ValueError('Downloaded file is not a supported wallpaper image') from None


def run(config):
    if config.get('action') == 'daily':
        images = iter(bing(config, True))
    else:
        images = candidates(config)
    failures = []
    for item in images:
        try:
            item['path'] = save_image(fetch(item['url'], MAX_IMAGE), config['directory'])
            return item
        except ValueError as error:
            failures.append(str(error))
    raise ValueError(failures[-1] if failures else 'No matching images. Try other categories or providers.')


if __name__ == '__main__':
    try:
        print(json.dumps({'ok': True, **run(json.load(sys.stdin))}))
    except Exception as error:
        print(json.dumps({'ok': False, 'error': str(error) if isinstance(error, ValueError) else 'Unexpected provider response; try another provider'}))
        sys.exit(1)
