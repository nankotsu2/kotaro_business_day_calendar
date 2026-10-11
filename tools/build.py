"""app.html に手書きマーク・店名ロゴ・フォントを埋め込んで、1ファイルのアプリ docs/index.html を作る。
(docs/ は GitHub Pages でそのまま配信できる場所)

フォントは Google Fonts から、カレンダーに使う文字だけを含む小さなファイルを取ってくる
(取得したものは fonts/ に保存し、次回からはそれを使う)。
可変フォントだと環境によって太さの指定が効かないことがあるので、太さを固定したものを埋め込む。
"""
import base64, json, os, re, urllib.parse, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
UA = ('Mozilla/5.0 (iPhone; CPU iPhone OS 18_5 like Mac OS X) AppleWebKit/605.1.15 '
      '(KHTML, like Gecko) Version/18.5 Mobile/15E148 Safari/604.1')

MONTHS = 'January February March April May June July August September October November December'
WEEK = 'Sun Mon Tue Wed Thu Fri Sat'
HOLIDAYS = ('元日 成人の日 建国記念の日 天皇誕生日 春分の日 昭和の日 憲法記念日 みどりの日 こどもの日 '
            '海の日 山の日 敬老の日 秋分の日 スポーツの日 文化の日 勤労感謝の日 国民の休日 振替休日')
DIGITS = '0123456789'

# (アプリ内のフォント名, Google Fonts のファミリー, 太さ, 含める文字)
def fonts(footer_text):
    return [
        ('KCal Sans', 'Noto Sans', 400, DIGITS + MONTHS + WEEK),
        ('KCal JP', 'Noto Sans JP', 400, DIGITS + HOLIDAYS + footer_text),
        ('KCal JP', 'Noto Sans JP', 500, DIGITS + '令和年'),
    ]


def chars(s):
    return ''.join(sorted(set(s.replace(' ', ''))))


def fetch(url):
    req = urllib.request.Request(url, headers={'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def font_face(name, family, weight, text):
    text = chars(text)
    cache_dir = os.path.join(HERE, 'fonts')
    os.makedirs(cache_dir, exist_ok=True)
    cache = os.path.join(cache_dir, f'{family.replace(" ", "")}-{weight}.woff2')
    cache_txt = cache + '.txt'
    if not (os.path.exists(cache) and os.path.exists(cache_txt)
            and open(cache_txt, encoding='utf-8').read() == text):
        q = urllib.parse.urlencode({'family': f'{family}:wght@{weight}', 'text': text})
        css = fetch('https://fonts.googleapis.com/css2?' + q).decode()
        url = re.search(r'url\((https://[^)]+)\)', css).group(1)
        data = fetch(url)
        assert data[:4] == b'wOF2', 'woff2 ではないファイルが返ってきた'
        with open(cache, 'wb') as f:
            f.write(data)
        with open(cache_txt, 'w', encoding='utf-8') as f:
            f.write(text)
    with open(cache, 'rb') as f:
        b64 = base64.b64encode(f.read()).decode()
    return (f'@font-face {{ font-family: "{name}"; font-weight: {weight}; font-display: block; '
            f'src: url(data:font/woff2;base64,{b64}) format("woff2"); }}')


def main():
    with open(os.path.join(HERE, 'app.html'), encoding='utf-8') as f:
        html = f.read()
    with open(os.path.join(HERE, 'marks.json'), encoding='utf-8') as f:
        marks = f.read()
    with open(os.path.join(HERE, 'logo.json'), encoding='utf-8') as f:
        footer = f.read()
    footer_text = ''.join(l['text'] for l in json.loads(footer)['text']['lines'])
    faces = '\n'.join(font_face(*x) for x in fonts(footer_text))
    for marker, value in [('/*__MARKS__*/null', marks), ('/*__FOOTER__*/null', footer), ('/*__FONTS__*/', faces)]:
        assert html.count(marker) == 1, marker
        html = html.replace(marker, value)
    out_dir = os.path.join(ROOT, 'docs')
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, 'index.html')
    with open(out, 'w', encoding='utf-8', newline='\n') as f:
        f.write(html)
    print(out, os.path.getsize(out) // 1024, 'KB')


if __name__ == '__main__':
    main()
