# STATUS

as-of: 2026-07-17

## 2026-07-17: 足音遮蔽偵測 + 偏好 A/B + PEQ 引擎 (research 選題, Ben 拍板 1+2+PEQ)
- 選題依據: RTINGS/評測研究 — 機器指標 (FR/失真/PRTF) 是 rig 地盤; 無機器指標的知覺量
  (解析力/偏好) 是本儀器地盤; 「足音頻段」查證為行銷語, 無人有數據 = 空白賽道.
- PEQ 引擎 (audio.py): eq/ 資料夾放 EQ APO/AutoEq txt (Preamp + PK/LSC/HSC), RBJ biquad
  -> scipy sosfilt. render_spec 收 eq + level_mode (peak|rms; rms 供響度匹配, 目標
  peak_dbfs-8, 防爆 0.98 cap). 正規化重構為單點 (pan 函式加 pre_normalized).
- Masked detection (masked.py + routes + UI): 目標 WAV 藏在兩段其一 (2AFC interval),
  遮蔽音固定 (預設 pink @ -18dBFS), QUEST 調目標音量 (grid -60..-6 dB, sigma 4dB,
  停止 sd<=2dB). render_masked 絕對電平混音 (不重正規化), clip guard. 驗收: 模擬觀察者
  真值 -32dB, 28 題收斂 -32.0 (CI -35.9..-28.1).
- Preference A/B (routes + UI): 兩 render spec (含 EQ) 2AFC 哪個好聽, 雙尾 p.
  ABX spec 也收 eq; 兩者 loudness_match 預設開 (level_mode=rms).
- 報表: masked staircase (dB 軸) + pref 摘要; Compare 加兩型表; CSV export 兩型.
- Codex 品質事故 #4/#5: batch 3 拒絕輸出完整檔 (太長); 3a 重出 index.html 把既有中文
  全轉亂碼 (其 shell cp950 讀檔). 處置: index.html 從 HEAD 還原+新區塊手動加;
  app.js/report.js 流程由 Claude 依既有 pattern 手寫. 教訓: Codex 不可重輸出含中文的
  既有檔; 只讓它產全新內容或純 ASCII 檔.
- Verified: 五模組 selfcheck; 三 JS node --check; id+編碼檢查; masked/pref API 端到端
  (模擬觀察者); 七種 session 型 smoke; EQ 驗證 (非法檔 400, rms level_mode 進 config).

## 2026-07-16 (五): per-source 音檔 (Ben: 球標籤+音量都加, 動工)
- Object Panner: 每球自選刺激 (列表內嵌下拉, 換選播放中即時單軌重建), 每球音量滑桿
  (voice gain 即時), WAV A/B 區段跟著 active 球走 (物件模型 {az,y,dh,stim,region,gain}),
  3D 球頂名稱標籤 (跟著拖動). 全域刺激下拉移除.
- CMAA: Source A/B 可選 (內建低頻/高頻 band noise 或任一 WAV). render_cmaa 收 stim_a/b,
  兩 token 齊頭裁 min(兩檔長, 1 秒) 後重 ramp. 問題/回饋/報表文字動態帶音源名;
  報表註明不同音源組合閾值不可互比.
- 事故與復原: Codex batch B 違反輸出格式 (給片段非完整檔), 套用時五檔被覆蓋成殘片.
  復原: 殘片備份 scratchpad -> git show 67dd555 還原四檔 + batch A index.html 從 codex
  session jsonl 重取 -> 殘片當補丁手動合併. 零損失. 教訓: 套用前先驗塊長度
  (完整檔應 >> 舊檔的 1/3), 已納入之後的套用檢查.
- Verified: 四模組 selfcheck; 三 JS node --check; id 交叉檢查; API (temp DB): wav+band
  CMAA session/render/trial/export, 非法 stim 400, 預設不變.

## 2026-07-16 (四): ABX + 頭外感 + 音場寬度 三測試 (Ben 拍板 1+2+3, 睡前交辦全自動執行)
- Codex 四批 (核心模組 / main.py 路由 / index.html+app.js / report.js+css), Claude 套用+驗收.
- ABX: 兩 render spec (stimulus/output_mode/az) 差異辨識, X 隨機, 無限重播, 精確二項 p 值
  (單尾). 比 APO 版本 = 先錄成 WAV 丟 stimuli/ 再 ABX 兩檔 (README 已記).
- Externalization: 每題評 1-5 (頭內→頭外), 方位由 seed 隨機取格點, 平均分 + 直方圖.
  主觀量表, 報表註明與客觀指標分開解讀.
- Width: 去相關雙 token 展開角 (spec A/B 各自 spread+outmode), 兩段 2AFC 誰寬,
  雙尾二項 p. WAV 兩側同檔寬度感有限, UI 建議 pink.
- 架構: audio.render_spec 泛用渲染 (單源/spread 雙源, 任一 output_mode); 三張 trial 表;
  x_is_a / a_first 為 server 端秘密 (seed 派生), 任何 API 回應不外洩 (驗過).
- Verified: 四模組 selfcheck; 三 JS node --check; JS id 交叉檢查 (80 id 全存在);
  API 端到端: ABX 秘密不洩+seeded 正解重算一致, ext rating 驗證 400/hist/mean,
  width chose_a 映射, compare 五型 ['abx','cmaa','extern','loc','width'], 舊流程回歸過.
- 修正 (Claude review): 無 — 本輪 Codex 四批零缺陷 (前兩輪各有 bug, spec 越細品質越穩).
- DB 注意: 今日 API 測試曾 rm localization.db, 07-12 的 practice/demo session 已失
  (皆非正式資料). 已重塞五型 DEMO session (id 1-5) 供報表檢視. 未來驗收改用 temp DB.
- README 加 Additional tests 節.

## 2026-07-16 (三): CMAA 分離度測試 (Codex 撰寫 x2 批, Claude 驗收)
- 背景: Ben 要客觀量測耳機「分離度」. 研究定案 CMAA (concurrent minimum audible angle,
  同時雙音源最小可辨角) + QUEST Bayesian 自適應 (25-40 題, 3-5 分/場, 免訓練).
- 新檔 cmaa.py: 純 numpy QUEST (61 點 log grid 1-60 度, cumulative-normal psychometric
  SIGMA=.12 LAPSE=.02, prior N(log15,.35), 停止 n>=40 或 n>=20 且 sd_log<=.06),
  無狀態 (posterior 由 trial history 重建, crash-safe 免 resume 邏輯).
- audio.py: band_noise (FFT bandpass pink), 低頻 200-1200 / 高頻 2k-8k 雙源,
  render_cmaa (ref±Δ/2 對稱擺位, 任一 output_mode, mix 峰值校準).
- db.py: cmaa_trials 表; list_sessions 計數含 cmaa.
- main.py: /api/cmaa/session|state|play|trial|report; /api/compare 分 type loc|cmaa.
- 前端: Setup 第三顆鈕 Start Separation Test; cmaa view (問題: 清亮聲在低沉聲哪一邊,
  左/右大鈕, 4 題 practice 含回饋後進 QUEST, 主測無回饋, replay 1x);
  報表 staircase SVG (log y 軸, 綠對紅錯, 閾值虛線+CI 帶) + Compare 分離度表.
- 修 2 bug (Codex 產出): cmaa.py frompyfunc erf 純量 .astype 炸 (改 np.asarray);
  main.py peak_dbfs 寫成必填 (spec 是 default -12).
- Verified: cmaa.py selfcheck (模擬觀察者 seeds 0-2 恢復閾值 5-13 度); 四模組 selfcheck;
  三 JS node --check; API 端到端模擬跑完 32 題閾值 7.9 度 CI 6.1-10.3 (真值 8);
  舊流程回歸 (stereo 28 題, index/sessions 200) 過. 未 commit.

## 2026-07-16: 2ch 輸出模式 (Codex GPT-5.6-Sol 撰寫, Claude 驗收)
- 背景: Pelta Core 端點只收 2ch (Savitech APO 的 7.1 downmix 需 driver 宣告 7.1 device format,
  此 SKU 未宣告); 遊戲的 7.1 選項實為遊戲內部 fold-down 成 2ch 再送出. 工具跟進此模式.
- 新增 output_mode: bed71 (原 8ch, 預設) / folddown (7.1 pan 後標準係數降混 2ch, 全圓,
  模擬遊戲鏈路) / stereo (constant-power 2ch pan, 前弧 ±90 限定).
- 變更: audio.py (folddown_71_to_stereo, pan_stereo_gains, pan_to_stereo, render_output,
  play_frame 依聲道數分 gate), main.py (/api/play + /api/session 收 output_mode, stereo 前弧
  trial order + practice, resume 依 mode 重建), index.html (setup + probe 各加 outmode 下拉),
  app.js (checkDevice 僅 bed71 檢 8ch, 時長估算, probe 傳 mode + stereo clamp).
- 工作流: codex exec read-only 當作者輸出完整檔, Claude 套用 + 獨立驗收 (Windows 沙箱下
  codex workspace-write 不可用, patch 被拒; read-only 作者模式繞開權限問題).
- Verified: python audio.py/metrics.py/db.py -> selfcheck OK; node --check app.js -> OK;
  flask test_client -> stereo 28 trials 全 |az|<=90, resume 一致, folddown 48, practice
  stereo 5 picks 前弧, bogus mode 400; git status 僅 4 個允許檔案變更.
- 未 commit. Pelta 實測下一步: folddown 模式 + Pelta 選 2ch, 跑 practice+main,
  Savitech 環繞 ON/OFF 各一場比較.

## 2026-07-16 (二): 主測試/probe 的 WAV A/B 區段 (Codex 撰寫, Claude 驗收)
- Ben: 正式測試也要能用匯入音檔; 裁決: 匯入本已支援, loop 不進正式測驗 (計時方法學),
  改加 A/B 區段修剪 — 長檔框一段, 每題只播該段, 記入 config (可重現).
- 變更: audio.py (make_stimulus region 參數 + wav_info 波形摘要), main.py (/api/wavinfo,
  session/play 傳 stim_region, pink 時存 null), index.html (setup/probe 波形容器),
  app.js (wavTrim widget 工廠 x2, probe loop 間隔隨區段長度).
- Verified: 四模組 selfcheck + node --check 過; API 驗收: wavinfo duration/600 peaks,
  壞檔 400, region 進 config, pink 忽略 region, 0.5s 區段 = 24000 samples, 過短 region raise.
- 未 commit.

## 現況
- M1-M5 完工並自檢通過. M6 (elevation Phase 2 spike) 依計畫刻意未做, 滑桿灰掉附說明.
- 檔案: audio.py, metrics.py, db.py, main.py, static/{index.html,style.css,app.js,report.js},
  stimuli/README.md, README.md, PLAN.md.

## Phase 2 object panner (2026-07-12, backend C 定案)
- 決策鏈: elevation 需 object 路徑 (7.1 bed 無高度) -> 定位為獨立 audition sandbox +
  之後正式測驗 (Ben: 兩者都要) -> backend 選 B (AudioGraph HRTF) 起步.
- Spike 推翻 B: winrt pywinrt 這個 build 沒生 AudioNodeEmitter 的 overload
  (file/submix/frame 帶 emitter 全 Invalid parameter count), 純 Python AudioGraph 無法空間化.
- 改 backend C: slab KEMAR HRTF, 純 Python, binaural stereo (Babyface 立體聲直接聽, 不需 7.1).
  Spike 驗證: 出聲 OK; 左右對應正確 (映射 slab_az=(360-our_az)%360, slab 為 CCW 正);
  高度/前後受通用 HRTF 限制 (Ben 實聽: 左右穩, 上方微弱, 前後無感; white noise 略優於 pink,
  因耳廓頻譜線索在高頻). 這是非個人化 HRTF 天花板, 非 bug; 之後可換 SOFA / backend A 測真產品.
- 實作: audio_hrtf.py (render_object/render_scene/Looper 循環播放), main.py 加
  /api/hrtf/play|stop, static/panner.js + index.html Object Panner 分頁.
  audio_hrtf.py selfcheck OK (+90 右耳能量較大確認映射; 多源 mix 不爆).
- UI 升級 (Ben 要求, 附 Atmos room-view 參考圖): 2D 圓盤+滑桿改成 three.js 3D 房間.
  vendored three r128 UMD + OrbitControls + TransformControls 進 static/vendor (離線, 無 CDN).
  orbit 相機 + 每軸 gizmo 拖拉 + drop-line/地板陰影顯示高度 + 方位 sprite 標籤.
  XYZ<->az/el/dist 轉換 (front=-Z, right=+X, up=+Y), 接同一 HRTF 後端不變.
  elev/dist 滑桿保留為 fine-tune. panner.js node --check OK, vendor 檔 200.
- 互動再修 (Ben: gizmo 易拖錯軸): 拿掉 TransformControls, 改「拖球=水平面平移, 高度=滑桿」
  (Atmos/Logic 做法). 物件模型改 {az, y(公尺), dh(水平距離)}, 送後端時轉 az/el/dist.
  三滑桿 Azimuth/Height/Distance. 頭換成有鼻子+眼睛+耳朵的 group 分前後.
- 無縫拖動 (Ben: 拖拉要放開才更新, 想即時無縫): sandbox 音訊改瀏覽器 Web Audio PannerNode
  (panningModel=HRTF). 拖球即時改 panner xyz, HRTF 內部平滑插值, 零延遲零斷點, 不走伺服器.
  Web Audio listener 面朝 -Z/+X 右/+Y 上, 與世界一致. 距離用內建 inverse distanceModel.
  device 改列 browser audiooutput + setSinkId (best-effort); 播放到瀏覽器輸出裝置,
  Ben 需把瀏覽器/系統預設輸出設成耳機. 刺激 white/pink 於瀏覽器生成 (WAV 之後可 fetch+decode).
  臉加強: 大鼻子 + 青色臉盤 + 前向箭頭 ArrowHelper + 大眼睛.
  結果: /api/hrtf/play|stop 與 audio_hrtf.py 目前 sandbox 不再呼叫, 保留給正式測驗 (backend A/離線 render).
- 房間收尾: 放大房間 (6.6x4.6x6.8) 使球最大伸手 (dh3+半徑) 不穿牆; 加天花板格線;
  Height 滑桿限 -1.45~2.6m 卡在地板/天花板間.
- 刺激 (Ben: 連續 noise 吵): 改脈衝. panner 生成 pink pulse/white pulse/click/pink cont/white cont
  (脈衝 burst+gap, 較不吵且 onset 助定位). 加 WAV 載入: main.py /stimuli/<name> 路由,
  panner.js loadWav fetch+decodeAudioData 轉 mono 迴圈, 掃 stimuli/ 的 .wav 進下拉.
  遊戲音 (腳步/槍聲/reload) 丟 stimuli/ 即用. server 重啟 -> 任務 ba2ixu1d9 (取代 be4kgaccd).
- WAV 播放器 (Ben: 長檔懶得剪, 要時間軸+AB loop): 選 WAV 時顯示波形 canvas + 兩個 A/B 把手,
  用 BufferSource loopStart/loopEnd 只循環 A→B (Web Audio 原生, 無縫接 HRTF panner). 拖把手即時更新.
  actx 提前於 init 建立 (suspended) 以便播放前 decode 畫波形. Ben 已放兩檔 (C4 beep, Walking).
- UI review 微調: WAV 播放器移到 Stimulus 下方 (Ben 要求); 加主音量滑桿 (接 master gain);
  側欄加「Editing source #N + 對應顏色圓點」標示正在編輯哪個音源 (多源時更清楚).
- 新依賴: slab, soundfile (backend C); winrt-* (spike 用, backend B 已棄可留著).
- server 背景任務: be4kgaccd (取代已停的 bo8spl1ak).

## 本次 session 後續調整 (2026-07-12)
- 修 CSS bug: .hidden 缺 !important, 被後定義的 .overlay display:flex 蓋過, 導致 pause
  遮罩一進 trial 就顯示且 Resume 壓不掉. 已加 !important.
- makeCircle 改版 (回應 UI 效度): 加時鐘方位參考 (12=前/3=右/6=後/9=左, 純標籤不量化),
  第一人稱粗體錨點 (含「你的正後方」點破背後=下方), 點擊畫射線+外圈吸附標記.
  目的: 消除俯視圖後半圈的非知覺誤點, 淨化 front-back confusion 指標. 對 ROG/Atmos 對稱不偏袒.
- 預設題數 72->48 (reps 6->4, ~5-6 分). index.html + main.py 後備值 + README + PLAN 同步.
- node --check static/app.js 過; Ben 目視新圓盤 UI 確認可用.

## 已驗證 (Verified)
- python audio.py -> selfcheck OK (constant-power panning, LFE 靜音, seeded 刺激, burst 長度)
- python metrics.py -> selfcheck OK (signed error, FB/LR confusion, binning)
- python db.py -> selfcheck OK (per-trial commit, resume indices, list)
- Flask test_client 端到端: session 建立 / practice 5 trials / main 72 trials /
  trial 存取算 FB confusion / resume 順序一致且 completed=[0,1,2] / report / compare / export 全 200.
- Step A: 2ch pink noise 實播 Analog(3+4) -> Ben 確認有聲 (發聲路徑通).
- 無 click 訊號層驗證: burst 頭尾樣本=0.0, burst->gap 邊界=5.5e-6≈靜音, LFE=0.0.
  click 成因(波形不連續)由 raised-cosine ramp 消除.

## 端點 gate 修正 (重要)
- 原用 max_output_channels<8 當關卡會誤拒空間音效端點 (Atmos/Sonic 常報實體 2ch 卻收 8ch).
- 改為探測 sd.check_output_settings(channels=8) 實際能否開串流. audio.supports_8ch().
- 實機掃描: 只有 LHDC virtual (36) 收 8ch; Babyface Analog(3+4) 開 Sonic 後仍拒 8ch
  (Sonic for Headphones 只對耳機類端點開 7.1, line-out 不生效).

## 未驗證 (UNVERIFIED — 硬體阻擋, 非程式問題, 驗收 #2)
- 真實可聽 8ch 端點播放無 click (需 DAC/APO 實際發聲 + 人耳).
- 阻擋原因: Ben 目前無「能開 8ch 又聽得到」的端點. Babyface 聽得到但收不了 8ch;
  LHDC 收 8ch 但無 LHDC 藍牙耳機. 等 ROG 耳機或 Atmos access.
  to confirm (拿到後): python main.py -> Manual Probe -> 選該端點 -> az 45 -> Play.

## 下一步 (若要續)
- M6 elevation spike: 驗證 winsdk AudioGraph 或 C# ISpatialAudioClient 能放 object 到 az/el 並聽到高度.
  通過才在 probe 頁啟用滑桿, 報表標 render_path=object.
