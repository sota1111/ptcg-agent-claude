# SOT-2238 — Kaggle順位向上サイクル 第6次（ptcg-agent-claude）

- コンペ: `pokemon-tcg-ai-battle`（系統: claude = 旧fable）
- 親サイクル: SOT-1913（自動起案の起点。Issue タイトルは新番号系で「第2次」だが、
  本 repo の改善サイクルとしては SOT-1992/2060/2114/2172/2229 に続く**第6次**）
- 判定: **champion 維持（昇格なし）／分解不要**
- 前サイクル: 第5次 SOT-2229（PR#27, 実予算0.8sで全レバー飽和を確定）

## 入力材料（cron 自動収集）

- 前回提出結果:
  - 2026-07-31 07:41 COMPLETE public=**493.8**
  - 2026-07-31 07:40 ERROR（standalone packaging 起因、e11d357 で修正済み・以後 COMPLETE）
  - 2026-07-29 15:00 COMPLETE public=**494.5**
- 直近の完了 Issue ダイジェスト: なし
- 失敗ログ・KPI 抜粋: なし

public は相対採点で日変動するが 494.5 → 497.1（第5次計測）→ 493.8 と横ばいで、
**順位急落・新 meta・新規失敗ログといった新シグナルは存在しない**。

## 分解判断: 不要

理由: 探索 param / 深化 / 幅 / 価値関数 / board-wipe / early-bench / expert-iter /
take 戦術 / デッキ再選定 / 相手プール / 高速化 / 予算スケールの全軸が、第1〜5次で
**proxy(0.06s) と実予算(0.8s) の両スケールで非昇格確定**（第5次 SOT-2229 が実予算
0.8s の head-to-head と独立 seed 拡張で mtd2+mra10 複合まで含め saturation を実測確定）。
残る構造候補（sims-per-world 効率 / 非ミラー相手プール頑健性）はいずれも**事前証拠
なし**であり、新シグナルが立たない現状で speculative 軸を自動子分解するのは共有 usage
limit の空費（CLAUDE.md「overhead > value なら分解しない」/「非昇格再演は空費」）。
→ 本サイクルは新規 A/B を追加せず、champion 健全性の新規 smoke で健在を確認して完結。

## 新実測（引用でなく）

第5次が 07-31 に実予算 0.8s の重い confirm を完了済みのため、本サイクルは高コストな
A/B 再実行を避け、champion の健全性のみを新規 smoke で確認した:

```
eval/bench.py --agent-a mcts --agent-b greedy --n 8 --seed 2238001
  → A wins 6 / B wins 2 / draws 0（win rate 0.7500 Wilson95 [0.4093, 0.9285]）
  → engine rejects 0 / agent exceptions 0 / fallbacks 0 / budget violations 0 /
     planner fallbacks 0 / degraded 0  ＝ faults 0
  → time/decision mean 33.5ms（0.8s 予算内）
```

champion（`main.py FABLE_CONFIG`: max_root_actions6 / max_tree_depth1 / n_worlds4 /
time_budget_s0.8 / deviate_margin0.1）は実走健在・全 fault カテゴリ 0。

## 提出判断 — skip（理由記録）

本サイクルは非昇格＝champion 無変更のため新 artifact は存在しない。無変更 artifact の
byte 等価 re-submit は 1日1提出設計・±20pt 相対採点ノイズに反するため **skip**。
現 champion artifact は 07-31 07:41 に COMPLETE(public 493.8/第5次計測 497.1) として
提出済み（`submission.tar.gz` sha256 `54776a08bf02e09130c335f7db106a0b1dee2565e19a119cde4de788205612c4`,
e11d357 packaging 修正込み）。次に champion が実際に変わる提出まで自動 safe skip を継続。

## 検証

- `python3 -m pytest tests -q` → **138 passed**（コード変更なし、docs + 計測ログのみ）
- smoke bench 全 8 局 faults=0

## 申し送り（第7次へ）

- 全既存レバー（探索・評価・学習・デッキ・予算・深化/幅・複合）は proxy と実予算の
  両スケールで非昇格確定（第5次 SOT-2229 を根拠に再々試行は不可・明示 skip 可）。
- 残る構造候補は sims-per-world 効率と非ミラー相手プール頑健性のみ。いずれも事前証拠
  なし → **新シグナル（順位急落 / 新 meta / 新規失敗ログ）が立つまで champion 維持が
  期待値最大**。新シグナルが立った場合のみ、その候補を子分解する。
