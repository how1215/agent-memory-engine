# Agent Memory Engine 面試問答與實作規劃

本文件整理面試時介紹 Agent Memory Engine 的建議說法、技術問題回答，以及可以繼續實作的功能與優化方向。內容以目前 repository 的實際程式碼、測試與 benchmark 結果為準；尚未實作的項目會明確標示為規劃，不把設計想法誤說成既有功能。

## 30 秒版本

> **Agent Memory Engine 是一個 framework-agnostic、local-first 的 AI agent 長期記憶引擎。** 我用 Python 建立 capture、store、retrieve、context construction 的完整 pipeline，並以 `MemoryStore` protocol 隔離 persistence。預設使用 dependency-free BM25，也可選擇 multilingual embedding hybrid search；Pi 只是第一個 TypeScript adapter，透過明確的 opt-in request 將相關記憶注入 context。系統目前具備 SHA-256 去重、atomic write、token budget 和離線 retrieval benchmark，同時清楚標示尚未完成的 schema migration、tenant isolation 與 lifecycle policy。

## 2 分鐘版本

> Coding agent 的 conversation window 只在單一 session 有效，session 結束後，像是「這個專案使用哪個 package manager」、「測試要怎麼執行」或使用者偏好就會消失。因此我把長期記憶拆成四個清楚的階段：capture、store、retrieve、inject。
>
> Capture 的核心 API 與 CLI 不依賴 agent framework；目前 Pi adapter 提供 `remember` tool。agent 將適合長期保存的事實整理成一句 summary 並附上 tags。Python engine 透過 `make_observation` 建立 observation；ID 是 summary 的 SHA-256，因此相同內容可以 idempotently 去重。
>
> Store 預設使用單一 JSON 檔案，不需要資料庫或常駐服務，也方便使用者直接檢查。寫入時先建立同一目錄下的 temporary file，flush 並 `fsync` 後以 `os.replace` 原子替換正式檔案。檔案不存在、JSON 格式錯誤或 root shape 不正確時會載入空 store，避免記憶功能故障導致 agent 無法啟動。不過目前沒有 multi-process locking，因此它是單一本地使用者的 prototype，而不是並行寫入的 production store。
>
> Retrieval 的預設路徑會把 summary 與 tags 合併後用輕量 tokenizer 切詞，再以 Okapi BM25 排序；英文與數字以 token 處理，CJK 則以單字元處理。BM25 的優點是快速、可解釋、可重現，對 command、檔案路徑和 library name 等精確術語特別有效。若設定 `AGENT_MEMORY_HYBRID=1`，系統會 lazy-load multilingual MiniLM，將 BM25 normalized score 與 cosine similarity 以 `alpha` 加權合併，處理同義、改寫與跨語言查詢。baseline 只回傳 BM25 分數大於零的結果；hybrid 則目前依混合分數排序。
>
> 最後，`build_injection` 以約 `characters / 4` 估算 token 數，在預設 2,000 token budget 內依排名加入記憶。Pi adapter 只有在 prompt 使用 `@memory` 時，才於 `before_agent_start` 查詢 Python CLI；一般 request 不啟動 retrieval subprocess，也不新增 context。若 subprocess 失敗就直接略過記憶，讓 memory 是 enhancement 而非 hard dependency。這個邊界也讓 Python engine 可以獨立用 API、CLI 或 benchmark 驗證。

## 系統技術架構

| Layer | 技術 | 用途 |
| --- | --- | --- |
| Agent integration | `adapters/pi/` | 第一個 adapter；提供 `remember` 與 opt-in injection |
| Process boundary | TypeScript `spawnSync` + framework-neutral CLI | 讓 runtime 以明確命令介接，且可獨立測試 |
| Capture/orchestration | Python 3.10+、`agent_memory_engine/service.py` | 建立 observation、選擇 retriever、組裝 injection |
| Persistence contract | `MemoryStore` protocol + `set_store()` | 將 use case 與 backend 解耦，預留 SQLite/service backend |
| Current persistence | JSON + SHA-256 + atomic `os.replace` | 可讀的本地持久化、內容去重與避免半成品寫入 |
| Lexical retrieval | 自製 tokenizer + Okapi BM25 | dependency-free、deterministic 的關鍵字檢索 |
| Semantic retrieval | sentence-transformers multilingual MiniLM | optional 的語意與跨語言相似度搜尋 |
| Hybrid ranking | normalized BM25 + cosine similarity | 結合精確術語匹配與語意召回 |
| Context control | approximate token budget | 限制注入內容，避免侵蝕 agent 工作 context |
| Interface | `agent-memory capture/retrieve/inject` | 可手動操作、除錯與整合其他 adapter |
| Evaluation | JSONL corpus/query + Recall/MRR/nDCG | 重複測量 retrieval 品質，且使用 temporary store |
| Quality | pytest + GitHub Actions | Python 3.10、3.11、3.12、3.13 的自動測試 |

## 主要資料流

```text
User / Pi agent
    ├─ remember(summary, tags)
    │      ↓
    │  TypeScript extension → python -m agent_memory_engine.cli capture
    │      ↓
    │  make_observation → JsonStore.add → atomic JSON write
    │
    └─ prompt prefixed with @memory
           ↓
       input removes marker → before_agent_start
           ↓
       python -m agent_memory_engine.cli inject
           ↓
       JSON store → BM25 或 optional hybrid retrieval
           ↓
       token-budgeted memory block → Pi agent context
```

## 從 Pi prototype 到通用引擎的重構

目前已把 Python package 改為 `agent_memory_engine/`，並將 Pi integration
移到 `adapters/pi/`。核心不 import Pi SDK；新的 `MemoryStore` protocol 與
`set_store()` 是 storage dependency inversion 的第一步。CLI 與環境變數
改為 `agent-memory`、`AGENT_MEMORY_*`，舊的 `pi-memory` 與
`PI_MEMORY_*` 暫時保留相容性。

面試時要明確說這是「可擴充基礎」，不是已經完成所有抽象：目前
service 仍使用 process-global state，retriever 尚未形成完整 interface，
JSON 是唯一 backend，也還沒有 tenant/workspace schema。下一步會先做 typed
schema、migration、user-controlled deletion，再做 SQLite 與多 adapter；詳細
驗收條件見 `docs/architecture.md` 與 `docs/roadmap.md`。

## 目前已完成的設計重點

### 1. Capture 與資料模型

- observation 包含 `id`、`sessionId`、毫秒 timestamp、`toolName`、`summary`、`tags`。
- `id = SHA-256(summary)`，重複 summary 不會新增第二筆記憶。
- Pi tool 的 summary 被要求是一句 durable fact，降低把短期對話全部寫入記憶的風險。
- CLI 支援 `capture --summary --session --tags`，extension 則把 tags array 轉成逗號分隔字串。

### 2. 可恢復的 JSON persistence

- `JsonStore` 對缺失、損壞或錯誤形狀的 JSON 以空資料處理。
- 每次新增或清除都會完整寫入，temporary file 與 destination 位於同一目錄，確保 `os.replace` 的原子性。
- 目前用單檔案模型換取可讀性與零服務依賴，代價是大資料量、並行 writer 與查詢效率有限。

### 3. BM25 與 multilingual tokenizer

- BM25 參數預設為 `k1=1.5`、`b=0.75`。
- tokenizer 將英文/數字轉小寫 token，CJK 以單一字元切分，不引入 segmenter。
- ties 保留輸入順序，讓 benchmark 結果可重現。
- `retrieve` 會排除 lexical score 為零的文件，避免小 corpus 中不相關記憶被回傳。

### 4. Optional hybrid retrieval

- embedding model lazy-load 並以 `lru_cache` 快取，baseline 使用者不需安裝 ML dependency。
-預設模型是 `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`。
- 分數公式：`alpha × normalized_BM25 + (1 - alpha) × cosine_similarity`，`alpha` 預設為 `0.3`，可由 `AGENT_MEMORY_HYBRID_ALPHA` 覆寫。
- embedding 不可用時，目前沒有在 Python core 自動 fallback 到 BM25；這是後續可靠性工作，而 extension 只會安全略過整個 injection。

### 5. 評估與目前結果

repository 內有 compact（30 memories / 21 queries）與 extended（100 memories / 40 queries）資料集，合計 130 筆 memory 與 61 個 labeled queries。benchmark 每次使用 temporary JSON store，不會污染使用者的真實記憶檔案。

| Dataset | Retriever | Recall@5 | MRR | nDCG@5 |
| --- | --- | ---: | ---: | ---: |
| Compact | BM25 | 0.810 | 0.810 | 0.802 |
| Compact | Hybrid, α=0.3 | **1.000** | **0.914** | **0.936** |
| Extended | BM25 | 0.838 | 0.826 | 0.795 |
| Extended | Hybrid, α=0.3 | **0.938** | **0.943** | **0.910** |

這些是 checked-in fixture 上的離線結果，不是 production traffic，也不是端到端答案正確率。README 與 case study 已明確區分已量測結果和未驗證假設。

## 常見面試問題

### 為什麼要做 agent memory，而不是直接保留完整 conversation？

完整 conversation 會快速消耗 context，也包含大量只對當下任務有用的短期資訊。這個專案刻意要求 agent 擷取 concise、durable facts，再跨 session 檢索；conversation compaction 與 persistent memory 解決的是不同生命週期問題，兩者可以互補。

### 為什麼要把 Pi 移到 adapter，而不是放在 core？

成熟 memory system 必須服務不同 agent runtime。若 core 直接依賴 Pi event 或 message type，storage、retrieval 與 lifecycle policy 就無法獨立測試和重用。目前依賴方向是 `adapters/pi → agent_memory_engine`；Pi 負責事件翻譯與 graceful degradation，核心只負責 memory use case。第二個 adapter 將用來驗證這個邊界是否真的通用。

### `MemoryStore` protocol 是否代表 storage abstraction 已完成？

還沒有。它目前只抽出 `add/all/clear`，足以隔離現有 JSON backend 並支援 dependency injection，但還缺 typed record、scoped query、pagination、delete、transaction 與 capability semantics。合理順序是先建立 backend contract tests 和 versioned schema，再加入 SQLite，避免先做一個無法表達 production requirement 的過度抽象。

### 為什麼預設使用 BM25？

BM25 不需要模型、速度快、結果 deterministic 且容易 debug。coding project 的 package manager、CLI command、檔案路徑與 library name 常需要 exact match，BM25 比純語意相似度更可靠。需要處理「package manager」對「pnpm」或跨語言查詢時，再啟用 hybrid。

### 為什麼不用純向量搜尋？

純 embedding 可能將語意相近但不是目標的記憶排前面，也不一定可靠地辨識特殊術語或精確命令。BM25 提供 lexical signal，embedding 補足 vocabulary mismatch；兩者組合也保留 dependency-free baseline 作為 fallback 與對照組。

### 為什麼不用資料庫或專門的 vector database？

目前目標是單一開發者的 local-first 小型 corpus。JSON 可直接檢查、不需服務、部署成本低；BM25 也能直接在記憶列表上計算。這不是規模化的最終答案，若需要多進程、數十萬筆資料、metadata query 或高併發，應遷移 SQLite/FTS5 或其他 transactional/indexed store。

### SHA-256 去重的限制是什麼？

它只對完全相同的 summary 去重；同一事實若換一種措辭，仍會產生不同 ID。這是有意選擇的簡單、可預測行為，而不是 semantic deduplication。未來可加入 canonicalization、相似度門檻或人工合併，但必須避免誤刪兩個其實不同的規範。

### 如何保證 JSON 寫入不損壞？

先在 destination 同一目錄建立 temporary file，寫完後 flush、`fsync`，再使用 `os.replace`。中斷時原檔仍存在，temporary file 也會在例外路徑清理。這解決 partial write，但沒有解決多進程同時讀寫造成的 lost update，因此不能宣稱具備完整 concurrency safety。

### 如何控制注入內容不超過 context？

`build_injection` 先計算 header 的估算 token，再依 retrieval 順序逐筆加入 summary；超過 budget 就停止。核心使用 `len(text) // 4`，避免 tokenizer dependency，但對 CJK 或實際模型可能不準。正式整合應使用目標模型的 tokenizer，並加入單筆過長記憶的截斷策略。

### TypeScript 與 Python 為什麼透過 subprocess？

這讓 Pi extension 保持輕量，Python retrieval engine 可用 CLI、測試與 benchmark 獨立驗證，兩邊的責任也清楚。代價是每次 capture/inject 都有 process startup cost，且目前使用 `spawnSync` 會同步等待；更高頻率或更低 latency 的版本可改為 daemon、HTTP/Unix socket 或直接重寫成 TypeScript library。

### memory engine 失敗時會怎樣？

Pi adapter 檢查 subprocess status；`before_agent_start` 在失敗或沒有輸出時直接 return，agent 仍可正常工作。這是將 memory 定位為 enhancement 而非 hard dependency 的 graceful degradation 設計。不過目前錯誤只回傳簡單文字，缺少 timeout、structured logging 與 hybrid-to-BM25 fallback。

### benchmark 的 Recall、MRR、nDCG 分別代表什麼？

Recall@k 衡量標記為 relevant 的 memory 有多少被帶進 top-k；MRR 關注第一筆 relevant memory 的排名；nDCG@k 反映整個 top-k 順序。三者一起看可以避免只用單一指標掩蓋「有找回來但排得很後面」的問題。目前資料集是人工標註 fixture，仍需更大且 held-out 的資料驗證泛化性。

### 目前最大的 failure boundary 是什麼？

系統能保存和找回記憶，但沒有 automatic retention、sensitive-data classification、encryption、user-facing deletion 或 prompt-injection defense。hybrid model 也可能下載失敗或產生不理想的語意排序。它目前是可稽核的 local prototype，不應直接當成多使用者 production memory platform。

## 可以主動提到的成果

- 完成 capture → persistent store → retrieval → context construction 的完整生命週期。
- 將框架無關核心與 `adapters/pi/` 分離，避免 core 依賴特定 agent SDK。
- 定義 `MemoryStore` protocol 與 `set_store()` seam，為 backend contract 演進建立基礎。
- JSON store 使用 SHA-256 deduplication、atomic write 與 malformed-file recovery。
- 實作無第三方 runtime dependency 的 multilingual BM25 ranker。
- 提供 optional multilingual embedding hybrid search，且 model lazy-load/cache。
- 透過 Pi extension 的 `remember` tool、`@memory` opt-in 與 `before_agent_start` hook 整合。
- 以 approximate token budget 限制注入內容，避免無限制塞入 context。
- 建立 130 memories / 61 labeled queries 的 benchmark，包含 same-topic distractors 與 multilingual records。
- BM25 和 hybrid 都有 pytest coverage，CI 針對 Python 3.10–3.13 執行測試與 benchmark smoke test。
- 使用 temporary store 執行離線評估，避免 benchmark 修改真實使用者資料。

## 談論實驗結果時的注意事項

可以誠實說明：

> 在 repository 提供的 labeled fixtures 上，hybrid retrieval 的 Recall@5 從 extended dataset 的 0.838 提升到 0.938，MRR 從 0.826 提升到 0.943；但這是離線資料集結果，尚未代表真實使用情境，也沒有量測端到端 agent answer quality、latency 或成本。

不要宣稱：

- hybrid 一定比 BM25 好；目前結果只來自既有 fixtures。
- memory 能防止 hallucination；它只提供檢索上下文，沒有 citation verifier 或 answer judge。
- JSON store 支援安全的多進程併發；目前沒有 file locking。
- token budget 精確等於模型 tokenizer 的 token 數；目前是 `characters / 4` heuristic。

面試時應分開說明「已實作」、「已在 fixture 觀察到」和「仍待驗證的假設」。

## 收尾說法

> 我在這個專案中最重要的工程體會是，agent memory 不只是把資料寫到檔案，而是要同時處理資料生命週期、retrieval quality、context budget、跨 runtime 整合，以及記憶功能故障時的 failure boundary。下一階段我會先補上品質與安全的可量化基礎，再逐步改善 storage、latency 和使用者操作體驗，而不是直接加入更多難以驗證的模型功能。

# Future Work 與可實際執行方向

以下方向特別以「可以直接在目前 repository 開工」為目標，並依建議優先順序排列。

## 第一優先：先建立可持續的品質基線

### 1. 擴充 benchmark 與 regression evaluation

**實作方式：**

- 擴充 `benchmark/corpus*.jsonl` 與 `queries*.jsonl`，加入真實使用情境：同一規範的不同說法、互相衝突的規範、短 query、CJK/英文混合與無相關結果。
- 在 `benchmark/run_benchmark.py` 增加 `precision@k`、hit rate、平均 query latency 與 indexing throughput。
- 將 BM25、hybrid alpha、不同 model 的結果輸出成 JSON，保留每次實驗設定。
- 在 CI 先加入不過度嚴格的 smoke threshold，避免模型或排序改動造成未察覺的品質退化。

**驗收條件：** 每次 retrieval 演算法改動都能比較 baseline、平均指標與失敗 query，而不是只看單一範例。

### 2. 改善 chunk/記憶內容品質與 schema validation

目前 observation 的必要欄位驗證偏少，`JsonStore.add` 只強制檢查 `id`；可以在 `make_observation` 或 store 增加 summary 非空、tags 型別、欄位版本與長度限制。

**可實作項目：**

- 增加 `schemaVersion`、memory type（convention/preference/decision）與 optional source。
- 對空白、過長、純短期指令的 summary 做拒絕或警告。
- 為 schema migration 寫測試，確保未來欄位增加不會讓舊 JSON 消失。
- 加入 `delete`、`list`、`export` CLI，讓使用者能檢查並撤回錯誤記憶。

## 第二優先：提高 retrieval 品質

### 3. 調整 BM25 tokenizer 與 ranking

目前 CJK 單字元切分不需要依賴，但長中文詞語會產生較多雜訊；英文也沒有 stemming 或 phrase matching。

**實作順序：**

1. 保留現有 tokenizer 作為 baseline。
2. 加入可選的 CJK word segmentation、英文 normalization 與 phrase boost。
3. 實作 Reciprocal Rank Fusion，與目前 raw score interpolation 比較。
4. 用 benchmark 的 per-query output 分析每個改動是否真的改善召回。

### 4. 加入 metadata filter 與可解釋結果

目前 tags 會參與搜尋，但沒有明確 filter，retrieve 也不回傳排名原因。

**可實作項目：**

- `retrieve(query, k, tags=None, session_id=None, memory_type=None)`。
- CLI 增加 `--tag` 或 `--type`。
- 回傳 score、matched terms、retriever 名稱與 rank，並在 CLI 顯示。
- injection 仍只放 summary，避免把過多 debug metadata 塞進 agent context。

### 5. 讓 hybrid 更可靠

- embedding model 載入或 encode 失敗時自動 fallback 到 BM25，並輸出可辨識的 warning。
- 修正或明確定義 hybrid 對低語意分數、無 lexical match 文件的處理規則，避免不相關結果因 cosine 分數被帶入。
- 對 model instance 做 process-level cache，並評估預先保存 embeddings 是否值得。
- 以 held-out queries 比較 MiniLM、E5、BGE 等模型，而非只依 alpha sweep 結果選型。

## 第三優先：改善 context 與 agent 行為

### 6. 使用真實 tokenizer 與更好的 injection policy

- 對接實際 Pi model 的 tokenizer，取代 `estimate_tokens` 的固定 `len / 4`。
- 對單筆超過 budget 的 summary 做截斷或摘要，而不是目前遇到第一筆超長項目就停止。
- 依 memory type、recency、relevance 做可設定的 reranking。
- 防止互相衝突的舊記憶同時注入；可採用同 topic 的最新版本或 explicit supersedes 欄位。

### 7. 加入 memory lifecycle 管理

目前記憶只會增加，沒有 retention 或過期策略。可以實作：

- `lastAccessedAt`、access count 與 recency decay。
- `archive`、`forget`、`restore` 指令。
- 專案路徑或 workspace ID 隔離，避免不同 repository 的 convention 混在一起。
- 先做 dry-run cleanup，讓使用者確認後才刪除。

## 第四優先：可靠性、安全性與效能

### 8. 從 JSON 漸進到 SQLite

目前已有最小 `MemoryStore` protocol；當資料量或並行需求增加時，先擴充成 typed、scoped、可刪除且有 contract tests 的 repository interface，再保留 JSON backend 並新增 SQLite backend。

**SQLite 版本應包含：**

- unique content/hash constraint 與 transaction。
- WAL mode 或適當 locking，處理並行讀寫。
- tags、workspace、timestamp 的 indexes。
- migration/versioning 與 backup/export。
- 若需要語意搜尋，再評估 SQLite FTS5、向量 extension 或獨立 vector store。

### 9. 強化 Pi bridge

目前 extension 使用 `spawnSync` 且沒有 timeout。可實作：

- 改用 async `spawn`，設定 timeout、最大 stdout/stderr 大小與 process cleanup。
- 對 capture/inject 錯誤加入 structured logs，但不要把敏感內容寫入 log。
- 將 hybrid failure 自動降級為 BM25。
- 若啟動成本成為瓶頸，再設計長駐 Python worker；先以 latency benchmark 證明值得引入常駐服務。

### 10. 加入隱私與 prompt-injection 防護

- capture 前對 API key、token、密碼、private key 與個資做 redaction 或提示確認。
- memory store 設定檔案權限，並評估 encryption at rest。
- 把記憶視為不可信資料，注入時加上清楚的 data-only boundary，不能讓 memory 中的文字覆寫 system/developer instruction。
- 實作 per-project isolation、使用者可見的刪除與完整 export。
- 為上述規則加入 adversarial tests。

## 建議的實作 roadmap

### Milestone 1：一週內可完成的低風險改善

1. 增加 observation schema validation 與空 summary 測試。
2. 增加 `list/delete/export` CLI 與對應 core API。
3. 加入 hybrid unavailable 時的 BM25 fallback。
4. benchmark 輸出 latency、precision 與設定資訊。
5. 用 `pytest` 和 benchmark smoke test 驗證，不改變既有 baseline 指標。

### Milestone 2：品質提升

1. 擴充 multilingual、negative 與 conflict query。
2. 實作 metadata filter、recency score 與結果解釋欄位。
3. 比較 RRF、不同 alpha 與至少兩個 embedding model。
4. 將最容易失敗的 queries 固定成 regression tests。

### Milestone 3：可長期使用

1. 擴充現有 `MemoryStore` contract 並新增 SQLite backend。
2. 將 process-global service 演進為可實例化的 `MemoryEngine`。
3. 實作 workspace isolation、retention 與 user-visible deletion。
4. 將 synchronous subprocess 改為有 timeout 的 async bridge。
5. 加入第二個 adapter、structured observability、backup/restore 與 migration 文件。

一個適合面試的未來規劃總結是：

> 我會先建立更接近真實使用的 labeled benchmark，並把 retrieval、latency、privacy 與 failure fallback 變成可量測的 regression baseline。接著處理 schema、metadata filter、recency/conflict policy 和 citation-like evidence display，讓 agent 知道記憶為何被取回。當單檔案 JSON 的併發與資料量成為實際瓶頸後，再以 repository abstraction 漸進遷移到 SQLite，最後才考慮常駐 worker 或更複雜的向量基礎設施。這樣每一步都有明確的驗收條件，也能持續新增功能而不犧牲目前的可稽核性與 graceful failure。
