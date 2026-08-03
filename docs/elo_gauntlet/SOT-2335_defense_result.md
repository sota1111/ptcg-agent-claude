# SOT-2335 — 盤面全滅 upset敗北の抑制（守備レバー）: 非昇格

**親**: SOT-2332 (ptcg-agent-claude Kaggle順位向上サイクル第1次) / **依存**: SOT-2334 (ELO整合ローカル評価ハーネス)
**判定日**: 2026-08-03 / **結論**: **非昇格 (NON-PROMOTION)** — champion (`main.py` FABLE_CONFIG) 不変

## 目的（再掲）

ELO方式LBでは弱敵への **upset敗北** が rating 流出の支配要因で、敗因の 93.8% が盤面全滅(board wipe)。
本 issue はその**守備レバー**として `agents/evaluator.py` の board-wipe 保険項
(`bench_dev`/`bench_dev_cap`/`evo_ready`, SOT-1863 で実装済・champion では既定 OFF) を ON にし、
SOT-2334 の ELO-proxy 上で **upset敗北率の削減**（＝弱敵に取りこぼさない）を確認する。
判定は平均勝率ではなく「下振れ（upset敗北率）」と upset-tier NET で行う。

## 方法

SOT-2334 の `eval/elo_gauntlet.py` に、**champion-under-test の `eval_weights` だけ**を差し替える
`--champion-eval-weights` を追加（相手フィールドは baseline FABLE_CONFIG に固定 → 候補 vs 固定参照場の
isolated A/B）。追加は additive・exec 非依存。unit test 4 本追加 (`tests/test_elo_gauntlet.py`,
計 12 green)。

A/B: champion budget 0.12s, n=16/cell, 7-cell anchored field, **独立 3 seed (2335/20335/42335)** で
screen＝confirm 同時実施。BASE = champion(FABLE_CONFIG)。CAND = champion + 守備レバー(eval_weights 差分のみ)。

## 結果

| 構成 | 守備レバー(eval_weights差分) | R* (pooled) | **upset敗北率** | upset-tier NET | board_wipe% | 3seed upset NET<0 |
|---|---|---|---|---|---|---|
| BASE (champion) | — | 1482.0 | **0.321** (77/240) | −339.9 | 96.9% (127/131) | all True |
| CAND1 | `bench_dev0.4/cap2/evo_ready0.2` | 1506.8 | **0.325** (78/240) | **−563.2** | 95.1% (116/122) | all True |
| CAND2 (強配合) | `bench_dev0.8/cap3/evo_ready0.4` | 1490.2 | **0.329** (79/240) | −468.3 | 89.8% (115/128) | all True |

## 判定：非昇格

- **upset敗北率は削減されない**（0.321 → 0.325 → 0.329、配合を強めるほど僅かに悪化）。有意減の反対。
- **upset-tier NET は悪化**（−339.9 → −563.2 / −468.3）。SOT-2334 が下流に課した「守備は upset-tier NET を
  引き上げよ」を満たさない。
- R* は CAND1 で +24.8 上がるが、内訳は **強敵tier (mcts_high wr 0.417→0.604)** の伸びで、本 issue の狙い
  （弱敵 board-wipe の取りこぼし削減）とは**直交**。守備レバーの効果ではない。
- 機序: 強配合(CAND2)では board_wipe% が 96.9→89.8% に下がる一方、prize_race_lost が 4→13 に増え、**敗因の型が
  盤面全滅→プライズレースに移るだけで upset 敗北の総数は減らない**。0.12s MCTS 下の wipe は評価項ボーナスでは
  買えないテンポ/盤面差の戦術的 KO 連鎖であり、bench 育成ボーナスはそれを防げない。

**昇格条件（ELO-proxy non-inferior かつ upset敗北率が有意減）を満たさないため非昇格。** champion / `main.py`
submit 経路は不変（exec互換維持、Kaggle 提出なし＝親 SOT-2332 のみ）。

## 残す成果物（champion 挙動は不変）

- `eval/elo_gauntlet.py` の `--champion-eval-weights` オーバーライドは、SOT-2334 と同様の **診断専用・additive・
  exec 非依存**ツールとして保持（下流 SOT-2336 攻撃レバーの A/B 機構としても再利用）。champion の eval_weights は
  変更しない。
- 生ログ: `docs/elo_gauntlet/sot2335_base.jsonl` / `sot2335_cand.jsonl` / `sot2335_cand2.jsonl`（＋各 `.log`）、
  実行スクリプト `docs/elo_gauntlet/run_sot2335_ab.sh`。

## 今後（軸は本サイクルで閉塞）

eval_weights ボーナスによる board-wipe 守備は **非有効**と確定。真に upset 敗北を減らすには評価項ではなく
**探索/行動側**（board-wipe 直前局面の保守的 promote・retreat 方策、planner 側の一斉気絶回避バイアス、または
より強い leaf 評価）が必要で、これは別 issue の攻撃/探索軸に委ねる。
