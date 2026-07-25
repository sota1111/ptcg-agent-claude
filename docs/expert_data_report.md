# Expert-iteration self-play データ生成パイプライン (SOT-1914)

親 **SOT-1911**（fable第4次: GPU実機の大規模 expert iteration）の仮説1の入力となる
大規模 self-play 学習データ生成基盤。champion MCTS 同士の自己対戦から
**(状態特徴量, MCTS訪問分布, 勝敗ラベル)** に加え、**H1–H3 board-risk 特徴量**
（SOT-1894 由来）と **補助ターゲット**（N手以内の 全滅/たね枯渇 敗北ラベル）を、
resume 可能なシャーディング出力で生成する。

## 成果物

| ファイル | 役割 |
| --- | --- |
| `train/gen_expert_data.py` | champion 自己対戦の per-decision データ生成器（シャーディング＋resume＋スループット計測） |
| `agents/expert_features.py` | H1–H3 特徴量抽出（`extract_h`）と敗着タグ（`loss_cause`）。値域は全て `[0,1]` |
| `agents/planner.py`（差分） | ルート訪問分布を `planner.last_stats["root_actions"/"root_visits"]` に公開（**診断のみ・着手選択は不変**） |
| `train/merge_expert_data.py` | シャード union（未完了 match を破棄）＋スループット集約 |
| `train/validate_expert_data.py` | スキーマ検証（訪問分布総和=1・ラベル欠損なし・H1–H3 値域） |
| `train/expert_data_sanity.py` | H1–H3 と敗着（全滅/たね枯渇）の相関サニティチェック |
| `tests/test_expert_data.py` | 24 テスト（エンジン非依存＋エンジンゲート付き end-to-end） |

## 記録スキーマ（1 サンプル = 1 JSON 行）

```json
{"m": 12, "actor": 0, "d": 7,
 "f": [ ...20 floats ],            // agents.value_features.extract (状態特徴量)
 "h": [ ...7 floats in [0,1] ],    // H1-H3 (agents.expert_features)
 "pi": {"a": [[0],[1],[3]], "v": [8,21,3], "p": [0.25,0.656,0.094]},  // 訪問分布
 "y": 1.0,                          // 勝1.0 / 負0.0 / 分0.5（着手側POV）
 "aux_wipe": 0, "aux_seed": 1}      // N手以内に全滅/たね枯渇で敗北したか
```

- `pi.p` は**ルート候補アクション**（各要素は option index の集合）上の訪問分布で、総和 1。
  実際に探索が走った ≥2 候補の局面のみ記録する（forced / degraded / greedy-fallback は
  方針シグナルを持たないので除外）。
- `f` は既存 value-net と同一の抽出器 → value 学習と特徴量レイアウトを共有。
- `aux_wipe`/`aux_seed` は「着手側が自分の以後 N 手（既定 8）以内に 全滅/たね枯渇 で負ける」
  early-warning ターゲット。敗着タグは終局盤面のヒューリスティック（`loss_cause`）。
- バージョン: `feature_version`=1 / `h_feature_version`=1 / `schema_version`=1。

### H1–H3 特徴量（SOT-1894 `docs/replay_prior_hypotheses.md`）

| 名前 | 意味 |
| --- | --- |
| `h1_bench_empty` | Active はいるがベンチ0（1回のKOで敗北の脆弱状態） |
| `h1_wipe_exposure` | `bench_empty × min(1, 相手Active最大打点 / 自Active HP)` |
| `h2_hand_basics` | 手札のたね（Basic）枚数 / 6 |
| `h2_hand_basics_zero` | 手札にたね0 のとき 1.0 |
| `h3_pokemon_in_play` | 場のポケモン数 / 6 |
| `h3_energy_attached` | 付与エネルギー総数 / 12 |
| `h3_evolved` | 進化済み（stage1/2）ポケモン数 / 6 |

## champion 既定挙動は無変更

- 生成は**読み取り専用の対戦実行**。既定 agent config は `main.FABLE_CONFIG`。
- `planner.py` の差分は `last_stats` に訪問数を**追記するだけ**で、返す着手は byte-identical。
  既存の再現性テスト（`test_mcts.py` の same-seed→same-action / scripted-win）は全て pass。
- 既存テスト 133 件 + 新規 24 件 = **全 pass**。

## 検証（fault0・スキーマ・実データ）

### small-N 生成 fault0 ＋ スキーマ検証

- champion FABLE_CONFIG で 6 マッチ生成 → **faults=0**、166 サンプル、
  `validate_expert_data` **SCHEMA OK**（f=20, h=7、訪問分布総和=1、ラベル欠損なし、
  H1–H3 全て `[0,1]`）。
- エンジンゲート付きテスト `TestGenExpertOnEngine` が CI 相当で fault0＋schema を担保。

### resume 可能なシャーディング（実証）

- `--n-shards 2 --shard-index k` で match 空間を素分割（`i % M == k`）。テストで
  無被覆・無重複を固定。
- **実際に resume が発火**: shard1 の生成が途中で中断 → 再実行で既完了 23 マッチを
  スキップし残り 37 マッチのみ実行（`matches_resumed=23`, faults=0）。未完了 match の
  行（`match_done` マーカー無し）は reader が破棄するため、部分書き込みでデータは壊れない。
- merge: shard0(60) + shard1(60) = **120 マッチ / 3932 サンプル / faults=0** に union、
  SCHEMA OK。

### スループット実測と ≥10万手番の現実性

| 設定 | games/h/core | samples/h/core | samples/game |
| --- | --- | --- | --- |
| champion `FABLE_CONFIG`（time_budget 0.8s, n_worlds 4） | **210.9** | ~5,836 | ~27.7 |
| 量産用 fast config（time_budget 5s, max_iter 40, n_worlds 2） | ~2,790 | ~89,000 | ~32 |

- **目標 ≥10万手番（policy サンプル）**:
  - champion 品質: 単コア ~17.1h、**8 コア並列（シャード）で ~2.1h** → 8h/日予算内。
  - fast config: 単コア ~1.1h、8 コアで ~8 分（policy 品質検証や補助ターゲット学習の量産用途）。
- 生成は CPU 並列（`--n-shards`）で、学習側の GPU とは独立。`--time-limit-s` で日次予算に収める。

### H1–H3 と敗着の相関サニティ（生成データ 3932 サンプル）

`train/expert_data_sanity.py train/data/expert.jsonl`：

| feature | wipe μ(=1) | wipe μ(=0) | wipe r | seed r |
| --- | --- | --- | --- | --- |
| `h1_bench_empty` | 0.784 | 0.321 | **+0.345** | +0.284 |
| `h1_wipe_exposure` | 0.488 | 0.177 | **+0.318** | +0.268 |
| `h2_hand_basics` | 0.004 | 0.030 | −0.128 | −0.126 |
| `h2_hand_basics_zero` | 0.977 | 0.852 | +0.137 | +0.130 |
| `h3_pokemon_in_play` | 0.193 | 0.317 | **−0.261** | −0.182 |
| `h3_energy_attached` | 0.083 | 0.150 | −0.140 | −0.096 |
| `h3_evolved` | 0.039 | 0.123 | **−0.234** | −0.147 |

読み（SOT-1894 の再現）:
- **H1**: 全滅敗北サンプルはベンチ0率 78%（非敗着 32%）・wipe_exposure も約 2.8 倍 → ベンチ0 と
  相手打点露出が敗着を強く予測（r≈+0.32–0.35）。
- **H2**: 全滅サンプルの **97.7% が手札たね0**（SOT-1894 の「wipe の 92%」を生成データで再現）。
- **H3**: 展開度（場のポケモン/エネルギー/進化）は全て敗着と**負相関** → development-first が
  効く方向。

いずれも SOT-1894 の敗着仮説と符合する。これは**サニティチェックであり昇格ゲートではない**
（昇格判定は SOT-1916 の学習→MCTS統合→screen→confirm で行う）。

## 使い方

```bash
# 量産（8 シャードを別プロセス/コアで並列、各々日次予算で打ち切り）
for k in $(seq 0 7); do
  python3 train/gen_expert_data.py --n 4000 --seed 20260725 \
    --n-shards 8 --shard-index $k --time-limit-s 28800 \
    --out train/data/expert.shard$k.jsonl &   # ← 別コア
done; wait
# union → 検証 → サニティ
python3 train/merge_expert_data.py --out train/data/expert.jsonl train/data/expert.shard*.jsonl
python3 train/validate_expert_data.py train/data/expert.jsonl
python3 train/expert_data_sanity.py  train/data/expert.jsonl
```

中断しても各シャードを同じコマンドで再実行すれば、`match_done` マーカーから未完了分のみ
再開する（resume）。
