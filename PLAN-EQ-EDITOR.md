# PLAN: EQ Editor 分頁

狀態: 已設計未動工. Ben 2026-07-17 批准設計方向, 因 context 用盡先落計畫.
下一個 session 讀完本檔即可直接執行, 不需重新推導.

## 目標

新 nav tab「EQ Editor」: 圖形化編輯 parametric EQ 檔 (eq/ 資料夾的 EQ APO/AutoEq txt),
拖點調參 + 即時試聽 + 存檔. 存出的檔直接被現有 ABX / Preference 測試選用 (檔案制不變).

## 已定案的設計決策 (勿重議)

1. 互動 = FabFilter Pro-Q 四件套: 拖點 (drag=Fc+Gain), 滾輪=Q, 合成曲線即時重畫,
   每 filter 一色點. 下方同步一張數字列表 (type/Fc/Gain/Q, 可打字, 可增刪).
2. 曲線與試聽的係數**全部在 JS 用 RBJ cookbook 自算** (移植 audio.py 的 _biquad_sos),
   試聽走 IIRFilterNode (feedforward=[b0,b1,b2], feedback=[1,a1,a2] per filter, 串鏈).
   **禁用原生 BiquadFilterNode 的 lowshelf/highshelf**: Web Audio spec 寫死 shelf S=1,
   無視 Q (MDN + WebAudio/web-audio-api-v2#67, 2021 未修), AutoEq shelf 會失真.
   自算係數 = 曲線/試聽/伺服器測試三者 100% 一致.
3. 曲線圖: canvas, log 頻率軸 20Hz-20kHz, y 軸 ±18 dB. 合成曲線 = 各 sos 級聯的
   |H(e^jω)| 乘積 (dB 相加), 逐 filter 疊加 + preamp. 畫法參考 CrinGraph (0BSD) 的軸刻度.
4. Preamp: 手動欄位 + 「自動」鈕 (= -max(正增益總和的峰值), 簡化為 -max(0, 合成曲線最大值)).
5. 試聽: loop 播放選定刺激 (pink pulse / stimuli WAV) 過 EQ 鏈, 拖點即時變聲.
   走瀏覽器輸出 (同 Object Panner 的 Web Audio 路徑), 不經伺服器.
6. 存檔: POST /api/eq/save {name, text} -> 寫 eq/<name>.txt (檔名清洗: 只留
   [A-Za-z0-9_-], 強制 .txt, 拒絕路徑分隔). 輸出標準 EQ APO 格式:
   Preamp: <g> dB / Filter N: ON PK Fc <f> Hz Gain <g> dB Q <q> (shelf 用 LSC/HSC).
   讀檔: 復用現有 GET /api/eqs + 新 GET /api/eq/load?name= (回傳 parse_eqapo 結果,
   audio.py 已有 parser).
7. 全部自刻 vanilla JS (~300 行), 無新依賴, 無 vendor. 抄 pattern 的來源僅供參考:
   weq8 (ISC, editor 結構), CrinGraph (0BSD, log 軸), FabFilter 手冊 (手勢).

## 分工 (重要 — Codex 事故教訓)

- **JS/HTML (含中文字串) 一律 Claude 手寫**. Codex 事故 #4/#5: 拒輸出大檔;
  重輸出含中文的既有檔時全轉亂碼 (其 shell cp950). 見 STATUS 2026-07-17 節.
- 可派 Codex 的部分: 純 ASCII 新模組 (若拆得出來, 例如 eq-math.js 的 RBJ 係數
  + 頻率響應計算, 指定輸出全新檔案). main.py 的 /api/eq/save|load 兩個小路由
  可派可自寫 (量小, 自寫更快).
- 套用 Codex 輸出前必驗: (a) 完整檔長度 >= 舊檔 90%, (b) 無 '�' 亂碼字元.

## 檔案級 spec

1. **static/eq-editor.js** (新): 
   - state: {name, preamp, filters:[{type:'PK'|'LS'|'HS', fc, gain, q}]}
   - rbjSos(f) -> [b0,b1,b2,a1,a2] (移植 audio.py _biquad_sos, fs=48000)
   - responseDb(freqs[]) -> 合成曲線 (含 preamp)
   - canvas 繪製: 軸 (log 20-20k, 刻度 20/50/100/.../10k/20k; ±18dB 格線), 合成曲線,
     各 filter 色點 (色盤複用 panner.js COLORS)
   - 手勢: pointerdown 選最近點 (or 空白處雙擊新增 PK), drag 改 fc(log x)/gain(y),
     wheel 改 q (×1.1 步進, clamp 0.1-10), delete 鍵刪選中
   - 列表 render + 雙向同步; preamp 欄 + auto 鈕
   - 試聽: AudioContext + IIRFilterNode 鏈 (每次參數變 = 重建鏈; IIRFilterNode
     係數不可變, 所以拖曳中 throttle ~150ms 重建, 接受微小斷點 — 或 crossfade
     兩條鏈, 先簡單版)
   - 存檔/載入/另存 UI
2. **static/index.html**: nav 加「EQ Editor」鈕 (data-view="eqedit"), 新
   section id="eqedit" (canvas id="eq-canvas" 720x360 + 列表容器 + 控制列).
   script tag 加 eq-editor.js.
3. **main.py**: POST /api/eq/save (檔名清洗如上, 寫檔後回 {ok, name});
   GET /api/eq/load?name= -> jsonify(audio.parse_eqapo(name)) (400 on error).
4. **static/style.css**: eqedit 區塊樣式 (canvas 邊框, 列表緊湊表格).
5. **README.md**: EQ Editor 一段.

## 驗收清單

- [ ] python audio.py / masked.py / cmaa.py / metrics.py / db.py 全過 (不應被動到)
- [ ] node --check 全部 JS
- [ ] id 交叉檢查 (現有腳本 pattern) + 無 '�'
- [ ] API: save -> eq/ 出現檔案且 GET /api/eqs 列出; load 回傳與 audio.parse_eqapo
  一致; 檔名注入 (../x, 斜線, 無副檔名) 全被拒 400; 存出的檔能被 ABX session 驗證通過
- [ ] JS 係數與 Python 一致性: 用一組已知 filter (PK 1kHz +6dB Q1.41) 在兩邊算
  1kHz 處響應, 差 < 0.1 dB (寫進 selfcheck: 伺服器端算 golden 值, 前端 console
  assert 或直接在驗收腳本用 node 跑 eq-editor.js 的純函式 — eq-math 函式寫成
  可被 node 單獨 require/執行的形式)
- [ ] 手動: 拖點曲線即時動, 試聽即時變聲, 存檔後 ABX 下拉可選

## 風險/註記

- IIRFilterNode 係數不可變 -> 拖曳中重建鏈會有微斷點; v1 接受, 若不能忍再做
  雙鏈 crossfade.
- 試聽走瀏覽器預設輸出 (同 panner), 提醒使用者系統輸出設到耳機.
- eq/ 資料夾已存在且 .gitignore 未排除 (EQ 檔要進 repo? 建議: 排除使用者檔,
  同 stimuli WAV 政策 — 動工時加 .gitignore 條目 eq/*.txt 並確認 Ben 意向).

## 現況背景 (2026-07-17)

- repo HEAD 2f2a1d3 (masked+pref+PEQ 引擎已上), 全部已推 GitHub.
- 工具現有測試: 定位/probe/CMAA/ABX/頭外感/寬度/足音遮蔽/偏好 + Object Panner.
- EQ 現況: 檔案制 (eq/*.txt), ABX/Pref 可選, 有 parse_eqapo/apply_eq/render_spec
  (audio.py), GET /api/eqs. 無編輯 UI — 本計畫補這塊.
