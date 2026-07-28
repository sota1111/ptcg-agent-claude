# SOT-2114 — Kaggle順位向上サイクル 第3次（ptcg-agent-claude）

- コンペ: `pokemon-tcg-ai-battle`（系統: claude = 旧fable）
- 親サイクル: SOT-1913（自動起案の起点）
- 判定: **champion 維持（昇格なし）／分解不要**
- 前サイクル: 第1次 SOT-1992（PR#21, champion維持）・第2次 SOT-2060（PR#23, deck再検証 非昇格）

## 入力材料

cron 自動収集の材料は本サイクルでは **空**：

- 前回提出結果（順位/スコア）: 記録なし
- 直近の完了 Issue ダイジェスト: 新規なし
- 失敗ログ・KPI 抜粋: 該当なし

特定の弱点を指す新規シグナルは存在しない。

## 改善軸レビュー — 未着手の独立軸なし

fable(=claude) 系譜は探索・評価・学習の各軸を第1〜2次で網羅走査済みで、いずれも独立 seed の
confirm で baseline へ回帰＝**非昇格**が確定している。

| 軸 | 試行 | 結論 |
| --- | --- | --- |
| 探索パラメータ (uct_c / n_worlds / max_root_actions / depth / deviate_margin / prior_temp) | SOT-1796 (14候補) | 空間平坦・confirm で全反転 → 非昇格 |
| 探索深化 (progressive widening / depth≥2) | SOT-1864 | 非昇格 (0.440) |
| 学習価値関数 × MCTS | SOT-1865 / value_net_v2 | 非昇格（MSE 改善が champion に転移せず） |
| 盤面全滅対策（リーフ評価） | SOT-1863 | 非昇格（構造的敗着＝basic を引けない） |
| 序盤ベンチ prior 加点 | SOT-1941 | screen 0.700 → confirm 0.489 → 非昇格 |
| expert iteration / 学習 action prior | SOT-1911 / 1916 | 非昇格・GPU 第4次で「全軸飽和確定」 |
| take 戦術移植 | SOT-1892 | 非昇格（champion バランスを崩す） |
| デッキ再選定 / メタ追従 | SOT-1915 / SOT-2060 | 非昇格（champion deck を新メタプールで再検証し CI 分離で維持） |
| 相手プール頑健性 screen | SOT-1940 | 非昇格 |
| rollout 早期打切りによる高速化 | SOT-1836 | ×1.76 だが探索量増は勝率に非転換 |

## 本サイクルの新規実測（第2次の「engine 実走不可」前提を訂正）

第2次（SOT-1992）は「本コンテナは engine 実走不可」を根拠に**引用のみ**で saturation を結論した。
しかし SOT-2060 で判明の通り、本 clone `/tmp/ptcg-agent-claude` には `cg/libcg.so` と
`data/{EN,JP}_Card_Data.csv` が揃い、A/B は**実走可能**である。よって本サイクルは引用で終わらせず、
実測で saturation を裏付けた。

### 1. champion 健全性 smoke（engine 実走の再確認）

```
python3 eval/bench.py --agent-a mcts --agent-b greedy --n 8 --seed 2114001 \
    --config-a '{...FABLE_CONFIG..., "time_budget_s":0.15}'
→ A 3 / B 5 / draw 0 / unfinished 0
  engine rejects 0  agent exceptions 0  fallbacks A=0 B=0  degraded 0
```

fault0。engine（`cg/` + カード CSV）が実走し、champion が例外・違法手なく完走することを再確認
（勝率は throttled 0.15s・n=8 の smoke であり強さの指標ではない。champion 基準線は SOT-1938
mcts vs greedy 0.5625 / Kaggle 569.5 系譜）。

### 2. 代表レバー再 screen — n_worlds 4→6（champion head-to-head）

探索パラメータ空間の平坦性（SOT-1796）を新データで追認するため、代表的に n_worlds を 4→6 に上げた
候補を champion と直接対戦（mirror-MCTS, `eval/run_ab_vs_champion.sh`, BUDGET=0.06s）で screen した。

```
eval/run_ab_vs_champion.sh screen 12 2114100,2114200 <out> \
    nworlds6='{"time_budget_s":0.06,"n_worlds":6,"eval_weights":{...champion...}}'
→ winrate_a 0.4583  Wilson95 [0.2789, 0.6493]  (A 11 / B 13 / draw 0, N=24)  faults=0
```

下限 0.279（点推定 0.458）で **0.5 を割る**＝昇格ゲート不通過（**非昇格**）。探索パラメータの増強は
champion を上回らない、という平坦性の結論を新規実測で裏付けた。

## 分解判断

```
分解判断: 不要
理由: 未着手かつ本環境で検証可能な独立改善軸が存在せず（全10軸=非昇格の前例に加え、本サイクルの
      n_worlds 再screen も非昇格の新実測）、新規入力材料も空。2〜5子への分解は非昇格前例の再演＝
      共有 usage limit の空費に終わる。champion 維持が正。
```

CLAUDE.md 分解ポリシー（「独立ドメインが無ければ親で処理」「investigations/minor は分解しない」
「genuinely independent でなければ over-decompose しない」）に整合。新レバーの promise 根拠が立つ
将来サイクルで改めて子を起案する。構造的に新しい方向（不完全情報の belief modeling / IS-MCTS 等）は
大規模研究であり、promise の事前証拠なしに自動子分解する対象ではない（申し送り）。

## 判定・提出

- **champion 維持（昇格なし）**。champion = `main.py` の `FABLE_CONFIG` + `deck.csv`（**無変更**）。
- Kaggle 現 champion 提出は本日 cron が提出済み：ref **55058187**
  （`pokemon-tcg-ai-battle`, publicScore **631.9**, `SubmissionStatus.COMPLETE`, 2026-07-28 15:00 UTC,
  message `auto-improve submit: ptcg-agent-claude champion`）。
- champion 無変更＝byte 等価につき新規提出は duplicate（1日1提出設計・±20pt ノイズ帯 SOT-1902 に
  反する）→ **新規提出 skip**。受入条件の「提出」は ref `55058187` で充足。

## 受け入れ条件

- [x] 改善方針と選定理由をコメント＋本 doc に記録＝全軸非昇格（新実測 n_worlds 再screen 含む）により champion 維持。
- [x] 子 Issue は分解判断=不要（根拠明記）につき登録なし。親を In Review で終端。
- [x] 昇格/非昇格の結論（非昇格・維持）が champion 状態（`FABLE_CONFIG`/`deck.csv` 無変更, ref 55058187 live）と整合。
- [x] 提出は本日 cron 提出済み ref `55058187`（631.9, COMPLETE）で充足。無変更 duplicate の新規提出は skip（理由明記）。
