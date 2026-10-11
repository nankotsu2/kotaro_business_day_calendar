"""11月のスキャンから手書きの「休」マークを切り出す。

出力:
  marks/*.png      確認用(1枚ずつ)
  marks_sheet.png  一覧(確認用)
  marks.json       アプリに埋め込むデータ(PNG の data URI とマス内の位置)

座標はすべて「基準座標」= 11月スキャン(934px幅)の傾きを除いたもの。
アプリのカレンダーもこの基準座標で描くので、マークを元のマス内の位置にそのまま置ける。
"""
import base64, io, json, os
import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage as ndi

HERE = os.path.dirname(os.path.abspath(__file__))
SS = 2  # 切り出し解像度(基準座標の何倍か)

# 休業日: (スキャン, [(列, 行), ...])  行0 = 1週目
# 形がばらつきすぎないよう、11月のサンプルだけを使う(ユーザーの指定)。
# 10月を足すときは '2026-10': ('scan_2026-10.png', [(4, 0), (5, 0), (6, 0), (0, 1), (1, 1), (1, 2), (1, 3), (2, 3), (1, 4)])
SCANS = {
    '2026-11': ('scan_2026-11.png', [(1, 0), (1, 1), (2, 1), (3, 1), (4, 1), (1, 2), (1, 3), (1, 4)]),
}


def load(path):
    return np.asarray(Image.open(os.path.join(HERE, path)).convert('RGB')).astype(float)


def gray_mask(a):
    mx, mn, mean = a.max(2), a.min(2), a.mean(2)
    return (mx - mn < 30) & (mean < 215)


def fit_grid(a):
    """罫線(列ごとに分かれた横線)から格子を当てはめる。
    y = y0 + k*rp + t*x、 x_left = x0 + c*cp + s*y、 x_right = x_left + w"""
    g = gray_mask(a)
    H, W = g.shape
    # まず粗い列位置と行位置
    cnt = g.sum(1)
    rows = [y for y in range(H) if cnt[y] > W * 0.2]
    ys = []
    for y in rows:
        if ys and y - ys[-1][-1] <= 2:
            ys[-1].append(y)
        else:
            ys.append([y])
    ys = [np.mean(v) for v in ys]
    # 7本(見出し下＋6行)を拾う。欠けていたら等間隔で補う
    y_first, y_last = ys[0], ys[-1]
    rp0 = (y_last - y_first) / 6
    yk = [y_first + k * rp0 for k in range(7)]
    band = g[int(y_last) - 1:int(y_last) + 2].any(0)
    segs, s = [], None
    for x in range(W):
        if band[x] and s is None:
            s = x
        if not band[x] and s is not None:
            if x - s > 30:
                segs.append((s, x - 1))
            s = None
    cp0 = 128.0
    x00 = segs[-1][0] - 6 * cp0  # 右端の列から逆算(左下は欠けることがある)

    Ay, by, Ax, bx = [], [], [], []
    for k in range(7):
        for c in range(7):
            xl = int(x00 + c * cp0 + 8)
            xr = int(x00 + c * cp0 + 110)
            y_lo, y_hi = int(yk[k] - 6), int(yk[k] + 7)
            win = g[y_lo:y_hi, xl:xr]
            prof = win.sum(1)
            if prof.max() < (xr - xl) * 0.8:
                continue  # マークで隠れている
            yy = y_lo + np.average(np.arange(len(prof)), weights=prof ** 4)
            Ay.append([1, k, (xl + xr) / 2]); by.append(yy)
            # 線の左端・右端(列の中央を含むひと続きの線)
            row = g[int(round(yy)) - 1:int(round(yy)) + 2, :].any(0)
            mid = int(x00 + c * cp0 + 58)
            if not row[mid]:
                continue
            lo = mid
            while lo > 0 and row[lo - 1]:
                lo -= 1
            hi = mid
            while hi < W - 1 and row[hi + 1]:
                hi += 1
            if hi - lo < 100 or hi - lo > 125:
                continue
            Ax.append([1, c, yy, 0]); bx.append(lo)
            Ax.append([1, c, yy, 1]); bx.append(hi + 1)
    y0, rp, t = np.linalg.lstsq(np.array(Ay), np.array(by), rcond=None)[0]
    x0, cp, s, w = np.linalg.lstsq(np.array(Ax), np.array(bx), rcond=None)[0]
    return dict(x0=x0, cp=cp, s=s, w=w, y0=y0, rp=rp, t=t)


def canon_to_image_affine(grid, base):
    """基準座標(×SS)→スキャン座標のアフィン係数(PIL の AFFINE 用)"""
    # 基準座標 X,Y → 格子座標 c,k
    #   c = (X - bx0)/bcp,  k = (Y - by0)/brp
    # スキャン: x - s*y = x0 + c*cp,  -t*x + y = y0 + k*rp
    M = np.array([[1, -grid['s']], [-grid['t'], 1]])
    Minv = np.linalg.inv(M)
    # [x0 + c*cp, y0 + k*rp] を X,Y の一次式に
    # c = X/(SS*bcp) - bx0/bcp
    L = np.array([[grid['cp'] / (SS * base['cp']), 0], [0, grid['rp'] / (SS * base['rp'])]])
    off = np.array([grid['x0'] - grid['cp'] * base['x0'] / base['cp'],
                    grid['y0'] - grid['rp'] * base['y0'] / base['rp']])
    A = Minv @ L
    o = Minv @ off
    return (A[0, 0], A[0, 1], o[0], A[1, 0], A[1, 1], o[1])


def ink_alpha(a, base):
    """赤マーカーの濃さ(0..1)。下地の白・灰色・黒には影響されにくい比率で見る。"""
    R, G, B = a[..., 0], a[..., 1], a[..., 2]
    ratio = ((G + B) / 2) / np.maximum(R, 1)
    raw = np.clip((1 - ratio) / (1 - 0.37), 0, 1)
    raw[R < 40] = 0
    # 印刷の赤(日曜・祝日)は raw が 0.7 程度までしか上がらない。
    # 確実にマーカーの部分(core)から、つながっている薄い部分へ少しだけ広げる。
    core = raw > 0.72
    lab, n = ndi.label(core)
    sizes = ndi.sum(core, lab, range(1, n + 1))
    core = np.isin(lab, np.nonzero(sizes >= 12 * SS * SS)[0] + 1)
    near = ndi.binary_dilation(core, iterations=5 * SS)
    lab, n = ndi.label((raw > 0.4) & near)
    hit = np.unique(lab[core & (lab > 0)])
    grown = np.isin(lab, hit)
    gate = ndi.binary_dilation(grown, iterations=SS)
    alpha = np.where(gate, raw, 0)
    # 印刷の数字・罫線の縁はスキャンの色ずれで赤みを帯びる。
    # その周りではマーカーの芯(raw が高い所)だけを残す。
    lum = a.mean(2)
    printed = (lum < 175) & (raw < 0.45)
    fringe = ndi.binary_dilation(printed, iterations=2 * SS)
    beside_core = ndi.binary_dilation(core, iterations=int(1.5 * SS))
    alpha[fringe & (raw < 0.72) & ~beside_core] = 0
    # 罫線がマーカーの線を横切っていた所は、上の処理で細い隙間になる。
    # 罫線の上下どちらにもインクがあれば、上下の濃さで埋める
    hz = 3 * SS
    for k in range(7):
        y = int(round((base['y0'] + k * base['rp']) * SS))
        above = alpha[y - hz - 1]
        below = alpha[y + hz + 1]
        fill = np.where((above > 0.3) & (below > 0.3), np.minimum(above, below), 0)
        alpha[y - hz:y + hz + 1] = np.maximum(alpha[y - hz:y + hz + 1], fill[None, :])
    alpha[alpha < 0.08] = 0
    return alpha


def ring_path(alpha, cx, cy, ax, ay, n_th=360):
    """楕円座標で丸の線をたどる(動的計画法)。戻り値: 角度ごとの ρ"""
    rho = np.linspace(0.45, 1.6, 116)
    th = np.linspace(0, 2 * np.pi, n_th, endpoint=False)
    X = cx + np.outer(np.cos(th), rho) * ax
    Y = cy + np.outer(np.sin(th), rho) * ay
    P = ndi.map_coordinates(alpha, [Y, X], order=1, mode='constant')
    P = P - 0.6 * (rho[None, :] - 1.0) ** 2  # 大きさの事前分布(弱め)
    P3 = np.concatenate([P, P, P], 0)
    n, m = P3.shape
    D = 3
    score = P3[0].copy()
    back = np.zeros((n, m), int)
    for i in range(1, n):
        best = np.full(m, -1e9)
        arg = np.zeros(m, int)
        for d in range(-D, D + 1):
            sh = np.roll(score, d) - 0.04 * abs(d)
            if d > 0:
                sh[:d] = -1e9
            elif d < 0:
                sh[d:] = -1e9
            upd = sh > best
            best[upd] = sh[upd]
            arg[upd] = (np.arange(m) - d)[upd]
        score = best + P3[i]
        back[i] = arg
    j = np.zeros(n, int)
    j[-1] = int(np.argmax(score))
    for i in range(n - 1, 0, -1):
        j[i - 1] = back[i, j[i]]
    jj = j[n_th:2 * n_th]
    return th, rho[jj], rho


def band_edges(alpha, cx, cy, ax, ay, th, rpath):
    """丸の線の内側・外側の縁(ρ)"""
    step = 0.005
    inner = np.empty_like(rpath)
    outer = np.empty_like(rpath)
    for i, (t, r) in enumerate(zip(th, rpath)):
        def val(rr):
            return ndi.map_coordinates(alpha, [[cy + rr * ay * np.sin(t)], [cx + rr * ax * np.cos(t)]], order=1)[0]
        ro = r
        while ro < r + 0.6 and val(ro + step) > 0.2:
            ro += step
        ri = r
        while ri > r - 0.4 and val(ri - step) > 0.2:
            ri -= step
        inner[i], outer[i] = ri, ro
    return inner, outer


def circ_median(x, k):
    pad = np.concatenate([x[-k:], x, x[:k]])
    return ndi.median_filter(pad, size=2 * k + 1)[k:-k]


def analyze(alpha, cell_c, cell_r, base):
    cx = (base['x0'] + cell_c * base['cp'] + base['w'] / 2) * SS
    cy = (base['y0'] + (cell_r + 0.5) * base['rp']) * SS
    ax, ay = 0.53 * base['cp'] * SS, 0.52 * base['rp'] * SS
    for _ in range(3):
        th, rpath, _ = ring_path(alpha, cx, cy, ax, ay)
        px = cx + rpath * ax * np.cos(th)
        py = cy + rpath * ay * np.sin(th)
        cx, cy = px.mean(), py.mean()
        ax = np.sqrt(2) * px.std()
        ay = np.sqrt(2) * py.std()
    th, rpath, _ = ring_path(alpha, cx, cy, ax, ay)
    inner, outer = band_edges(alpha, cx, cy, ax, ay, th, rpath)
    ext = outer - rpath
    # 隣の丸とくっついて太くなっている所は、内側の縁から普通の太さで切る
    width = outer - inner
    wmed = np.median(width)
    fat = width > wmed * 1.3
    outer = np.where(fat, np.maximum(inner + wmed * 1.05, rpath + 0.01), outer)
    cap = np.median(ext) * 1.3 + 0.01
    outer = np.minimum(outer, rpath + cap)
    # 線の中心をなめらかな曲線で近似し、そこから普通の線幅より外の出っ張り(隣の丸の名残)を切る
    F = np.fft.rfft(rpath)
    F[9:] = 0
    smooth = np.fft.irfft(F, len(rpath))
    ext_norm = np.median(ext[~fat])
    outer = np.minimum(outer, smooth + ext_norm * 1.35 + 0.01)
    outer = circ_median(outer, 4)
    in_ext = rpath - inner
    inner_ext = np.minimum(in_ext, np.median(in_ext) * 1.3 + 0.01)
    rp = circ_median(rpath, 3)
    # 線の中心から半幅ぶん(隣のマークの線を除くとき用。合体部分を含まない細めの帯)
    half = np.median(ext + in_ext) / 2
    return dict(cx=cx, cy=cy, ax=ax, ay=ay, th=th, rpath=rp, half=half,
                outer=outer, inner=circ_median(rpath - inner_ext, 4),
                tight_lo=rp - half * 1.1, tight_hi=rp + half * 1.1)


def centerline_dist(m, r, idx):
    """丸の線の中心からの距離(px のおおよそ)"""
    t = m['th'][idx]
    px_per_rho = np.hypot(m['ax'] * np.cos(t), m['ay'] * np.sin(t))
    return np.abs(r - m['rpath'][idx]) * px_per_rho, m['half'] * px_per_rho


def polar_of(shape, m):
    H, W = shape
    Y, X = np.mgrid[0:H, 0:W].astype(float)
    dx, dy = (X - m['cx']) / m['ax'], (Y - m['cy']) / m['ay']
    r = np.hypot(dx, dy)
    t = np.mod(np.arctan2(dy, dx), 2 * np.pi)
    idx = np.round(t / (2 * np.pi) * len(m['th'])).astype(int) % len(m['th'])
    return r, idx


def circ_filter(x, fn, size):
    k = size // 2
    pad = np.concatenate([x[-k:], x, x[:k]])
    return fn(pad, size=size)[k:-k]


def smooth_ring(ma, m, rr, idx):
    """丸の線の縁をなめらかにする。

    切り出しで隣の丸や罫線の所を切ったために、丸の縁に欠け(ギザギザ)が残ることがある。
    角度ごとに線の内側・外側の縁を測り、細い欠けを埋めるようになめらかにしてから、
    欠けていた所は周りと同じくらいの濃さのインクで埋め、外にはみ出た細かい破片は落とす。
    中の「休」には手を付けない。
    """
    th = m['th']
    n = len(th)
    rho = np.arange(0.45, 1.6, 0.004)
    X = m['cx'] + np.outer(np.cos(th), rho) * m['ax']
    Y = m['cy'] + np.outer(np.sin(th), rho) * m['ay']
    P = ndi.map_coordinates(ma, [Y, X], order=1, mode='constant')
    inner = np.full(n, np.nan)
    outer = np.full(n, np.nan)
    for i in range(n):
        j0 = int(np.argmin(np.abs(rho - m['rpath'][i])))
        lo, hi = max(j0 - 40, 0), min(j0 + 40, len(rho) - 1)
        jc = lo + int(np.argmax(P[i, lo:hi + 1]))
        if P[i, jc] < 0.3:
            continue  # この角度では線が途切れている
        # 罫線の跡などで線の中に細い隙間があっても、またいで続ける
        ink = P[i] > 0.25
        gap = 8
        a = jc
        while a > 0 and ink[max(a - gap, 0):a].any():
            a = max(a - gap, 0) + int(np.nonzero(ink[max(a - gap, 0):a])[0].min())
        b = jc
        while b < len(rho) - 1 and ink[b + 1:b + 1 + gap].any():
            b = b + 1 + int(np.nonzero(ink[b + 1:b + 1 + gap])[0].max())
        inner[i], outer[i] = rho[a], rho[b]
    ok = ~np.isnan(outer)
    if ok.sum() < n * 0.6:
        return ma
    # 途切れた角度は前後からつなぐ
    t = np.arange(n)
    for arr in (inner, outer):
        arr[~ok] = np.interp(t[~ok], np.concatenate([t[ok] - n, t[ok], t[ok] + n]), np.tile(arr[ok], 3))
    wmed = np.median((outer - inner)[ok])   # ふだんの線の太さ
    # 外側の縁: 欠け(へこみ)を埋めてから、出っ張りを削る
    outer = circ_filter(outer, ndi.maximum_filter1d, 13)
    outer = circ_filter(outer, ndi.minimum_filter1d, 13)
    outer = circ_filter(outer, ndi.minimum_filter1d, 25)
    outer = circ_filter(outer, ndi.maximum_filter1d, 25)
    outer = circ_filter(outer, ndi.median_filter, 9)
    # 内側の縁: 「休」の線がつながっている所の落ち込みは無視する
    inner = circ_filter(inner, ndi.median_filter, 15)
    pad = 6
    outer = ndi.gaussian_filter1d(np.concatenate([outer[-pad:], outer, outer[:pad]]), 2)[pad:-pad]
    inner = ndi.gaussian_filter1d(np.concatenate([inner[-pad:], inner, inner[:pad]]), 2)[pad:-pad]
    # 線の中に下の数字の跡などで薄い所があっても、外縁からふだんの太さまでは線とみなして埋める
    inner = np.minimum(inner, outer - wmed)

    px = np.hypot(m['ax'] * np.cos(th), m['ay'] * np.sin(th))[idx]   # ρ 1 あたりの px
    edge = 1.0 * SS
    in_outer = np.clip((outer[idx] - rr) * px / edge + 0.5, 0, 1)
    in_band = in_outer * np.clip((rr - inner[idx]) * px / edge + 0.5, 0, 1)
    # 周りの線の濃さ
    w = (ma > 0.7).astype(float)
    dens = ndi.gaussian_filter(ma * w, 4 * SS) / np.maximum(ndi.gaussian_filter(w, 4 * SS), 1e-6)
    out = np.maximum(ma, np.clip(dens, 0, 1) * in_band)
    out = out * in_outer
    # 丸の内側: 「休」の線(濃い所とその縁)だけを残し、下に印刷されていた数字の薄い影や小さな点は消す
    inside = rr < inner[idx] - 0.02
    strong = out > 0.65
    lab, n = ndi.label(strong)
    if n:
        sizes = ndi.sum(np.ones_like(out), lab, range(1, n + 1))
        strong &= ~np.isin(lab, np.nonzero(sizes < 60 * SS * SS)[0] + 1) | ~inside
    near = ndi.binary_dilation(strong, iterations=2 * SS)
    out[inside & ~near] = 0
    return out


def main():
    out_dir = os.path.join(HERE, 'marks')
    os.makedirs(out_dir, exist_ok=True)
    grids = {k: fit_grid(load(v[0])) for k, v in SCANS.items()}
    for k, g in grids.items():
        print(k, {kk: round(vv, 4) for kk, vv in g.items()})
    g = grids['2026-11']
    base = dict(x0=g['x0'], cp=g['cp'], w=g['w'], y0=g['y0'], rp=g['rp'])
    BW, BH = 934, 716

    results = []
    for key, (path, cells) in SCANS.items():
        src = Image.open(os.path.join(HERE, path)).convert('RGB')
        aff = canon_to_image_affine(grids[key], base)
        warped = src.transform((BW * SS, BH * SS), Image.AFFINE, aff, resample=Image.BICUBIC, fillcolor=(255, 255, 255))
        warped.save(os.path.join(out_dir, f'_warped_{key}.png'))
        a = np.asarray(warped).astype(float)
        alpha = ink_alpha(a, base)
        models = [analyze(alpha, c, r, base) for c, r in cells]
        polars = [polar_of(alpha.shape, m) for m in models]
        for i, ((c, r), m) in enumerate(zip(cells, models)):
            rr, idx = polars[i]
            keep = rr <= m['outer'][idx]
            own_band = keep & (rr >= m['inner'][idx])
            di, hi = centerline_dist(m, rr, idx)
            # 隣のマークの丸の線が入り込んでいたら除く
            for j, mj in enumerate(models):
                if j == i:
                    continue
                rj, ij = polars[j]
                nb = (rj <= mj['tight_hi'][ij]) & (rj >= mj['tight_lo'][ij])
                keep &= ~(nb & ~own_band & (rr > 0.75))
                # 丸同士が接して交差している所: 自分の線から外れていて、隣の線の上にあるインクは除く
                # (線が重なって共有している部分は両方に残す)
                dj, hj = centerline_dist(mj, rj, ij)
                keep &= ~((dj < hj * 2.0) & (di > hi * 1.15) & (rr > 0.75))
                # 隣の丸の内側(相手の「休」)も除く
                keep &= ~((rj < mj['tight_lo'][ij]) & ~own_band & (rr > 0.6))
            soft = ndi.gaussian_filter(keep.astype(float), 0.8 * SS)
            ma = alpha * np.clip(soft * 1.4 - 0.2, 0, 1)
            ma = smooth_ring(ma, m, rr, idx)
            ys, xs = np.nonzero(ma > 0.02)
            x1, y1, x2, y2 = xs.min() - 2, ys.min() - 2, xs.max() + 3, ys.max() + 3
            crop = ma[y1:y2, x1:x2]
            # 基準座標でのマスの左上からの位置
            cell_x = base['x0'] + c * base['cp']
            cell_y = base['y0'] + r * base['rp']
            name = f'{key}_c{c}r{r}'
            results.append(dict(name=name, alpha=crop,
                                dx=x1 / SS - cell_x, dy=y1 / SS - cell_y,
                                w=(x2 - x1) / SS, h=(y2 - y1) / SS))
            rgba = np.zeros(crop.shape + (4,), np.uint8)
            rgba[..., 0], rgba[..., 1], rgba[..., 2] = 232, 64, 74
            rgba[..., 3] = np.round(crop * 255)
            Image.fromarray(rgba).save(os.path.join(out_dir, name + '.png'))
    # 一覧
    cw, ch = int(170 * SS), int(130 * SS)
    cols = 6
    rows = (len(results) + cols - 1) // cols
    sheet = Image.new('RGB', (cw * cols, ch * rows), 'white')
    dr = ImageDraw.Draw(sheet)
    for i, rres in enumerate(results):
        im = Image.open(os.path.join(out_dir, rres['name'] + '.png'))
        sheet.paste(im, ((i % cols) * cw + 10, (i // cols) * ch + 10), im)
        dr.text(((i % cols) * cw + 4, (i // cols) * ch + 2), f"{i} {rres['name']}", fill=(0, 0, 160))
    sheet.save(os.path.join(HERE, 'marks_sheet.png'))

    data = dict(base=dict(x0=base['x0'], cp=base['cp'], w=base['w'], y0=base['y0'], rp=base['rp'], W=BW, H=BH),
                scale=SS, marks=[])
    for rres in results:
        a8 = np.round(rres['alpha'] * 255).astype(np.uint8)
        # アプリ側で色を付けるので、明るさ=濃さのグレースケールで持つ(容量節約)
        buf = io.BytesIO()
        Image.fromarray(a8, 'L').save(buf, 'PNG', optimize=True)
        data['marks'].append(dict(name=rres['name'], dx=round(rres['dx'], 2), dy=round(rres['dy'], 2),
                                  w=round(rres['w'], 2), h=round(rres['h'], 2),
                                  src='data:image/png;base64,' + base64.b64encode(buf.getvalue()).decode()))
    with open(os.path.join(HERE, 'marks.json'), 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False)
    print('marks', len(results), 'json KB', os.path.getsize(os.path.join(HERE, 'marks.json')) // 1024)


if __name__ == '__main__':
    main()
