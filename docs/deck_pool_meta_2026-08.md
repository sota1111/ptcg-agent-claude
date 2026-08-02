# Champion play-deck re-optimization vs 2026-08 meta (SOT-2284)

2026-08-02。Kaggle順位向上サイクル第4次（親 SOT-2277）。公開スコアの相対低下
(626.9→540→526) を受け、**アルゴリズムでなくデッキ(メタ適合)側のレバー**で現行8月メタに
対する期待勝率を上げられるかを検証する。champion アルゴリズム(`main.py` `FABLE_CONFIG`)は
無変更、`deck.csv`(=`26_stw_champion`) の軸のみを扱う。前回のデッキ再検証は 07-27 の
SOT-2060(`docs/deck_meta_revalidation_sot2060.md`, 非昇格・維持)。

champion デッキ骨子（`deck.csv` = `26_stw_champion`, 9 種 60 枚）:

| x | id | card | 役割 |
| --- | --- | --- | --- |
| 4 | 722 | Snover | Basic（進化元） |
| 4 | 723 | Mega Abomasnow ex | Stage1 主アタッカー |
| 2 | 721 | Kyogre | Basic サブアタッカー |
| 4 | 1145 | Mega Signal | Item（加速/展開） |
| 4 | 1227 | Lillie's Determination | Supporter |
| 4 | 1235 | Waitress | Supporter |
| 2 | 1205 | Cyrano | Supporter（サーチ/展開） |
| 1 | 1158 | Maximum Belt | Pokémon Tool（**ACE SPEC**, 1 枚上限） |
| 35 | 3 | Basic {W} Energy | エネルギー |

---

## 1. 現行(2026-08)メタ調査 — 07-27 → 08-01 の差分

ソース: `https://ptcg-meta.vercel.app/daily/2026-08-01.html`（`tools/deck_update.py --fetch`
でパース、`decks/meta/snapshots/2026-08-01.json` にコミット。08-02 のページは 404=未発行
のため直近の 08-01 を採用）。

### Top100 シェア（08-01, 括弧内は 07-27）

| # | archetype | 08-01 | 07-27 | 傾向 |
| --- | --- | --- | --- | --- |
| 1 | マリィのオーロンゲex (悪) | **62.0%** | 54.0% (#1) | ↑ さらに寡占化 |
| 2 | イワパレス (草) | 7.0% | 6.0% (#3) | ↑ LB #2 へ上昇 |
| 3 | フーディン | 7.0% | **26.0%** (#2) | ↓↓ 大幅減 |
| 4 | オーガポン みどりのめんex (草) | 6.0% | — | **NEW** 草ex台頭 |
| 5 | バチンキー/カミッチュ/ペロッパフ | 5.0% | 1.0% (#9) | ↑ |
| 6 | ドラパルトex | 4.0% | 4.0% (#4) | → 横這い |
| 7 | ノココッチ/メガミミロップex (無色) | 3.0% | — | **NEW** かつ **LB #1**(1257.9) |
| 8 | ロケット団のワナイダー | 3.0% | 3.0% (#5) | → |
| 9 | タケルライコex (ドラゴン) | 1.0% | 1.0% (#7) | → LB 上位維持 |
| 10 | シロナのガブリアスex | 1.0% | 3.0% (#6) | ↓ |
| 11 | ヤドキング | 1.0% | — | NEW |

Top100 から消失: ノココッチ(単体), メガスターミーex。

### LB リーダー（08-01 上位）

`ノココッチ/メガミミロップex`(無色, 1257.9) が **新盤面リーダー**＝低シェア×高順位
（07-27 の タケルライコ パターンの再来）。以下 イワパレス(草,1175.3)、マリィのオーロンゲ
ex(悪,1169.1)、オーガポン みどりのめんex(草,1157.6/1143.6)、タケルライコex(1153.5)。

### 差分の要約（champion への含意）

1. **マリィのオーロンゲex(悪)がさらに寡占**(54→62%)。対悪の安定択が引き続き最重要。
2. **草の台頭**: オーガポン みどりのめんex(NEW #4) + イワパレス上昇(#2)。Water 系 champion に
   とって不利になり得るタイプ分布のシフト。
3. **盤面リーダーが 無色 ノココッチ/メガミミロップex に交代**(低シェア高順位)。ex 主体で
   高速。フィールド全体が **ex 濃度上昇 + 高速化** 方向。
4. **フーディン急減**(26→7%)。07 に想定した対フーディン枠の重要度は低下。

→ champion(Mega Abomasnow ex/Kyogre, Water)の調整仮説: **ex 濃度上昇・高速化した 08 フィールドに
対し、サブアタッカー厚み or 展開安定性を微増**させる非構造調整に価値があるか。

---

## 2. デッキ調整候補（≤2 案・非構造・legal）

`main.py` 骨子と全カード ID を維持し、**既存カードの枚数再配分**のみ（新規カード投入なし＝
engine-pool/legality リスクを排除。`eval/deck_validator.py` 3/3 valid）。ACE SPEC の Maximum
Belt は 1 枚上限のため増量不可（2 枚案は legality NG で棄却済み）。

| 候補 | 変更 | 狙い |
| --- | --- | --- |
| A `kyogre3` | −1 Water Energy(35→34), **+1 Kyogre(2→3)** | 高速化した 08 フィールドへ、独立して立つ Basic サブアタッカーを厚くしブリック耐性/二の矢を確保 |
| B `cyrano3` | −1 Water Energy(35→34), **+1 Cyrano(2→3)** | 展開サーチ Supporter を増やし、寡占する悪/草 ex を相手に序盤の展開安定性で先行 |

エネルギーは 35→34（Water 単色 60 枚デッキでは依然潤沢）。

---

## 3. screen → confirm（self-mirror 直接 A/B, 実予算 0.8s, 独立 seed）

手法（SOT-1940/2050 の教訓厳守: 非ミラー比較・単発最上位はミスリード → **self-mirror 直接
A/B + 独立 seed 必須**）: 候補 deck を載せた champion(A=`mcts` FABLE_CONFIG) vs 現行 deck を
載せた champion(B=同 config)、`eval/bench.py --deck <cand> --deck-b deck.csv`、先後入替
(bench 内蔵)、`time_budget_s=0.8`。昇格ゲート = **候補の pooled Wilson95 下限 > 現行の点推定**。
現行の点推定は直接 A/B では `1 − 候補winrate`。

各 shard は `eval/bench.py --agent-a mcts --agent-b mcts --n 16 --deck <cand> --deck-b deck.csv
--config-a FABLE_CONFIG --config-b FABLE_CONFIG`（先後入替は bench 内蔵）。生 JSON は
`eval/results/sot2284/{screen,confirm}_*_s*.json`、ドライバは同 dir `run_ab.sh`。

### screen（各候補 4 独立 seed × n=16 = 64 局）

| 候補 | seeds | pooled winrate_a | Wilson95 | 判断 |
| --- | --- | --- | --- | --- |
| A `kyogre3` | 2284101–104 | **35/64 = 0.547** | [0.426, 0.663] | 最上位（>0.5・僅差） |
| B `cyrano3` | 2284201–204 | 27/64 = 0.422 | [0.309, 0.544] | 現行 deck 未満 → 棄却 |

screen 最上位 = 候補 A。候補 B は点推定で既に現行 deck を下回るため confirm 対象外。

### confirm（候補 A を **独立追加 seed** 2284111–114 × n=16 = 64 局で裏取り）

| seed | winrate_a | fault |
| --- | --- | --- |
| 2284111 | 7/16 = 0.4375 | 0 |
| 2284112 | 7/16 = 0.4375 | 0 |
| 2284113 | 7/16 = 0.4375 | 0 |
| 2284114 | 6/16 = 0.3750 | 0 |
| **confirm pooled** | **27/64 = 0.422** | 0 |

### 候補 A pooled（screen + confirm, 128 局）

| 指標 | 値 |
| --- | --- |
| candidate A winrate_a | **62/128 = 0.484** |
| Wilson95 (excl. draws) | **[0.3995, 0.5701]** |
| 現行 deck 点推定 (= 1 − 候補winrate) | 0.516 |
| fault/budget違反（全 shard） | **0** |

screen の 0.547 は**上振れ**で、独立 confirm seed では 0.422 へ回帰し、pooled 128 局で 0.484
＝現行 deck と実質パリティ（self-mirror・骨子ほぼ同一なら期待どおり）。SOT-1940/2050 の教訓
（単発最上位 seed はミスリード → 独立 confirm 必須）が再現した。

---

## 4. 判定 — **非昇格（NON-PROMOTION）**

昇格ゲート: 候補 A pooled Wilson95 **下限 0.3995 > 現行 deck 点推定 0.516** → **偽**。加えて候補 A の
点推定 0.484 自体が 0.5 未満で、現行 deck が少なくとも同等以上。候補 B(0.422) は screen で既に棄却。

→ **どの候補も現行 `deck.csv`(=`26_stw_champion`) を有意に上回らない。`deck.csv` は無変更（改変して
いないため revert 不要）。champion アルゴリズム(`main.py` FABLE_CONFIG) も無変更。** 成果は本メタ調査
(§1) と self-mirror 直接 A/B 証跡(§3, `eval/results/sot2284/`) の docs のみ。

**含意**: 8 月フィールドは ex 濃度上昇・悪寡占・草台頭というシフトはあるが、champion の play-deck を
枚数再配分レベルで触っても self-mirror 期待勝率は動かない（デッキ軸はこのサイクルでも飽和）。デッキ
軸で真に前進するには、非構造再配分ではなく (a) 新規カード投入を伴う構造変更（engine-pool/legality の
拡張が前提）か、(b) SOT-2282 の拡張ガントレット等 **非ミラーのフィールド代表オラクル**上での評価が要る。
Kaggle 提出は本 Issue 対象外（親 SOT-2277 の再開 run のみ）。

---

## 受け入れ条件（SOT-2284）

- [x] 現行 8 月メタ調査と 07 月からの差分が記録されている（§1）
- [x] ≤2 案のデッキ候補を self-mirror 直接 A/B（実予算 0.8s・独立 seed）で screen→confirm（§2–3）
- [x] 昇格判定（候補 CI 下限 > 現行点推定）を明示 → **非昇格**。deck.csv 無変更（改変なし＝revert 不要）+ docs 証跡（§4）
- [x] pytest green（deck 軸は無変更、`vendor/ptcg-agent-core` submodule 未 checkout の 1 件のみ環境要因で pre-existing）／ Kaggle 提出は行っていない（提出は親 SOT-2277 の再開 run のみ）
