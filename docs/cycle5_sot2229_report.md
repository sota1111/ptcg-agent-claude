# SOT-2229 — Kaggle順位向上サイクル 第5次（ptcg-agent-claude）

- コンペ: `pokemon-tcg-ai-battle`（系統: claude = 旧fable）
- 親サイクル: SOT-1913（自動起案の起点。Issue タイトルは新番号系で「第1次」だが、
  本 repo の改善サイクルとしては SOT-1992/2060/2114/2172 に続く第5次）
- 判定: **champion 維持（昇格なし）／分解不要（Issue 追記の一回限り例外により本 Issue 内で完結）**
- 前サイクル: 第4次 SOT-2172（PR#26, champion 維持・全11軸非昇格レビュー）

## 入力材料

- 前回提出結果: 07-29 COMPLETE public=494.5 / 07-31 ERROR → 07-31 COMPLETE public=497.1
  （ERROR は standalone packaging 起因、e11d357 で修正済み）
- 直近の完了 Issue ダイジェスト / 失敗ログ・KPI 抜粋: なし

## 改善軸と実測（seeds 2229001–2229108, 全192局, faults=0）

### 1. 宣言軸: 実試合時間予算の活用（proxy scale screen）— 不通過

第1〜4次の全 A/B は両者 0.06s の proxy 予算下の方策比較で、実提出（0.8s/決定、
クロック600s の~5%しか消費しない）の時間余地が唯一の未着手レバーだった。まず
proxy スケールで予算4倍化が効くかを screen した。

```
screen bud4x: candidate time_budget_s=0.24 vs champion 0.06 (seeds 2229001-2)
  → 11/24 = 0.458（<0.5）→ 不通過
```

予算4倍でも champion に勝ち越せない。SOT-1836（rollout 高速化 ×1.76 が勝率に
非転換）と整合し、**この探索器は追加 compute を勝率に変換できない**ことを再確認。

### 2. 派生軸: 実予算 0.8s での旧棄却レバー再 screen

再試行根拠: 過去の非昇格判定は全て 0.06s proxy 下の測定であり、実予算 0.8s では
探索量が ~13倍異なるため、proxy で沈んだ構造レバー（深化・幅）が実予算では効く
可能性が残っていた。champion と 0.8s 同予算 head-to-head で screen（N=24, seeds 2229003-4）:

| レバー | 結果 | 勝率 |
| --- | --- | --- |
| n_worlds 4→8 | 12/12 | 0.500 |
| max_tree_depth 1→2 | 14/10 | 0.583 |
| max_root_actions 6→10 | 13/11 | 0.542 |
| **mtd2 + mra10 複合** | **16/8** | **0.667** |

### 3. confirm: mtd2_mra10（実予算, 独立 seed）— 非昇格

```
confirm 前半 (seeds 2229101-104, 16局×4): 11/5, 10/6, 5/11, 8/8 → 34/64 = 0.531
拡張     (seeds 2229105-108, 16局×4):  9/7,  8/8,  9/7, 6/10 → 32/64 = 0.500
pooled: 66/128 = 0.5156  Wilson95 [0.4299, 0.6005]
```

事前登録ゲート（拡張実行前に固定）: **pooled Wilson95 下限 > 0.5 のみ昇格**。
下限 0.430 < 0.5 → **非昇格**。screen 0.667 は前サイクル群と同型の screen ノイズで、
独立 seed 拡張は正確に 0.500 へ回帰した。実予算下でも探索の深化・幅のレバーは
champion に対し中立であり、saturation 結論（第4次）は実予算スケールでも成立する。

## 提出判断 — skip（理由記録）

Issue 追記の一回限り例外は「改善実装後の**新しい** artifact を提出し、既存 artifact の
無変更再提出は行わない」ことを指示している。本サイクルは非昇格＝champion 無変更のため、
新 artifact は存在せず提出は **skip**。現 champion artifact
（`submission.tar.gz` sha256 `54776a08bf02e09130c335f7db106a0b1dee2565e19a119cde4de788205612c4`,
e11d357 packaging 修正込み）は 07-31 07:41 に COMPLETE (public=497.1) 提出済み。
fingerprint 未記録問題は残るため、次に champion が実際に変わる提出で
`[artifact:sha256:...]` が導入される（または人間が baseline 再提出を明示許可する）まで
自動提出の safe skip は継続する。

## 検証

- `python3 -m pytest tests -q` → **138 passed**（コード変更なし、docs + 計測ログのみ）
- 全192局 faults=0（rejects / exceptions / budget violations / planner fallbacks 全0）

## 申し送り（第6次へ）

- 探索・評価・学習・デッキ・予算・深化/幅の全軸が proxy と実予算の両スケールで非昇格確定。
  次サイクルで同レバーの再々試行は不可（本報告を根拠に明示 skip してよい）。
- 残る構造候補は sims-per-world 効率（determinization 1 world あたりの探索効率）と
  非ミラー相手プールへの頑健性のみだが、いずれも事前証拠なし。新シグナル
  （順位急落・新 meta・失敗ログ）が立つまで champion 維持が期待値最大。
