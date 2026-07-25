# SOT-1915 — 上位帯メタ想定構成に対する fable デッキ再選定（SOT-1893 引き継ぎ）

親Issue: SOT-1911（fable 第4次強化）。SOT-1893（第3次で未実施終端）の引き継ぎ。
判定: **非昇格（champion デッキ `26_stw_champion` 維持）** — `deck.csv` 不変。

## 目的

第3次で未実施のまま終端した SOT-1893 を引き継ぎ、上位帯メタ（大会実績デッキ 26 種の
候補プール `decks/candidates/`）に対して fable の現行 champion デッキが依然として最強かを
`compare_decks.py`（agent 非依存, SOT-1794）の screen で再確認する。

## 方法

- ドライバ: `eval/compare_decks.py`（全候補ペア総当たり、両側 greedy、side 交互、集約 Wilson 95% CI）。
- 候補: `decks/candidates/*.csv` 全 26 デッキ（`01_dragapult` … `26_stw_champion`、NAIC/大会実績構成込み）。
- 現行 champion `deck.csv` は `26_stw_champion.csv` と **バイト一致**（現行デッキが候補#26として同梱）。

```bash
python3 eval/compare_decks.py --decks-dir decks/candidates \
    --n-per-pair 40 --seed 1915001 --json eval/results/sot1915_screen.json
```

## 結果（screen, n_per_pair=40, 全 351 ペア, fault 0）

| Rank | Deck | Aggregate winrate (excl. draws) | Wilson 95% |
| --- | --- | --- | --- |
| **1** | **26_stw_champion（現行 champion）** | **0.8282** | **[0.8040, 0.8499]** |
| 2 | 16_crustle_mysterious_rock_inn | 0.7522 | [0.7250, 0.7775] |
| 3 | 15_marnie_s_grimmsnarl_ex | 0.7220 | [0.6939, 0.7484] |
| 4 | 20_cynthia_s_garchomp_ex | 0.6440 | [0.6142, 0.6727] |
| … | … | … | … |
| 26 | 07_n_s_zoroark_n | 0.1213 | [0.1028, 0.1425] |

FAULTS: rejects=0 exceptions=0 fallbacks=0。生 JSON: `eval/results/sot1915_screen.json`。

## 判定

現行 champion デッキ `26_stw_champion` が **26 デッキ中 rank #1**。その Wilson 95% CI 下限
（0.8040）が #2（16_crustle, 上限 0.7775）を **上回り区間が重ならない** ため、序列は曖昧でなく、
再選定候補は screen 段階で成立しない → **confirm 不要・champion デッキ維持**。

SOT-1852（デッキ再編・4repo）で確認された「デッキ側の改善余地は枯れ、次はエージェント側」という
結論を、上位帯メタ候補プールに対しても再確認した。第4次の改善リソースは学習軸（SOT-1916
expert iteration の learned prior）に集中する。

## 受け入れ条件チェック

- [x] 上位帯メタ候補プールに対し compare_decks screen で現行デッキを再評価
- [x] champion デッキが rank #1（CI 非重複）であることを記録し、非昇格（deck.csv 不変）を判定
- [x] SOT-1893 の未実施分（デッキ再選定）に決着をつけ、改善軸をエージェント側へ集約
