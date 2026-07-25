# SOT-1911/1914/1916 — GPU expert iteration（learned action prior）

親Issue: SOT-1911（fable 第4次強化 / GPU 大規模学習）。子: SOT-1914（データ生成）,
SOT-1916（学習+統合+昇格判定）, SOT-1915（デッキ再選定, `docs/deck_reselection_sot1915.md`）。

判定: **非昇格（champion 維持）** — `main.py` FABLE_CONFIG 不変、learned prior は
既定 OFF の opt-in インフラとして温存。全 opt-in・非昇格なら behavior revert 不要
（champion 経路に学習版は載っていない）。

## 背景と設計判断

第3次（SOT-1887）までで **手書き・小規模学習の 4 軸すべてが非転換**:
探索量（SOT-1836）/ 深さ（SOT-1864）/ value net 小規模学習（SOT-1837・**SOT-1865**）/
手書き手選択バイアス（SOT-1892）。特に **SOT-1865 が「champion は full-rollout
（`rollout_turns=100`）なので葉評価の寄与が構造的に小さく、value net は効かない」** と
GPU 完全再現ジョブまで含めて実証済み。

したがって第4次の本命は value net の焼き直しではなく、**未試行の learned action
prior（expert iteration の policy head）**。SOT-1892 の *手書き* prior が非転換だったのに対し、
*学習* prior は別軸。

### なぜ「per-option scorer」か

このMCTSのアクション空間は状態依存の可変集合（engine option index の部分集合,
`agents/planner.py`）で、固定サイズの policy head を作れない。そこで
**policy = 各 option を `[state ; option]` から採点する学習器**として定式化した
（`GreedyAgent.score_options` の学習版）。これは greedy prior への
**状態条件付き学習補正**であり、option の greedy score を特徴量として与えるので、
net は「greedy が符号化しない差」だけを学べばよい。属性のみ（per-card 重み表禁止）で
value net と同じ合法性・Kaggle 互換（純Python/numpy-free 推論）を満たす。

## 成果物

| 追加/変更 | 役割 |
| --- | --- |
| `agents/policy_features.py`（新規） | per-option 特徴量: state(20) ++ OptionType one-hot(17) ++ greedy score ++ **ターゲット属性(14)**（対象ポケモンHP/エネルギー/進化段階/prize, 攻撃ダメージ/lethal, PLAY カード種別）。POLICY_FEATURE_VERSION=2 |
| `agents/policy_net.py`（新規） | 純Python per-option scorer（input→H tanh→1 linear logit）+ softmax + stdlib softmax-CE SGD。JSON エクスポート（value_net と同型） |
| `agents/learned_prior.py`（新規） | 推論用 opt-in prior。planner の root prior 注入点で greedy を置換。純Python 推論 |
| `agents/planner.py`（変更） | `learned_prior_path`（opt-in・既定 None・**単一選択のみ**適用）と `record_root`（self-play 記録）を追加。両フラグ OFF で champion 経路は byte-identical |
| `train/gen_policy.py`（新規） | champion MCTS 自己対戦から (state, per-option block, **MCTS訪問分布π**, 勝敗z) を記録。seed シャード分割 + wall-clock 上限（SOT-1865 踏襲） |
| `train/merge_policy.py`（新規） | policy シャード JSONL を1データセットに union |
| `train/train_policy.py`（新規） | π への masked softmax CE を GPU（torch/CUDA, RTX 3080 Ti）で学習 → 純Python export → 一致検証 |
| `tests/test_policy_net.py`（新規） | forward/export一致/次元/version ガードを固定 |

`train/data/`・`train/weights/` は `.gitignore` 済（生成物・重み）。コード + docs + 生 bench JSON を PR 化する。

## 1) データ生成（SOT-1914, 受け入れ条件①）

champion config（`max_root_actions=6, max_tree_depth=1, rollout_turns=100, n_worlds=4,
deviate_margin=0.1`, 同一 `eval_weights`）の自己対戦を **24 シャード並列 × wall-clock 1200s**
で生成（生成 budget `time_budget_s=0.25`）:

| 項目 | 実測 |
| --- | --- |
| シャード | 24（各 time-limit 1200s, RTX 3080 Ti マシン 24 コア） |
| matches_played | **4,891 戦** |
| policy サンプル（単一選択・訪問分布つき） | **123,893** |
| fault | **0** |

単一選択（`lo==hi==1`, options>1）決定のみ記録（policy net の適用範囲）。各サンプルは
π = champion の集約ルート訪問分布、z = 手番側の最終勝敗。

## 2) 学習（SOT-1916, 受け入れ条件②）

GPU（torch/CUDA）で masked softmax CE を学習（`hidden=128, epochs=300, lr=0.01`）:

| 指標 | 値 |
| --- | --- |
| decisions (train/val) | 123,893 (105,310 / 18,583) |
| **val CE** | **1.2076**（uniform 1.4149） |
| torch→python logit 一致 | max gap 2.6e-6 |
| export 再ロード一致検証 | **max gap 0.0e+00**（tol 1e-4）OK |

**headroom 診断（val 20k サンプル）** — learned prior が greedy を超えたか:

| prior | CE ↓ | top1 vs π ↑ | 備考 |
| --- | --- | --- | --- |
| uniform | 1.4153 | — | 下限 |
| greedy（planner temp 40） | 1.2830 | 0.873 | 現行 champion prior |
| **learned** | **1.2083** | 0.859 | 分布校正は改善／最善手的中は微減 |

> **learned argmax == greedy argmax: 0.967**。learned prior は π の *分布* を greedy より
> 良く近似する（CE 1.283→1.208）が、**指す手（argmax）は greedy と 96.7% 同一**で、最善手
> 的中はむしろ微減。champion の full-rollout 探索（~600 iter）が prior を補正する構造では、
> prior の校正改善は着手選択をほぼ変えない。

## 3) vs champion A/B（SOT-1916, 受け入れ条件③）

両側 MCTS を同一 budget（`time_budget_s=0.12, n_worlds=4, max_root_actions=6,
max_tree_depth=1, deviate_margin=0.1`, 同一 `eval_weights`）で対戦、side 交互、独立 seed。
A=learned prior 統合、B=champion（greedy prior）。生 JSON: `screen_prior.json`。

| 案 | N | winrate A (excl. draws) | Wilson95 | W/L/D | fault/reject/budget超過/degraded | 判定 |
| --- | --- | --- | --- | --- | --- | --- |
| learned prior | 50 | **0.5000** | [0.3664, 0.6336] | 25/25/0 | 0/0/0/0 | **非昇格** |

昇格ゲート = 集約 CI 下限 > 0.5。CI 下限 0.366 < 0.5 で **screen 段階で不成立 → confirm 不要**。
25/25 の完全同格・engine reject 0・agent 例外 0・budget 超過 0・planner fallback 0・degraded 0。

低 budget（0.12s）は prior の寄与が最も顕在化しやすい条件（探索が少ないほど prior 依存）。
そこで完全同格 = champion budget（0.8s）ではさらに探索が prior を補正するため、より高 budget で
昇格に転じる見込みはない（追加測定を省いた根拠）。診断（argmax 96.7% 同一）とも整合。

## 判定と教訓

**非昇格。champion 挙動は不変**（`learned_prior_path` 既定 None, `record_root` 既定 False,
`main.py` FABLE_CONFIG 変更なし, test_submission/test_mcts 全 green, `test_policy_net` 追加）。
learned prior は opt-in インフラとして温存。

### なぜ効かないか（SOT-1837/1865 → 1916 の収束した結論）

1. champion の greedy prior は既に強く、learned prior は **argmax を 96.7% 変えない**
   （分布校正は良くなるが着手が同じ）。
2. champion の探索（full rollout ~600 iter）が prior の粗さを吸収する。value net（SOT-1865）が
   full-rollout に効かなかったのと **同じ構造的理由**が prior 側にも当てはまる。
3. 単純 MLP + 属性のみ特徴量では、greedy が同点にする option（例: 複数エネルギー付け先）を
   π が区別する分の一部しか学べない（属性は近いが π は探索固有の差を持つ）。
4. matsu SOT-1674/1679, ume PPO 系, fable 1837/1865/1892 と **同じ結論**に再到達
   = fable の探索は量/深さ/value 質/手書き prior/**学習 prior** のいずれでも非転換で飽和。

### exec 互換 / Kaggle（SOT-1917）

learned prior 推論は純Python/numpy-free（`agents/policy_net.py`）で exec 互換ゲートを通せる設計だが、
**昇格が出なかったため Kaggle 提出は発火しない**（SOT-1917 は「昇格時のみ」）。champion（fable v1,
Kaggle 収束 ≈550.7）を最終提出のまま維持。

## 受け入れ条件チェック（SOT-1911 親）

- [x] 仮説を子Issueへ分解・登録（SOT-1914/1916/1915/1917）
- [x] GPU学習 → 純Python推論エクスポート → exec互換ゲートの経路を実装（policy_net export + 一致検証）
- [x] 各子に screen→confirm 昇格ゲート + 非昇格 champion 維持を内蔵（learned prior・deck とも非昇格）
- [x] 昇格時の Kaggle 実証経路を定義（SOT-1917, 未発火 = 非昇格）
