"""docs/index.html を Chrome(iPhone 相当の画面)で開いて確認する。

  python check.py           Chrome で確認
  python check.py webkit    WebKit(iPhone の Safari と同じエンジン)で確認

  check_phone.png    スマホ画面のスクリーンショット
  check_render.png   書き出される画像(今の状態)
  check_nomarks.png  2026年11月を印なしで描いたもの
  check_overlay.png  2026年11月を印なしで描いたもの(黒)と、11月スキャン(赤)の重ね合わせ
"""
import base64, functools, http.server, io, os, sys, threading
import numpy as np
from PIL import Image
from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
DIST = os.path.join(os.path.dirname(HERE), 'docs')


def serve():
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=DIST)
    httpd = http.server.ThreadingHTTPServer(('127.0.0.1', 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def canvas_png(page):
    url = page.evaluate("document.getElementById('cal').toDataURL('image/png')")
    return Image.open(io.BytesIO(base64.b64decode(url.split(',', 1)[1]))).convert('RGB')


def wait_ready(page):
    page.wait_for_function("document.fonts.status === 'loaded' && tinted.length === MARKS.marks.length && logo")
    page.wait_for_timeout(300)


def main():
    httpd = serve()
    url = f'http://127.0.0.1:{httpd.server_address[1]}/index.html'
    with sync_playwright() as p:
        webkit = 'webkit' in sys.argv[1:]
        if webkit:
            browser = p.webkit.launch()
            ctx = browser.new_context(**p.devices['iPhone 15'], locale='ja-JP')
        else:
            browser = p.chromium.launch(channel='chrome')
            ctx = browser.new_context(viewport={'width': 390, 'height': 844}, device_scale_factor=3,
                                      is_mobile=True, has_touch=True, locale='ja-JP')
        page = ctx.new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.on('console', lambda m: m.type == 'error' and errors.append(m.text))
        page.goto(url)
        page.evaluate("localStorage.clear()")
        page.reload()
        wait_ready(page)

        # 初期状態: 翌月(月曜が自動で休み)
        sel = page.evaluate("[document.getElementById('year').value, document.getElementById('month').value]")
        n0 = page.evaluate("Object.keys(monthState(...cur()).marks).length")
        print('表示中の年月', sel, '初期の休み', n0)

        # タップで印を付ける/消す(2週目の火曜)
        box = page.locator('#cal').bounding_box()
        def tap_cell(c, r):
            bx = 21.8 + c * 128.31 + 59
            by = 125.98 + r * 87.88 + 44
            page.touchscreen.tap(box['x'] + bx / 934 * box['width'], box['y'] + by / 716 * box['height'])
        tap_cell(2, 1)
        n1 = page.evaluate("Object.keys(monthState(...cur()).marks).length")
        tap_cell(2, 1)
        n2 = page.evaluate("Object.keys(monthState(...cur()).marks).length")
        print('タップ: 付ける', n0, '->', n1, ' 消す ->', n2)
        for c, r in [(2, 1), (3, 1), (4, 1)]:
            tap_cell(c, r)
        pats = page.evaluate("Object.values(monthState(...cur()).marks).map(v => v.p)")
        print('使われた形', pats, '重複', len(pats) - len(set(pats)))

        tag = '_webkit' if webkit else ''
        page.screenshot(path=os.path.join(HERE, f'check_phone{tag}.png'), full_page=True)
        page.wait_for_timeout(300)
        canvas_png(page).save(os.path.join(HERE, f'check_render{tag}.png'))

        # 印なしの 2026年11月 をスキャンと重ねる
        page.evaluate("""() => {
            document.getElementById('year').value = 2026; document.getElementById('month').value = 11;
            store.months['2026-11'] = { marks: {} }; render();
        }""")
        page.wait_for_timeout(200)
        plain = canvas_png(page)
        plain.save(os.path.join(HERE, 'check_nomarks.png'))
        r = np.asarray(plain.convert('L')).astype(float)
        H, W = r.shape
        scan = Image.open(os.path.join(HERE, 'marks', '_warped_2026-11.png')).convert('L')
        scan = scan.resize((W, H), Image.LANCZOS)
        s = np.asarray(scan).astype(float)
        ov = np.full((H, W, 3), 255.0)
        ink_r = 1 - r / 255
        ink_s = 1 - s / 255
        ov[..., 0] -= 255 * ink_r            # 描画 = 黒っぽく(青緑)
        ov[..., 1] -= 255 * np.maximum(ink_r, ink_s)
        ov[..., 2] -= 255 * np.maximum(ink_r, ink_s)
        Image.fromarray(np.clip(ov, 0, 255).astype(np.uint8)).save(os.path.join(HERE, 'check_overlay.png'))

        # コピー(クリップボードに PNG が入るか)
        if not webkit:
            ctx.grant_permissions(['clipboard-read', 'clipboard-write'], origin=url.rsplit('/', 1)[0])
        page.click('#copy')
        page.wait_for_timeout(800)
        types = None if webkit else page.evaluate("navigator.clipboard.read().then(items => items.flatMap(i => i.types))")
        print('コピー', types, page.inner_text('#toast'))
        # 共有・保存: 共有シートに渡るファイル
        page.evaluate("""() => {
            navigator.canShare = () => true;
            navigator.share = d => { window.__shared = d.files.map(f => [f.name, f.type, f.size]); return Promise.resolve(); };
        }""")
        page.click('#share')
        page.wait_for_timeout(500)
        print('共有', page.evaluate('window.__shared'))
        # 共有シートが無い環境ではダウンロード
        page.evaluate("navigator.canShare = undefined")
        with page.expect_download() as dl:
            page.click('#share')
        d = dl.value
        path = os.path.join(HERE, 'check_download.png')
        d.save_as(path)
        im = Image.open(path)
        print('保存', d.suggested_filename, im.size, os.path.getsize(path) // 1024, 'KB')

        print('エラー', [e for e in errors if 'favicon' not in e and '404' not in e] or 'なし')
        browser.close()
    httpd.shutdown()


if __name__ == '__main__':
    main()
