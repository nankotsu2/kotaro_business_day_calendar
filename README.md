# 高太郎 営業日カレンダー

Instagram に載せる翌月の営業日カレンダー画像を、iPhone で作るアプリ。

- アプリ本体: `docs/index.html`(1ファイル。手書きマーク・店名ロゴ・フォントも中に入っている)
- デザインの分析: `デザインメモ.md`

## 使い方

1. 開くと翌月のカレンダーが出る。カレンダーに出ている月曜(定休日)には、前後の月のマスも含めて、すべて最初から「休」が付いている
   - 前の月の画面で、翌月の日付にも「休」を付けていた場合は、それも引き継ぐ
2. 日付をタップすると「休」が付く。もう一度タップすると消える
   - マークは、11月の手書きから切り出した8パターンからランダムに選ぶ(同じ月の中ではなるべく重ならず、隣のマスとも違う形になる)
3. 「共有・保存」で画像を書き出す(1440×1104 の PNG。下の余白に店名ロゴと住所・電話番号が入る)。iPhone では共有シートが開くので、Instagram を選ぶか「画像を保存」で写真アプリに入れる
   - 「コピー」は、画像をクリップボードに入れる
   - 「マークを描き直す」は、日付はそのままで、形だけを選び直す
   - 「この月をやり直す」は、最初の状態(すべての月曜に休)に戻す

印の状態は、その端末のブラウザの中に保存される。

## 作り直し(tools/)

| ファイル | 役割 |
|---|---|
| `extract_marks.py` | `scan_2026-11.png` から「休」マークを切り出して `marks.json` を作る。隣の丸とくっついていた所や罫線の跡でできた丸の縁の欠けは、なめらかに整える。一覧は `marks_sheet.png` |
| `extract_logo.py` | pptx の p.5(ロゴの3文字と、隠す部分の白い四角)から黒い文字だけを取り出し、p.4 の並べ方・位置と住所・電話番号を読んで `logo.json` を作る。確認用は `logo_preview.png` |
| `app.html` | アプリのひな形(見た目の寸法・色・祝日の計算など) |
| `build.py` | ひな形にマーク・ロゴ・フォントを埋め込み、`docs/index.html` を作る。フォントは初回だけ Google Fonts から取得して `fonts/` に保存する |
| `check.py` | iPhone 相当の画面で動作を確認する。`python check.py` は Chrome、`python check.py webkit` は Safari と同じエンジン |

```
python tools/build.py           # ひな形を直したとき
python tools/extract_marks.py   # マークを切り出し直すとき(そのあと build.py)
python tools/extract_logo.py    # pptx のロゴ・住所を直したとき(そのあと build.py)
python tools/check.py webkit    # 確認
```

必要なもの: Python と Pillow・numpy・scipy(切り出し)、playwright(確認)。

元の pptx(`高太郎営業日カレンダー.pptx`)は作成者情報が入っているのでリポジトリには入れていない。`extract_logo.py` はこの pptx を読むので、ロゴや住所を作り直すときは手元に置いて実行する。

カレンダーの文字には Noto Sans / Noto Sans JP(SIL Open Font License 1.1)の必要な文字だけを埋め込んでいる。
