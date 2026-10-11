"""pptx から店名ロゴと住所・電話番号を取り出し、カレンダー下の余白に置くためのデータを作る。

  p.5: ロゴの3文字(拡大版)と、不要な部分を隠す白い四角
  p.4: アプリ画面のイメージ。カレンダー(9月のスキャン)の下にロゴと住所・電話番号がある

ロゴは文字の黒い部分だけを残し、背景の和紙(写真から切り貼りしたもの)は消す。
3文字の並べ方と大きさは p.4 のロゴに合わせる。

出力:
  logo.json         アプリに埋め込むデータ(基準座標での位置、ロゴの PNG、住所の行)
  logo_preview.png  確認用
"""
import base64, io, json, os, re, zipfile
import numpy as np
from PIL import Image
from scipy import ndimage as ndi

import extract_marks as em

HERE = os.path.dirname(os.path.abspath(__file__))
PPTX = os.path.join(os.path.dirname(HERE), '高太郎営業日カレンダー.pptx')
FOOTER_SLIDE = 4
LOGO_SLIDE = 5


def slide_shapes(z, n):
    xml = z.read(f'ppt/slides/slide{n}.xml').decode('utf-8')
    rels = z.read(f'ppt/slides/_rels/slide{n}.xml.rels').decode('utf-8')
    media = {}
    for m in re.finditer(r'<Relationship [^>]*>', rels):
        t = m.group(0)
        rid = re.search(r'Id="(\w+)"', t).group(1)
        media[rid] = 'ppt/media/' + re.search(r'Target="([^"]+)"', t).group(1).split('/')[-1]
    shapes = []
    for m in re.finditer(r'<p:(sp|pic)>.*?</p:\1>', xml, re.S):
        blk = m.group(0)
        xf = re.search(r'<a:off x="(-?\d+)" y="(-?\d+)"/><a:ext cx="(\d+)" cy="(\d+)"', blk)
        if not xf:
            continue
        sp = re.search(r'<p:spPr>(.*?)</p:spPr>', blk, re.S)
        emb = re.search(r'r:embed="(\w+)"', blk)
        shapes.append(dict(
            kind=m.group(1), box=tuple(int(v) for v in xf.groups()),
            media=media.get(emb.group(1)) if emb else None,
            white=bool(sp and re.search(r'<a:solidFill><a:(?:schemeClr val="bg1"|srgbClr val="FFFFFF")/?>',
                                        sp.group(1).split('<a:ln')[0])),
            paras=[''.join(re.findall(r'<a:t>([^<]*)</a:t>', p)) for p in re.findall(r'<a:p>.*?</a:p>', blk, re.S)],
            size=[int(v) for v in re.findall(r'<a:rPr[^>]*\bsz="(\d+)"', blk)],
        ))
    return shapes


def load_rgb(z, name):
    return np.asarray(Image.open(io.BytesIO(z.read(name))).convert('RGB')).astype(float)


def black_alpha(rgb):
    """漆黒の部分の濃さ(0..1)。和紙の地(明るさ100以上)は 0 にする。"""
    lum = rgb @ np.array([0.299, 0.587, 0.114])
    # 切り貼りした写真の縁に暗い線が出ていることがあるので、外周は内側の値で置き換える
    # (文字が縁まで届いている所は、そのまま縁まで続く)
    e = 3
    lum[:, :e] = lum[:, e:e + 1]
    lum[:, -e:] = lum[:, -e - 1:-e]
    lum[:e, :] = lum[e:e + 1, :]
    lum[-e:, :] = lum[-e - 1:-e, :]
    a = np.clip((88 - lum) / (88 - 42), 0, 1)
    # 和紙の模様の小さな黒い点は消す
    lab, n = ndi.label(a > 0.5)
    if n:
        sizes = ndi.sum(np.ones_like(a), lab, range(1, n + 1))
        small = np.isin(lab, np.nonzero(sizes < 40)[0] + 1)
        a[ndi.binary_dilation(small, iterations=1)] = 0
    return a


def runs(mask):
    out, s = [], None
    for i, v in enumerate(mask):
        if v and s is None:
            s = i
        if not v and s is not None:
            out.append((s, i))
            s = None
    if s is not None:
        out.append((s, len(mask)))
    return out


def main():
    z = zipfile.ZipFile(PPTX)

    # --- p.5: 3文字に白い四角の加工をして、黒だけを残す ---
    s5 = slide_shapes(z, LOGO_SLIDE)
    tiles = sorted([s for s in s5 if s['kind'] == 'pic'], key=lambda s: s['box'][0])
    masks = [s['box'] for s in s5 if s['kind'] == 'sp' and s['white']]
    assert len(tiles) == 3, f'p.{LOGO_SLIDE} のロゴ画像が3枚ではない'
    pieces = []
    for t in tiles:
        rgb = load_rgb(z, t['media'])
        h, w, _ = rgb.shape
        x, y, cx, cy = t['box']
        a = black_alpha(rgb)
        for mx, my, mcx, mcy in masks:  # 白い四角で隠れている所
            x1 = int(np.floor((mx - x) / cx * w)); x2 = int(np.ceil((mx + mcx - x) / cx * w))
            y1 = int(np.floor((my - y) / cy * h)); y2 = int(np.ceil((my + mcy - y) / cy * h))
            a[max(y1, 0):max(y2, 0), max(x1, 0):max(x2, 0)] = 0
        pieces.append(a)

    # --- p.4: ロゴの並べ方(貼ってあるロゴ画像の中の、3枚の位置と幅) ---
    s4 = slide_shapes(z, FOOTER_SLIDE)
    pics = [s for s in s4 if s['kind'] == 'pic']
    cal = max(pics, key=lambda s: s['box'][2] * s['box'][3])          # カレンダー(9月のスキャン)
    text = next(s for s in s4 if any(re.search(r'\d+-\d+-\d+', p) for p in s['paras']))
    logo = min((s for s in pics if s is not cal and s['box'][1] > cal['box'][1] + cal['box'][3] * 0.7),
               key=lambda s: abs(s['box'][1] - text['box'][1]))
    ref = load_rgb(z, logo['media'])
    lum = ref.mean(2)
    cols = runs((lum < 235).sum(0) > 5)
    assert len(cols) == 3, 'p.4 のロゴ画像から3文字の位置を読み取れない'
    top = min(int(np.nonzero((lum[:, a:b] < 235).sum(1) > 3)[0].min()) for a, b in cols)

    # p.4 の並べ方に合わせて、黒だけにした3文字を並べる(ロゴ画像の px 単位)
    placed = []
    for (a, b), piece in zip(cols, pieces):
        w = b - a
        h = round(piece.shape[0] * w / piece.shape[1])
        im = Image.fromarray(np.round(piece * 255).astype(np.uint8), 'L').resize((w, h), Image.LANCZOS)
        placed.append((a, top, im))
    x0 = cols[0][0]
    W = cols[-1][1] - x0
    H = max(t + im.height for _, t, im in placed) - top
    sheet = Image.new('L', (W, H), 0)
    for a, t, im in placed:
        sheet.paste(im, (a - x0, t - top))

    # --- 位置: スライド(EMU) → 9月スキャンの px → 基準座標(11月) ---
    sept = load_rgb(z, cal['media'])
    sg = em.fit_grid(sept)
    marks = json.load(open(os.path.join(HERE, 'marks.json'), encoding='utf-8'))
    bg = marks['base']
    emu = cal['box'][2] / sept.shape[1]          # 9月スキャン 1px あたりの EMU
    sx = lambda X: (X - cal['box'][0]) / emu
    sy = lambda Y: (Y - cal['box'][1]) / emu
    kx, ky = bg['cp'] / sg['cp'], bg['rp'] / sg['rp']
    bx = lambda x: bg['x0'] + (x - sg['x0']) * kx
    by = lambda y: bg['y0'] + (y - sg['y0']) * ky
    lpx = logo['box'][2] / ref.shape[1]          # ロゴ画像 1px あたりの EMU
    logo_x = bx(sx(logo['box'][0] + x0 * lpx))
    logo_y = by(sy(logo['box'][1] + top * lpx))
    logo_w = W * lpx / emu * kx
    logo_h = H * lpx / emu * ky

    # 住所・電話番号: PowerPoint の既定の余白(左 0.1in、上 0.05in)、メイリオ UI の行送り
    size_pt = (text['size'] or [1800])[0] / 100
    size = size_pt * 12700 / emu * ky
    left = bx(sx(text['box'][0] + 91440))
    top_text = sy(text['box'][1] + 45720)
    line_h = text['box'][3] - 91440                # 2行ぶんの高さ(EMU)
    pitch = line_h / len(text['paras']) / emu * ky
    first = by(top_text + (1061 / 1271) * (line_h / len(text['paras'])) / emu)
    lines = [dict(text=p, x=round(left, 2), y=round(first + i * pitch, 2)) for i, p in enumerate(text['paras'])]

    buf = io.BytesIO()
    sheet.save(buf, 'PNG', optimize=True)
    data = dict(logo=dict(x=round(logo_x, 2), y=round(logo_y, 2), w=round(logo_w, 2), h=round(logo_h, 2),
                          src='data:image/png;base64,' + base64.b64encode(buf.getvalue()).decode()),
                text=dict(size=round(size, 2), lines=lines))
    with open(os.path.join(HERE, 'logo.json'), 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False)

    prev = Image.new('RGB', (W, H), 'white')
    prev.paste(Image.new('RGB', (W, H), 'black'), (0, 0), sheet)
    prev.save(os.path.join(HERE, 'logo_preview.png'))
    print('logo', data['logo'] | {'src': f'{len(buf.getvalue()) // 1024}KB'})
    print('text', data['text'])


if __name__ == '__main__':
    main()
