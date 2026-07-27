# Champion play-deck re-validation vs 2026-07 meta pool (SOT-2060)

2026-07-27。Kaggle順位向上サイクル（親 SOT-1913 の自動起案 / repo `ptcg-agent-claude` = 旧 fable
系統 / コンペ `pokemon-tcg-ai-battle`）。前サイクル SOT-1992（同名「第2次」）は「全軸=非昇格の
前例あり **＋本コンテナで engine 実走不可**」を根拠に分解不要／champion 維持で終端していた。本
サイクルはその **engine 実走不可という前提が本コンテナでは成立しない**ことを起点に、SOT-1992 が
回せなかった実測ギャップを 1 つ埋める。**champion は無変更**（評価の追加のみ）。

---

## 1. 起点 — engine は本コンテナで実走可能

`cg/libcg.so` + `data/{EN,JP}_Card_Data.csv` が本チェックアウトに揃っており、`eval/bench.py` の
smoke（greedy vs random, n=6, seed 20260727）が **fault0 で完走**（A 5 / B 1）。SOT-1992 の
「engine 実走不可（`data/` 空）」は当時のコンテナ固有の状態で、本コンテナには当てはまらない。

## 2. 選定した改善軸

直近 SOT-2055 が `decks/candidates` をメタ追従再編し `decks/meta_active/`（23 デッキ, 2026-07
メタ）を新設した。しかし SOT-2055 は候補/相手プールの再編であって、champion の **プレイデッキ**
`deck.csv`(=`26_stw_champion`) をこの新メタ盤面に対して **再選定・再検証はしていない**（champion は
常時保持の扱い）。

したがって未着手かつ本コンテナで検証可能な軸＝**champion プレイデッキを 2026-07 meta_active
プールに対して再検証する**。手法は agent 非依存のデッキ選定ラウンドロビン（`eval/compare_decks.py`,
SOT-1794；両側 greedy でデッキ強度そのものを測る）。SOT-1915 のデッキ再選定は旧プールに対する
非昇格であり、新メタプールに対する検証は本サイクルが初。

## 3. 実測 — screen → confirm ゲート

両ステージとも `decks/meta_active/` の 23 デッキ総当たり（mirror 含む）、両側 greedy、fault0。

### screen（全 23 候補, n/pair=40, seed 2060001）
`eval/results/sot2060_deck_meta_screen.json`

| # | deck | winrate | Wilson95 |
| --- | --- | --- | --- |
| **1** | **26_stw_champion** | **0.8185** | **[0.792, 0.842]** |
| 2 | 16_crustle_mysterious_rock_inn | 0.7448 | [0.716, 0.772] |
| 3 | 15_marnie_s_grimmsnarl_ex | 0.7204 | [0.690, 0.749] |
| 4 | 20_cynthia_s_garchomp_ex | 0.6560 | [0.625, 0.686] |
| … | （以下 19 デッキ、最下位 07_n_s_zoroark_n 0.1134） | | |

champion の Wilson 下限 **0.792** は #2 の上限 **0.772** を上回り、screen 段階で既に CI 分離。

### confirm（finalists = champion + #2, n/pair=90, 独立 seed 2060100）
`eval/results/sot2060_deck_meta_confirm.json`（各 finalist はフィールド全体と対戦＝統計は screen と可比）

| deck | winrate | Wilson95 | n_decided |
| --- | --- | --- | --- |
| **26_stw_champion** | **0.8197** | **[0.803, 0.836]** | 2063 |
| 16_crustle_mysterious_rock_inn | 0.7472 | [0.728, 0.766] | 2061 |

独立 seed の confirm でも champion 下限 **0.803** ≫ #2 上限 **0.766**＝**CI 非重複で分離**。
screen と confirm で champion のポイント推定（0.8185 → 0.8197）が一致し、seed luck ではない。

## 4. 判定 — 非昇格（champion プレイデッキ維持）

- champion `26_stw_champion`（= `deck.csv`）は 2026-07 の meta_active フィールドに対して **依然 rank #1、
  かつ #2 と統計的に明確に分離**。新メタ盤面でも champion デッキの選択は妥当と実測で確認された。
- よって **プレイデッキ差し替えの根拠なし＝非昇格**。`main.py`(`FABLE_CONFIG`) と `deck.csv` は
  **無変更**。共有 champion（matsu/take/ume/claude 共通 `26_stw_champion`）を差し替える提案も不要。
- 本 PR の変更は評価コード非依存（既存 `eval/compare_decks.py` を用いた計測）＋結果 JSON ＋本 doc のみ。
  champion の挙動・提出物には一切影響しない。

## 5. 提出

- 現 champion（無変更）は本日 cron が既に提出済み: **ref `55031928` "auto-improve submit:
  ptcg-agent-claude champion"（2026-07-27 15:00 UTC）= publicScore 541.4 (COMPLETE)**。
- 系譜の高値記録 ref `54921798`（569.5, 07-23）と同一 champion 系譜で、差は既知の public-score
  ノイズ帯（±20pt, SOT-1902）内＝実効同一。
- 本サイクルは champion を **無変更**にした（プレイデッキ非昇格）。同日・byte 等価の champion を
  再提出するのは duplicate（1 日 1 提出設計・±20pt ノイズ）に反するため、**新規提出は skip**。
  受け入れ条件の「提出」は本日提出済み ref `55031928` で充足。

## 受け入れ条件（親 SOT-2060）

- [x] 改善方針と選定理由をコメント/本 doc に記録（engine 実走可を起点に champion デッキ×新メタ再検証を選定）。
- [x] 子 Issue は分解判断=不要（単一の一貫した評価タスク＝1PR）につき登録なし。親を In Review で終端。
- [x] 昇格/非昇格の結論（非昇格・維持）が champion 状態（`FABLE_CONFIG` + `deck.csv` 無変更）と整合。
- [x] 提出は本日提出済み ref `55031928`（541.4, COMPLETE）で充足。無変更につき新規 duplicate 提出は skip（理由明記）。
