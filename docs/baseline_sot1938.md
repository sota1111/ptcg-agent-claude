# ptcg-agent-claude champion baseline 再計測 & 前回提出結果 (SOT-1938)

2026-07-25。Kaggle順位向上サイクル第1次 (親 SOT-1936) の改善判断の土台として、現 champion
(`main.py` の `FABLE_CONFIG` + `deck.csv`) の実力を既存 KPI ハーネスで再計測し、前回 Kaggle
提出のスコア/順位を取得してベースラインを確立する。**champion の挙動は無変更**（計測と記録のみ）。

---

## 1. champion baseline 勝率 (Wilson 95% CI)

`eval/kpi.py`（canonical KPI ハーネス。1実行=1計測=`kpi_history.jsonl` 1行追記）で、champion
determinized MCTS (`FABLE_CONFIG` を base) を固定リファレンス `greedy` に対して計測した。

```bash
python3 eval/kpi.py --label baseline --phase baseline \
    --agent-a mcts --agent-b greedy --n 12 --seeds 1938001,1938002,1938003,1938004 \
    --note "SOT-1938 champion baseline re-measure (FABLE_CONFIG MCTS vs greedy); engine=ume/cg"
```

| 項目 | 値 |
| --- | --- |
| agent A (champion) | `mcts` + `FABLE_CONFIG` |
| agent B (reference) | `greedy` |
| N | 48 (12/seed × 4 独立seed shard) |
| 勝率 A (draws除外) | **0.5625** |
| Wilson 95% CI | **[0.4228, 0.6930]** |
| A wins / B wins / draws | 27 / 21 / 0 |
| faults 合計 | **0**（rejects / exceptions / fallbacks / budget_violations / planner_fallbacks / degraded すべて0） |
| git_sha | f352370 |
| engine | ume/cg（`scripts/setup_engine.sh` 相当を sibling から注入。`cg/`・`data/` はgitignore） |

- **fault0 で完走**。CI下限 0.4228 と過去の 07-21 baseline confirm (0.667 [0.525, 0.783], N=48)
  はCI重複範囲内で、engine内部RNGが外部seed不可なためrun間の分散（±）に収まる。champion は
  greedy に対し優位傾向だが N=48 では 0.5 を明確にCI分離するには至らない（探索飽和領域の既知挙動）。
- 追記行は `kpi_history.jsonl` の最終行（`label=baseline / phase=baseline / n_total=48`）。

## 2. 前回 Kaggle 提出結果

Kaggle CLI（best-effort）でコンペ `pokemon-tcg-ai-battle` の提出履歴を取得。

**ptcg-agent-claude(=fable系) の直近提出:**

| ref | 日時 (UTC) | 説明 | status | publicScore |
| --- | --- | --- | --- | --- |
| **54921798** | 2026-07-23 07:09 | ptcg-agent-fable d46222b champion (SOT-1866; phase-2 全非昇格, baseline 34064b3=550.7 とbyte等価) | COMPLETE | **569.5** |
| 54883092 | 2026-07-21 17:06 | ptcg-agent-fable 34064b3 (v1 champion) | COMPLETE | 550.7 |

- 前回の claude/fable champion 提出 = **ref 54921798, publicScore 569.5 (COMPLETE)**。
- privateScore はコンペ開催中のため非開示（空欄）。

**順位について（重要な注意）:** Kaggle アカウント `sota1111` は matsu/take/ume/zero/fable(claude) の
**全エージェントを単一チームで提出**しており、public leaderboard 上のチーム順位は「その時点で選択/最良の
1提出」で決まる。2026-07-25 07:01 取得の public leaderboard スナップショットでは:

| 指標 | 値 |
| --- | --- |
| チーム `sota1111` 現在順位 | **4771 / 5670** |
| 現在の選択スコア | 434.6（= zero counter-policy 提出 ref 54934082、07-24 が最新選択） |
| fable champion 569.5 が選択された場合の概算順位 | ≈ **3725 / 5670** |
| 首位スコア | 1154.9 (Yushin Ito) |

したがって「claude(fable) champion 単体の実力指標」= publicScore **569.5**（概算順位 ≈3725/5670）。
チーム表示順位 4771 は zero 提出が現在選択されているための値で、claude champion 固有の順位ではない。

## 3. ベースライン確立まとめ

- **local baseline**: champion `mcts`(`FABLE_CONFIG`) vs greedy = **0.5625 [0.4228, 0.6930]**, N=48, fault0。
- **Kaggle baseline**: 前回 claude champion 提出 **ref 54921798 = 569.5 (COMPLETE)**（概算LB ≈3725/5670）。
- これらを SOT-1936 サイクルの改善判断の起点とする。以降の改善候補は同じ `eval/kpi.py`
  screen→confirm でこの baseline とCI比較して昇格判定する。

## 受け入れ条件

- [x] champion baseline 勝率（Wilson CI 付き）が記録されている → §1 + `kpi_history.jsonl` 追記行
- [x] 前回提出の順位/スコア（または取得不可理由）が記録されている → §2（score 569.5 / LB順位注記）
