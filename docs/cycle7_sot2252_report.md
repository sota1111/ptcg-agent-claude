# SOT-2252 — Kaggle順位向上サイクル 第7次（ptcg-agent-claude）

- コンペ: `pokemon-tcg-ai-battle`（系統: claude = 旧fable）
- 親サイクル: SOT-1913（自動起案の起点。Issue タイトルは新番号系で「第3次」だが、
  本 repo の改善サイクルとしては SOT-1992/2060/2114/2172/2229/2238 に続く**第7次**）
- 判定: **champion 維持（昇格なし）／分解不要**
- 前サイクル: 第6次 SOT-2238（PR#28, 実予算 smoke で健全性確認・saturation 継続）

## 入力材料（cron 自動収集）

- 前回提出結果:
  - 2026-08-01 13:01 COMPLETE public=**540.0**（現 champion artifact `54776a08…`）
  - 2026-07-31 07:41 COMPLETE public=**486.1**
  - 2026-07-31 07:40 ERROR（standalone packaging 起因・修正済み）
- 直近の完了 Issue ダイジェスト: なし
- 失敗ログ・KPI 抜粋: 該当なし

public は相対採点で日変動する（過去実測 493.8 → 494.5 → 497.1 → 486.1 → **540.0**）。
540.0 は前サイクル群に対し **横ばい〜微増**であって順位急落ではない。
**順位急落・新 meta・新規失敗ログといった新シグナルは存在しない。**

## 分解判断: 不要

理由: 探索 param / 深化 / 幅 / 価値関数 / board-wipe / early-bench / expert-iter /
take 戦術 / デッキ再選定 / 相手プール / 高速化 / 予算スケール / 複合の全軸が、第1〜6次で
**proxy(0.06s) と実予算(0.8s) の両スケールで非昇格確定**（第5次 SOT-2229 が実予算
0.8s の head-to-head と独立 seed 拡張で mtd2+mra10 複合まで含め saturation を実測確定、
第6次 SOT-2238 が smoke で健全性を追認）。残る構造候補（sims-per-world 効率 /
非ミラー相手プール頑健性）はいずれも**事前証拠なし**であり、新シグナルが立たない現状で
speculative 軸を opus 子分解するのは共有 usage limit の空費
（CLAUDE.md「overhead > value なら分解しない」/「非昇格再演は空費」）。
→ 本サイクルは新規 A/B を追加せず、champion 健全性の新規 smoke で健在を確認して完結。

## 新実測（引用でなく）

第5次が 07-31 に実予算 0.8s の重い confirm を完了済みのため、本サイクルは高コストな
A/B 再実行を避け、champion の健全性のみを新規 smoke で確認した（コード変更なし）:

```
eval/bench.py --agent-a mcts --agent-b greedy --seed 2252001 --n 8
  → A 2 / B 6 / draws 0（win rate 0.2500 Wilson95 [0.0715, 0.5907]）
eval/bench.py --agent-a mcts --agent-b greedy --seed 2252100 --n 24
  → A 13 / B 11 / draws 0（win rate 0.5417 Wilson95 [0.3507, 0.7211]）
  pooled: 15/32 = 0.469
  全 32 局: engine rejects 0 / agent exceptions 0 / fallbacks 0 /
            budget violations 0 / planner fallbacks 0 / degraded 0  ＝ faults 0
  time/decision mean 28–33ms（0.8s 予算内）
```

vs-greedy は**堅牢性 smoke**（クラッシュ・予算超過・fallback の有無を見る harness）であり、
champion の競技力そのものは Kaggle public（本日 540.0）が指標。小 n・強めの greedy 相手で
勝率は 0.5 近傍にノイズするが、**全 32 局 fault カテゴリ 0** で champion は実走健在。

champion（`main.py FABLE_CONFIG`: max_root_actions6 / max_tree_depth1 / n_worlds4 /
time_budget_s0.8 / deviate_margin0.1）は無変更・実走健在。

## 提出判断 — idempotent skip（理由記録）

提出は指示どおり control-plane の
`bash scripts/ai/kaggle_targets_submit.sh --competition ptcg --repo ptcg-agent-claude`
経由で判定した（Kaggle CLI/API 直呼びは行わず fingerprint gate を尊重）。結果:

```
ptcg-agent-claude [claude] → skip  (daily slot already completed (idempotent rerun))
```

現 champion artifact（`submission.tar.gz` sha256
`54776a08bf02e09130c335f7db106a0b1dee2565e19a119cde4de788205612c4`）は本日 08-01 13:01 に
COMPLETE(public=540.0) として既に提出済み。registry は
`repeat_requires_new_artifact: true`（当日2枠目は未提出 SHA-256 のみ許可）であり、
本サイクルは非昇格＝champion 無変更のため**新 artifact が存在しない**。よって当日枠は
**idempotent skip**（byte 等価 re-submit は 1日提出設計・±20pt 相対採点ノイズに反する）。
次に champion が実際に変わる提出まで自動 safe skip を継続。

## 検証

- `python3 -m pytest tests -q` → **138 passed**（コード変更なし、docs + 計測ログのみ）
- smoke bench 全 32 局 faults=0

## 申し送り（第8次へ）

- 全既存レバー（探索・評価・学習・デッキ・予算・深化/幅・複合）は proxy と実予算の
  両スケールで非昇格確定（第5次 SOT-2229 / 第6次 SOT-2238 を根拠に再々試行は不可・
  明示 skip 可）。
- 残る構造候補は sims-per-world 効率と非ミラー相手プール頑健性のみ。いずれも事前証拠
  なし → **新シグナル（順位急落 / 新 meta / 新規失敗ログ）が立つまで champion 維持が
  期待値最大**。新シグナルが立った場合のみ、その候補を子分解する。
- public が 486.1（07-31）→ 540.0（08-01）と揺れているのは相対採点ノイズ。今後
  **恒常的な**順位低下トレンドが立てば、それが初めての新シグナルとして扱える。
