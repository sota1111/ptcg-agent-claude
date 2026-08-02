# SOT-2283 — 学習value関数でrolloutを置換（GPU, 特徴量v2）: 第3次 value-net 挑戦

親Issue: SOT-2277（ptcg-agent-claude Kaggle順位向上サイクル 第4次）。
関連: SOT-1837（value net 第1次・greedy off-policy・非昇格）／ SOT-1865（第2次・on-policy・非昇格）／
SOT-1836（sims_speedup 解析：本機構を「唯一残された有望路」と名指し）。
判定: **非昇格（champion 維持）** — `value_net` は既定 OFF のまま、`main.py` FABLE_CONFIG 不変。

## 目的（非昇格再演でない根拠）

sims_speedup 解析（SOT-1836）は根本トレードオフを明示した: champion は 1 手 ~606 反復で**既に反復飽和**
しており、rollout 早期打ち切りで反復を増やしても評価品質（≒100ターン rollout の value）が劣化して純減する。
これを解く唯一の道は「**遅い rollout を速い学習 value 関数で置換して、反復数↑と評価品質維持を両立**」。
先行 SOT-1837/1865 は同機構で非昇格だが、本サイクルは以下を**前回から明確に強化**して再実施した
（CLAUDE.md「非昇格再演は空費」の回避）:

| レバー | 前回 (1837/1865) | 今回 (2283) |
| --- | --- | --- |
| **特徴量** | 20次元（集約のみ: 両側の prize/pokemon/energy/hp合計/hand/deck/active/bench + 4差分） | **36次元 (FEATURE_VERSION=2)**。集約20をそのまま prefix に保持し、prize-trade を左右する **Active 個体シグナル**を追加: Active HP・Active energy(攻撃準備)・Active進化済フラグ・最大単体HP(最大の壁/脅威)・進化Pokémon数・特殊状態フラグ、＋ global の **ターン数(局面フェーズ)**。per-card 重み禁止規律は維持 |
| **データ規模** | on-policy 1,344戦 / 24,901サンプル (SOT-1865) | **on-policy 7,438戦 / 132,560サンプル**（8シャード×~900s並列, faults 0）= **約5.5倍** |
| **学習** | CPU stdlib / GPU非搭載, hidden≤64 | **GPU (RTX 3080 Ti, torch 2.5.1+cu121)**, hidden=128, epochs=500, Adam |
| **A/Bゲート** | time_budget 0.12s, N≤50 | **実予算 time_budget_s=0.8**, 独立**4 seed** N=30 (pooled 120), Wilson95 |

姉妹 SOT-2282 は field-representative ガントレットで **policy/algorithm 飽和は REAL（oracle ドリフト無）**
と確定済み。本 Issue はその上で「value 品質×反復数の両立」という別軸を、最強構成で検証する。

## 1) on-policy データ生成（受け入れ条件①）

champion(MCTS) 自己対戦を 8 シャード並列生成（各 ~900s wall-clock 上限, 生成 budget 0.04s で量を確保。
方策の質・盤面分布は champion 同型: `max_tree_depth=1, rollout_turns=100, n_worlds=4`, 同一 `eval_weights`）:

| 項目 | 実測 |
| --- | --- |
| シャード数 | 8（全 stopped_early=true, ~900s 到達） |
| matches_played | **7,438 戦** |
| サンプル数 | **132,560**（勝 76,423 / 他 56,137） |
| fault | **0** |
| 生成時間 | 8 並列 × ~900s（累計 gen_seconds 7,205s） |

> SOT-1865(1,344戦) 比で **約5.5倍** の on-policy データ。in-container 実行制限撤廃で実現。

## 2) 学習（受け入れ条件①②）— GPU

```bash
python3 train/train_value.py --data train/data/onpolicy.jsonl \
    --out train/weights/value_v3.json --backend torch \
    --hidden 128 --epochs 500 --lr 0.01 --l2 1e-4 --seed 2283
```

| 指標 | 値 |
| --- | --- |
| backend / device | **torch 2.5.1+cu121 / cuda (RTX 3080 Ti)** |
| samples (train/val) | 132,560 (106,048 / 26,512) |
| win base rate | 0.577 |
| **val MSE** | **0.1909**（final train_mse 0.1907） |
| torch→python forward 一致 | max gap **2.58e-07** |
| 一致検証（train-forward vs 再ロード純Python推論） | max gap **0.00e+00**（tol 1e-6）OK |

**val MSE 比較**: 定数0.5予測=0.25。1837(greedy)=0.197 / 1865(on-policy 20次元)=0.214。
今回 **0.1909** は両者を下回り、**1865 レポートが「昇格の前提」と名指しした 0.197 の閾値を突破**した。
→ **特徴量拡張(v2)＋GPU＋5.5倍データが、先行2回の val MSE 頭打ちを実際に破った**（value 信号は明確に強化された）。

## 3) sims_bench（受け入れ条件②）— 反復数≥champion を実証

`eval/sims_bench.py`（同一 40 盤面コーパス, seed 20260722, 同一 0.8s 予算）:

| config | leaf 評価 | iters/search | sims/sec | speedup | faults |
| --- | --- | --- | --- | --- | --- |
| champion | 100ターン rollout | ~500 | 892.6 | 1.00 | 0 |
| **value_v3_leaf** | 学習value直接 (`rollout_turns=0`) | **2000（反復キャップ飽和）** | 10,475.8 | **×11.74** | 0 |

→ **受け入れ条件「0.8s 予算内で反復数≥champion」を達成**（学習value推論に置換すると 1反復が
engine rollout 不要で桁違いに速く、0.8s 到達前に反復キャップ 2000 へ達する = champion 以上の探索量を
品質劣化なく確保、fault 0）。

## 4) vs champion A/B（受け入れ条件③）— 実予算 0.8s / 独立4seed

`eval/bench.py --agent-a mcts(value_v3 leaf) --agent-b mcts(champion)`、同一 deck.csv、先後入替、
`time_budget_s=0.8`。生 JSON: `docs/value_net_v3/ab_leaf_s*.json`（`eval/results/` は .gitignore のためここに保存）。

| seed | N | 候補勝(A) | champion勝(B) | draw | winrate A | Wilson95 |
| --- | --- | --- | --- | --- | --- | --- |
| 22831 | 30 | 13 | 17 | 0 | 0.433 | [0.274, 0.608] |
| 22832 | 30 | 14 | 16 | 0 | 0.467 | [0.302, 0.639] |
| 22833 | 30 | 11 | 19 | 0 | 0.367 | [0.219, 0.545] |
| 22834 | 30 | 12 | 18 | 0 | 0.400 | [0.246, 0.577] |
| **pooled** | **120** | **50** | **70** | **0** | **0.4167** | **[0.3324, 0.5061]** |

engine rejects 0 / agent exceptions 0 / budget violations 0 / planner fallbacks 0 / degraded 0（全 seed）。

**昇格ゲート = pooled Wilson CI 下限 > 0.5** → CI 下限 **0.3324 < 0.5** で**非昇格**。点推定 0.4167 で
champion より**むしろ弱く**、4 seed すべてが < 0.5 で一貫（上振れ seed なし）。

## 判定と根拠（受け入れ条件④⑤）

**非昇格。champion 挙動は不変**（`value_net` 既定 OFF、`main.py` FABLE_CONFIG 変更なし、
`tests` 138 green、`test_submission` 系で不変を担保）。behavior revert は不要（champion 経路に学習版は
そもそも載っていない）。**Kaggle 提出は行っていない**（本 Issue 制約: 提出は親 SOT-2277 の再開 run のみ）。

### なぜ「品質両立」が勝率に転換しなかったか（1段落）

今回は先行2回の 2 つの弱点（弱い value 信号・少ないデータ）を実際に解消した—— val MSE は 0.191 へ改善し
（0.197 閾値突破）、leaf 置換で反復数は champion の約4倍（500→2000, キャップ飽和）に増えた。にもかかわらず
勝率は 0.417 と **むしろ低下**した。これは「反復数↑」でも「評価品質」が champion の 100ターン full rollout に
**まだ届いていない**ことを意味する。champion の葉評価は事実上 terminal までの完全プレイアウト（真の結果の
不偏サンプル）であり、36次元 MLP が均衡付近の盤面で出す value は—— MSE を 0.023 下げてもなお—— その分散を
埋めきれない。飽和済みの木(24エッジ×~83訪問)にノイジーな葉値を大量注入しても、探索は速く**誤った**方向へ
収束するだけで、full-rollout champion の少数だが正確な葉値に負ける。**value 品質の質的ギャップが束縛条件**で
あり、データ量・反復数・特徴量の量的強化では超えられない、という結論に第3次で最も強い証拠つきで到達した。

### escalation ladder 上の含意（親サイクルへの申し送り）

local tuning（第1-7次）→ data/oracle rebuilding（SOT-2282 で oracle ドリフト無を確定）→
value-net 置換（本 Issue, 第1-3次で閉塞）まで歩いた。**同一 determinized-MCTS 枠内での漸進改善レバーは
出尽くした**。次の有望軸は枠外——(a) アーキテクチャ変更（例: 葉評価に full rollout を残しつつ policy prior を
学習して探索を絞る／progressive widening で depth を稼ぐ, ただし SOT-1864/2172 系は非昇格前例あり）、
(b) 外部知識（公開 notebook / 論文の determinized-MCTS 改良）、(c) デッキメタ追従（SOT-2284 領域）。
本機構(value 置換)は opt-in インフラ(`value_features` v2 / `LearnedEvaluator`)として温存する。

## 再現

```bash
# 1) on-policy データ生成（8シャード並列, 各 ~900s, budget 0.04s）
CFG='{"time_budget_s":0.04,"max_root_actions":6,"max_tree_depth":1,"rollout_turns":100,
      "rollout_depth":200,"n_worlds":4,"deviate_margin":0.1,
      "eval_weights":{"deck_low":-0.2,"deck_low_at":14,"deck_low_prize_gate":3}}'
for k in $(seq 0 7); do
  python3 train/gen_selfplay.py --agent mcts --n 12000 --seed 22830101 --stride 2 \
    --max-per-match 40 --n-shards 8 --shard-index $k --time-limit-s 900 \
    --config "$CFG" --out train/data/onpolicy.shard$k.jsonl &
done; wait
python3 train/merge_selfplay.py --out train/data/onpolicy.jsonl train/data/onpolicy.shard*.jsonl

# 2) GPU 学習（feature_version=2, 36次元）
python3 train/train_value.py --data train/data/onpolicy.jsonl \
    --out train/weights/value_v3.json --backend torch --hidden 128 --epochs 500 --lr 0.01 --seed 2283

# 3) sims_bench（反復数 ≥ champion を実証）
python3 eval/sims_bench.py --label value_v3_leaf --states 40 --seed 20260722 \
    --override '{"value_net":"train/weights/value_v3.json","rollout_turns":0,"rollout_depth":0}' --baseline

# 4) vs champion A/B（実予算 0.8s, 独立4seed）
CHAMP='{"max_root_actions":6,"max_tree_depth":1,"rollout_turns":100,"rollout_depth":200,"n_worlds":4,
        "time_budget_s":0.8,"deviate_margin":0.1,"eval_weights":{"deck_low":-0.2,"deck_low_at":14,"deck_low_prize_gate":3}}'
LEAF='{"max_root_actions":6,"max_tree_depth":1,"rollout_turns":0,"rollout_depth":0,"n_worlds":4,
       "time_budget_s":0.8,"deviate_margin":0.1,"value_net":"train/weights/value_v3.json",
       "eval_weights":{"deck_low":-0.2,"deck_low_at":14,"deck_low_prize_gate":3}}'
for s in 22831 22832 22833 22834; do
  python3 eval/bench.py --agent-a mcts --agent-b mcts --n 30 --seed $s \
    --config-a "$LEAF" --config-b "$CHAMP" --json docs/value_net_v3/ab_leaf_s$s.json &
done; wait
```

## 受け入れ条件チェック

- [x] ① 自己対戦データ生成・value学習が再現可能で、前回(1837/1865)からの強化点（特徴量20→36次元 / データ1,344→7,438戦 / GPU学習 / ゲート0.8s×4seed）を記録
- [x] ② value推論が leaf 評価に統合され、0.8s予算内で反復数 2000 ≥ champion ~500 を実証（sims_bench, ×11.74, fault0）
- [x] ③ vs-champion A/B（実予算0.8s・独立4seed / pooled 120）の pooled Wilson CI [0.3324, 0.5061] を記録
- [x] ④ 昇格判定（CI下限>0.5）を明示 → **非昇格**。main.py 不変（champion value_net OFF, revert 不要）
- [x] ⑤ pytest 138 green ／ **Kaggle提出なし**（提出は親の再開runのみ）
