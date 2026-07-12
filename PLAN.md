# Localization Test Tool 詳細計畫

版本: 2026-07-12 v2 (加入手動探測模式與遊戲刺激, 尚未動工)

## 一. 已定案決策 (前次 grilling 結果)

1. Stack: Flask + sounddevice + numpy, 前端 vanilla JS + SVG, 無 build step, 無 CDN, SQLite.
2. 圖表: 手刻 SVG (polar plot, heatmap, 比較表), 離線可用.
3. 刺激: pink noise 每 trial 新 token, seed = session_id + trial_index, seed 記入 config_json. Trial 內 replay 播放完全相同 buffer.
4. 回應角度: 連續值, 0.1 度精度, 分析時才 bin.
5. response_ms: 從最後一次播放結束起算, replay_count 另記.
6. Practice: 存 DB, sessions 加 mode 欄位 ('practice'|'main'), 報表預設排除.
7. 比較視圖: 逐 session 欄位 + 相同 condition label 的 pooled 欄位 (僅同 grid 可 pool).
8. 正式測試預設: 12 方位 x 30 度步進 x 4 重複 = 48 trials, 約 5-6 分鐘, 步進與重複次數可設定.
9. 中斷 session 可 resume (trial 順序由 seed 重建), 逐 trial commit SQLite.

## 二. 音訊引擎 (不變, 關鍵約束)

- WASAPI shared mode (exclusive 會 bypass APO), 8ch / 48kHz, Windows 7.1 聲道順序 FL FR FC LFE BL BR SL SR, LFE 恆靜音.
- Endpoint 少於 8 聲道: 拒絕啟動, 提示開啟 7.1. 永不 downmix.
- Constant-power pairwise panning (2D VBAP), speaker map: FC 0, FR +30, SR +90, BR +135, BL -135, SL -90, FL -30. 正好落在 speaker 上時單喇叭輸出.
- Pink noise: 3 burst x 250ms, 100ms 間隔, 10ms raised-cosine fade, peak 預設 -12 dBFS 可設定.

## 三. 新增功能 A: 手動探測模式 (Manual Probe)

目的: 不跑正式流程, 手動設定精確方位並播放, 主觀確認 APO 的定位表現.

- 獨立頁面, 不建 session, 不寫 DB (純探索工具; 要留紀錄就跑正式 session).
- 控制項:
  - 方位角: 拖曳圓盤 + 數字輸入框, 0.1 度精度 (例: 輸入 45.0 就是客觀的右前 45 度).
  - 刺激選擇: pink noise 或 stimuli/ 資料夾內任一 WAV.
  - 播放一次 / 循環播放 (循環間隔 500ms) / 停止.
  - Peak level 滑桿.
  - Elevation 滑桿 (-90 到 +90 度): Phase 2 才啟用, Phase 1 灰掉並註明原因.
- 水平角走與正式測試完全相同的 panner 程式路徑, 保證客觀一致.

## 四. 新增功能 B: 遊戲類刺激

- stimuli/ 資料夾機制: 放入 mono 48kHz WAV 即出現在下拉選單 (setup 頁與 probe 頁共用).
  - 非 48kHz 或非 mono: 拒絕載入並提示轉檔, 不做默默 resample (資料效度優先).
  - 建議素材: 腳步聲, 槍聲, 換彈匣聲 (遊戲玩家最熟悉的方位辨認 cue). 素材由團隊自備, README 註明授權注意事項.
- 播放處理: 套用與 pink noise 相同的 burst 包裝? 否 — WAV 原樣播放 (保留 transient 特性), 只做 10ms fade in/out 防 click 與 peak normalize 到設定的 dBFS.
- 正式 session: 刺激固定整場 (混刺激會汙染資料), 記入 config_json, 比較表顯示刺激欄位. 不同刺激 = 不同 session.
- 內建合成備援: 若 stimuli/ 為空, 下拉只有 pink noise, 不合成假腳步聲 (合成品不像, 反而誤導).

## 五. 新增功能 C: Elevation (Phase 2, 需先 spike)

技術路徑分析:

| 路徑 | 高度 | 測的對象 | 狀態 |
|---|---|---|---|
| 7.1 bed + APO (現行) | 不可能, bed 無高度資訊 | 你的 APO / Atmos 的 bed 虛擬化 | Phase 1 |
| Windows Spatial Sound dynamic objects | 可, xyz 座標 | Atmos/Sonic 的 object renderer | Phase 2 |

- 兩條路徑資料不可互比, UI 與報表須明確標示 render path.
- 實作候選 (spike 決定):
  - (a) Python winsdk 套件走 WinRT AudioGraph + AudioNodeEmitter, 純 Python 但 API 覆蓋度未驗證.
  - (b) 小型 C# helper exe 用 ISpatialAudioClient, Python 以 stdin/stdout 控制, 較穩但多一個 build 產物.
- Spike 驗收: 能在啟用 Atmos for Headphones 的 endpoint 上, 把 pink noise 物件放到 az 45 / el 30 並聽到明顯高度感.
- Phase 2 範圍先只做 probe 頁的 elevation 滑桿; 正式 elevation 測試流程 (含 UI 與資料模型) 等 spike 通過後另開計畫.

## 六. 檔案結構

```
main.py         # Flask app + routes, 啟動時開瀏覽器
audio.py        # 裝置列舉, WASAPI stream, panner, 刺激合成/載入
metrics.py      # signed error, FB/LR confusion, binning
db.py           # SQLite schema + queries
static/
  index.html    # 單頁: setup / trial / report / probe 四區
  app.js        # 測試流程 + probe 控制
  report.js     # SVG polar, heatmap, 比較表
  style.css
stimuli/        # 使用者自備 WAV
README.md       # Windows 設定 checklist
PLAN.md         # 本檔
```

## 七. 資料模型

- sessions: id, participant, condition, device_name, mode, created_at, config_json
  (config_json 內含: seed, azimuth_step, reps, peak_dbfs, stimulus, render_path)
- trials: id, session_id, trial_index, target_az, response_az, signed_error, abs_error,
  front_back_confusion, left_right_confusion, replay_count, response_ms
- Signed error: 最短角距, -180 到 +180.
- FB confusion: target 對 interaural 軸鏡射 (az -> 180-az), response 在鏡射點 30 度內且前後半球翻轉; target 正好 +90/-90 排除.
- LR confusion: response 與 target 左右半球相反; target 0/180 排除.
- 30 度 grid 下鏡射點全部落在 grid 上 (30<->150, 60<->120), 指標乾淨.

## 八. 里程碑

1. M1 音訊核心: 裝置列舉, 8ch 拒絕邏輯, panner + 單元自檢 (功率和恆定, speaker-exact 單喇叭), pink noise 合成, 無 click 播放.
2. M2 測試流程: setup, practice 含回饋, main 含 resume, 逐 trial commit, pause.
3. M3 報表: 四視覺化 + CSV export + 比較視圖.
4. M4 Manual probe 頁 (azimuth only).
5. M5 遊戲刺激資料夾機制.
6. M6 (Phase 2) elevation spike, 通過才續建.

## 九. 驗收標準 (原 5 條外新增)

6. Probe 頁輸入 45.0 度, 聽到的聲音來自右前 45 度方向, 循環播放無 click.
7. stimuli/ 放入 mono 48k WAV 後, setup 與 probe 下拉出現該檔, session config_json 記錄刺激名.
8. Elevation 滑桿在 Phase 1 呈灰色並附說明文字.

## 十. 未決事項

無. 2026-07-12 Ben 拍板:
1. Elevation 接受 Phase 2 spike 定位 (測 object renderer, 資料與 bed 路徑不可比, UI 標示 render path).
2. 遊戲刺激採 stimuli/ 資料夾自備制, 不內建合成音.
