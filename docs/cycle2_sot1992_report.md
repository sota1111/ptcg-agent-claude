# Kaggle順位向上サイクル第2次 — 改善方針の立案と判定 (SOT-1992)

2026-07-26。親 SOT-1913 の自動起案サイクル（`pokemon-tcg-ai-battle` / repo `ptcg-agent-claude`
= 旧 fable 系統）。前サイクル（SOT-1936 群 = 第1次）の全非昇格を受けて、次の未着手改善軸の有無を
判定し、champion 状態と提出を整合させた。**champion は無変更**（本サイクルで昇格なし）。

## 起案材料

- 前回提出（champion）: ref `54987094` (2026-07-26 00:09 UTC, `auto-improve submit:
  ptcg-agent-claude champion`) = publicScore **548.1** (COMPLETE)。系譜の高値記録は ref `54921798`
  (2026-07-23, d46222b) = **569.5**。両者は同一 champion 系譜で、差 ≈21pt は既知の public-score
  ノイズ帯（±20pt, SOT-1902）内＝実効同一。
- 完了 Issue ダイジェスト / 失敗ログ: 新規なし（起案材料は空）。

## 改善軸レビュー — 未着手の独立軸が存在しない

fable(=claude) 系譜は探索・評価・学習の各軸を既に走査済みで、いずれも独立 seed の confirm で
baseline へ回帰＝**非昇格**が確定している。本サイクルで「未着手かつ本コンテナで検証可能」な軸は
見当たらない。

| 軸 | 試行 | 結論 |
| --- | --- | --- |
| 探索パラメータ (uct_c / n_worlds / max_root_actions / max_tree_depth / deviate_margin / prior_temp) | SOT-1796 (fable_v2, 14候補) | 空間は平坦。screen で光った候補が独立 seed で全反転 → 非昇格 |
| 探索深化 (progressive widening, depth≥2) | SOT-1864 (depth_search) | 非昇格 (0.440) |
| 学習価値関数 × MCTS | SOT-1865 / value_net_v2 | 非昇格（MSE 改善が champion に転移せず） |
| 盤面全滅対策（リーフ評価） | SOT-1863 (board_wipe) | 非昇格（構造的敗着＝basic を引けない） |
| 序盤ベンチ prior 加点 | SOT-1941 (early_bench) | screen 0.700 → confirm 0.489、非昇格 |
| expert iteration / 学習 action prior | SOT-1911 / 1916 | 非昇格。GPU 第4次で「全軸飽和確定」 |
| take 戦術移植 | SOT-1892 | 非昇格（champion バランスを崩す） |
| デッキ再選定 | SOT-1915 (deck_reselection) | 非昇格 |
| 相手プール頑健性 screen | SOT-1940 (opponent_pool) | 非昇格 |
| rollout 早期打切りによる高速化 | SOT-1836 (sims_speedup) | ×1.76 だが探索量増は勝率に非転換 |

補足: 本コンテナは engine（`cg/` + `data/` カード CSV）と sibling 供給源
（`/workspaces/kaggle-ptcg-ume/.../extracted`）が不在のため、新規 A/B を実走できない。仮に新レバーを
起案しても本環境では screen→confirm ゲートを回せず、非昇格前例の再演にしかならない。

## 分解判断

```
分解判断: 不要
理由: 未着手かつ本環境で検証可能な独立改善軸が存在せず（全軸=非昇格の前例あり／engine 実走不可）、
      2〜5 子への分解は非昇格前例の再演＝共有 usage limit の空費に終わるため。champion 維持が正。
```

CLAUDE.md 分解ポリシー（「investigations/minor は分解しない」「独立ドメインが無ければ親で処理」）に
整合。新レバーの根拠が立った将来サイクルで改めて子を起案する。

## 判定: champion 維持（昇格なし）

- champion = `main.py` の `FABLE_CONFIG` + `deck.csv`（**無変更**）。
- 昇格/非昇格の結論（＝非昇格・維持）と、Kaggle 上の現 champion（ref `54987094` = 548.1 が本日
  提出済み・COMPLETE）は整合。
- 追加提出: **不要**。本日すでに現 champion（byte 等価）を提出済みで、無変更 champion の再提出は
  duplicate（1日1提出の設計・±20pt ノイズ帯 SOT-1902 に反する）。よって本サイクルの「提出」は
  ref `54987094` で充足とし、新規提出は skip（理由: champion 無変更＋当日提出済み）。

## 受け入れ条件

- [x] 改善方針と選定理由を記録（本 doc + Linear コメント）= 全軸非昇格・engine 実走不可により champion 維持。
- [x] 子 Issue は分解判断=不要（根拠明記）につき登録なし。親を In Review で終端。
- [x] 昇格/非昇格の結論（非昇格・維持）が champion 状態（`FABLE_CONFIG` 無変更 / ref 54987094 live）と整合。
- [x] 提出は本日提出済み ref `54987094`（548.1, COMPLETE）で充足。無変更のため新規 duplicate 提出は skip（理由明記）。
