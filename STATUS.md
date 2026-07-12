# STATUS

as-of: 2026-07-12

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
