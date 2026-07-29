# SOT-2172 — Kaggle順位向上サイクル 第4次（ptcg-agent-claude）

- コンペ: `pokemon-tcg-ai-battle`（系統: claude = 旧fable）
- 親サイクル: SOT-1913（自動起案の起点）
- 判定: **champion 維持（昇格なし）／分解不要**
- 前サイクル: 第1次 SOT-1992（PR#21, champion維持）・第2次 SOT-2060（PR#23, deck再検証 非昇格）・
  第3次 SOT-2114（PR#24, n_worlds再screen 非昇格・維持）

## 入力材料

cron 自動収集の材料は本サイクルでは **空**：

- 前回提出結果（順位/スコア）: 記録なし（description上）
- 直近の完了 Issue ダイジェスト: 新規なし
- 失敗ログ・KPI 抜粋: 該当なし

特定の弱点を指す新規シグナルは存在しない。参考として `docs/kaggle-ranking-history.md`（SOT-2097）は
公式順位 3,987/5,753（07-26）→ 2,010/5,873（07-28）と改善を記録（GPT+Claude 共有チーム順位）。

## 改善軸レビュー — 未着手の独立軸なし

fable(=claude) 系譜は探索・評価・学習の各軸を第1〜3次で網羅走査済みで、いずれも独立 seed の
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
| determinization 幅 (n_worlds 4→6) | SOT-2114 | 下限 0.279 → 非昇格 |

## 本サイクルの新規実測（引用でなく実測で saturation を裏付け）

第3次（SOT-2114）の申し送り「不完全情報の belief modeling / IS-MCTS が構造的な新方向候補だが
promise の事前証拠なしに自動子分解しない」を受け、本サイクルは **その候補軸に事前証拠が立つか**を
実測で確認した。engine（`cg/libcg.so` + `data/{EN,JP}_Card_Data.csv`）は本 clone で実走可能。

### 1. champion 健全性 smoke（engine 実走の再確認）

```
python3 eval/bench.py --agent-a mcts --agent-b greedy --n 8
→ A 4 / B 4 / draw 0 / unfinished 0
  engine rejects 0  agent exceptions 0  fallbacks A=0 B=0
  budget violations A=0 B=0  planner fallbacks 0  degraded 0
```

fault0。engine が実走し champion が例外・違法手なく完走することを再確認（勝率は n=8 の smoke で
強さ指標ではない。champion 基準線は SOT-1938 系譜）。

### 2. 候補2軸を champion 直接対戦で screen（mirror-MCTS, BUDGET=0.06s, N=24）

第3次の申し送り候補「探索深化」と「belief/determinization 幅の増強」を代表する2レバーを、
champion（`FABLE_CONFIG`）と直接 head-to-head で screen した（`eval/run_ab_vs_champion.sh`）。

```
eval/run_ab_vs_champion.sh screen 12 2172001,2172002 kpi_history.jsonl \
  mtd2='{"time_budget_s":0.06,"max_tree_depth":2,"eval_weights":{...champion...}}' \
  nw8='{"time_budget_s":0.06,"n_worlds":8,"eval_weights":{...champion...}}'

mtd2 (max_tree_depth 1→2): winrate_a 0.3333  Wilson95 [0.1797, 0.5329]  (A 8 / B 16, N=24)  faults=0
nw8  (n_worlds 4→8):       winrate_a 0.2917  Wilson95 [0.1491, 0.4917]  (A 7 / B 17, N=24)  faults=0
```

両候補とも点推定・上限ともに **0.5 を下回り、champion に劣後**（belief 幅 nw8 は 95%CI 全域が
0.5 未満で有意に悪い）。固定 compute 予算下で determinization world を増やす（belief 幅の naive な
増強）と 1 world あたりの sims が減り per-world 探索が弱まる、という古典的トレードオフを新実測で確認。
すなわち **belief modeling / IS-MCTS 系の"事前証拠"は本 screen では立たず**、真の利得には
sims-per-world 効率の改善が必要で、それは前サイクル群が到達した同じ壁である。

## 分解判断

```
分解判断: 不要
理由: 未着手かつ本環境で検証可能な独立改善軸が存在せず（全11軸=非昇格の前例に加え、本サイクルで
      第3次申し送りの belief/determinization 幅 nw8 と 探索深化 mtd2 を新実測しいずれも非昇格＝champion
      劣後）、新規入力材料も空。2〜5子への分解は非昇格前例の再演＝共有 usage limit の空費に終わる。
      champion 維持が正。
```

CLAUDE.md 分解ポリシー（「独立ドメインが無ければ親で処理」「investigations/minor は分解しない」
「genuinely independent でなければ over-decompose しない」）に整合。構造的に新しい方向
（belief modeling / IS-MCTS 等）は本 screen で事前証拠が立たず、大規模研究として promise の
根拠が立つ将来サイクルで改めて子を起案する（申し送り）。

## 判定・提出

- **champion 維持（昇格なし）**。champion = `main.py` の `FABLE_CONFIG` + `deck.csv`（**無変更**）。
- Kaggle 現 champion 提出は本日 cron が提出済み：ref **55085404**
  （`pokemon-tcg-ai-battle`, publicScore **444.5**, `SubmissionStatus.COMPLETE`, 2026-07-29 15:00 UTC,
  message `auto-improve submit: ptcg-agent-claude champion`）。
- champion 無変更＝byte 等価につき新規提出は duplicate（1日1提出設計・±20pt ノイズ帯 SOT-1902 に
  反する）→ **新規提出 skip**。受入条件の「提出」は ref `55085404` で充足。
  publicScore は相対採点で日により大きく動く（07-28 571.0 → 07-29 444.5）が champion は無変更。

## 受け入れ条件

- [x] 改善方針と選定理由をコメント＋本 doc に記録＝全軸非昇格（新実測 mtd2 / nw8 含む）により champion 維持。
- [x] 子 Issue は分解判断=不要（根拠明記）につき登録なし。親を In Review で終端。
- [x] 昇格/非昇格の結論（非昇格・維持）が champion 状態（`FABLE_CONFIG`/`deck.csv` 無変更, ref 55085404 live）と整合。
- [x] 提出は本日 cron 提出済み ref `55085404`（444.5, COMPLETE）で充足。無変更 duplicate の新規提出は skip（理由明記）。
