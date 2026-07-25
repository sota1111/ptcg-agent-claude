# 序盤たね切れ / 盤面全滅耐性: early-bench 行動prior加点 A/B レポート (SOT-1941)

2026-07-25。親 SOT-1936（[ptcg-agent-claude] Kaggle順位向上サイクル第1次）の敗着解析ベース改善。
fable(=claude) の最大ローカル敗着クラスタ **盤面全滅（board_wipe: アクティブ不在で敗北,
RESULT.reason=3）** に対し、**行動選択 prior（greedy scorer）側**でベンチが薄いとき序盤のたね
Pokémon 展開を優先する opt-in 加点を1案実装し、vs-champion A/B の screen → confirm と board_wipe
敗着タグ before/after で昇格可否を判定した。

関連: SOT-1863（同じ board_wipe 対策を**リーフ評価**で試行し非昇格）/ SOT-1835（敗因解析）/
SOT-1796（screen反転の教訓）。

## 仮説と、SOT-1863 との差別化

盤面全滅は「アクティブが気絶したとき、昇格できるベンチ Pokémon が 1 体もない」状態で起きる。
SOT-1863 は**リーフ評価**に `bench_dev`（ベンチ枚数の飽和加点）/ `evo_ready` を足したが、
screen→confirm 非昇格・board_wipe 構成比も低下せず（構造的敗着＝そもそも basic を引けない）と
結論した。

本 Issue はその**リーフ評価加点の再試行ではなく、別レバー**を1案として試す:

- `agents/greedy_agent.py` の `bench_boost` / `bench_floor`（既定 0 = champion 不変）。基本
  Pokémon を**プレイする行動の優先度**を、ベンチが `bench_floor` 未満のあいだ、不足枠数ぶん
  `bench_boost` だけ引き上げる（floor で飽和）。リーフ**価値**ではなく**手番中のプレイ順**を
  steer し、items/supporters/attack より先に「保険のたね」を置かせる。
- `PlannerConfig.early_bench` / `early_bench_floor` 経由で、prior と rollout を兼ねる共有
  `GreedyAgent` に注入。champion（`main.py FABLE_CONFIG`）はこれらを設定しない＝完全不変。

## 手法

- `eval/run_ab_vs_champion.sh`（候補 MCTS を champion MCTS に直接対戦、記録 `winrate_a` が対
  champion 勝率、Wilson 95% CI 下限が昇格ゲート）。両者同一の絞った time budget 0.06s。
- **昇格ゲート: 集約 Wilson 95% CI 下限 > 0.5、独立 seed の confirm 必須**（SOT-1796）。全計測 fault 0。
- board_wipe 敗着タグは `analysis/local_loss_tags.py` の新 `FABLE_TAG_CONFIG`（top-level config
  delta）で候補 config を注入し、mirror で before/after を比較。

## screen 結果（seeds 2001,2002 / N=40, 対 champion, budget 0.06s）

| 候補 | config delta | 勝率 | Wilson 95% CI |
| --- | --- | --- | --- |
| **eb_f2_b20** | `early_bench=20, early_bench_floor=2` | **0.700** | **[0.5457, 0.8193]** |
| eb_f3_b20 | `early_bench=20, early_bench_floor=3` | 0.575 | [0.4220, 0.7149] |
| baseline | `{}`（champion 相当） | 0.500 | [0.3520, 0.6480] |
| eb_f3_b40 | `early_bench=40, early_bench_floor=3` | 0.475 | [0.3294, 0.6250] |

- baseline（champion 対 champion）が 0.500 ちょうど → 対戦ハーネスは無バイアス（サニティ合格）。
- 強すぎる加点（`b40`）は逆効果（0.475）。唯一 CI 下限 > 0.5 を screen で満たした **eb_f2_b20**
  （floor=2, boost=20）を confirm に昇格。

## confirm 結果（独立 seeds 3001–3003 / N=90, 対 champion）

| 候補 | 勝率 | Wilson 95% CI |
| --- | --- | --- |
| eb_f2_b20 | 0.4889 | [0.3882, 0.5905] |
| baseline | 0.4667 | [0.3671, 0.5690] |

screen の 0.700 は独立 seed の confirm で **0.489 へ後退**、CI 下限 **0.388 < 0.5** で昇格ゲート
未達。baseline 自身も 0.467（ノイズ床）で、両 CI はほぼ完全に重複 → **有意差なし**。SOT-1673 /
1698 / 1699 / 1796 / 1863 と同じ「screen の輝きが独立 seed で洗い流される」パターンが再現した。

## board_wipe 敗着タグ before/after（mirror / N=40, budget 0.08s, seed 5001）

| 構成 | losses | board_wipe | prize_race_lost |
| --- | --- | --- | --- |
| champion | 20 | **85.0%**（17） | 15.0%（3） |
| eb_f2_b20 (`early_bench=20, floor=2`) | 24 | **87.5%**（21） | 12.5%（3） |

**対策版でも board_wipe 構成比は下がらない**（85.0% → 87.5%、むしろ微増、mirror 総損失も 20→24）。
序盤にベンチを厚くしても盤面全滅損失は減っておらず、confirm の勝率非改善と整合する。SOT-1863 の
リーフ評価と同じく、盤面全滅は「ベンチ忘れ」ではなく**ゲームを通じて削り切られる / basic を
引けない**構造的敗着で、prior 側のプレイ順 steer でも動かないと再確認された。

## 判定: **非昇格 — champion を維持**

- 昇格ゲート（confirm CI 下限 > 0.5）未達、かつ board_wipe 構成比の低下も確認できず。
- SOT-1698/1699/1796/1863 の運用ルールに従い、**champion（`main.py FABLE_CONFIG`）の挙動は一切
  変更しない**。追加した加点は **既定 OFF の opt-in**（`bench_boost`/`bench_floor` ＝
  `early_bench`/`early_bench_floor`）として温存（`bench_dev` / `deck_low` / `value_net` と同じ
  dormant infra 扱い。将来 on-policy 学習や別レバーと組み合わせる後続候補が再利用できる）。
- 残す成果物: opt-in 行動prior加点（`agents/greedy_agent.py`＋`agents/planner.py`＋単体テスト
  `tests/test_early_bench.py`）、`local_loss_tags.py` の `FABLE_TAG_CONFIG` top-level override、
  KPI 履歴、本 docs。

## 受け入れ条件

- [x] たね切れ/全滅 敗着率の before/after が記録されている（champion 85.0% vs 対策版 87.5%、
  `analysis/data/local_loss_tags.json`（champion 版）+ 本表）。
- [x] 昇格/非昇格が CI で結論付けられている（screen 4 行 + confirm 2 行、全 fault 0、
  confirm CI 下限 0.388 < 0.5 → 非昇格判定、`kpi_history.jsonl`）。
- [x] 非昇格につき behavior revert + docs のみ（新加点は既定 OFF＝champion 不変、コード変更は
  dormant opt-in と本 docs のみ）。

## 再現コマンド

```bash
EW='"deck_low":-0.2,"deck_low_at":14,"deck_low_prize_gate":3'
# screen（対 champion, N=40）
BUDGET=0.06 eval/run_ab_vs_champion.sh screen 20 2001,2002 kpi_history.jsonl \
  eb_f2_b20="{\"time_budget_s\":0.06,\"eval_weights\":{$EW},\"early_bench\":20,\"early_bench_floor\":2}"
# confirm（独立 seed, N=90）
BUDGET=0.06 eval/run_ab_vs_champion.sh confirm 30 3001,3002,3003 kpi_history.jsonl \
  baseline="{\"time_budget_s\":0.06,\"eval_weights\":{$EW}}" \
  eb_f2_b20="{\"time_budget_s\":0.06,\"eval_weights\":{$EW},\"early_bench\":20,\"early_bench_floor\":2}"
# board_wipe タグ before/after
FABLE_TAG_BUDGET=0.08 python3 analysis/local_loss_tags.py --n 40 --mirror --seed 5001            # champion
FABLE_TAG_BUDGET=0.08 FABLE_TAG_CONFIG='{"early_bench":20,"early_bench_floor":2}' \
  python3 analysis/local_loss_tags.py --n 40 --mirror --seed 5001                                # 対策版
```
