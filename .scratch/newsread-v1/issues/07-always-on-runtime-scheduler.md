# 07: 常駐與排程器

**What to build:** 讓 NewsRead 在關掉頁面後仍常駐，並提供所有定時工作共用的排程器。

**Blocked by:** 04（移除研究工作區、文獻搜尋、Zotero 與批次匯入）

**Status:** done

- [x] 關掉所有頁面之後，server 仍然在跑（測試）；安裝版的視窗和系統匣在 66
- [x] 同時啟動第二個時會被擋下，並提示已經有一個在跑（測試）
- [x] 可以設定 Windows 開機自動啟動
- [x] 停止時，排程和背景執行緒在時限內結束（測試）
- [x] 共用排程器：每個工作記錄上次成功的時間；啟動後補做錯過的部分，不重複執行（用假時鐘測試）
- [x] 時鐘可以替換，供測試使用

## 做法（實作紀錄）

- 常駐：`start.cmd` / `start.sh` 不再帶 `--exit-on-close`；這個選項還在，要的人自己加。新增 `easyread stop`（呼叫 `/api/shutdown`，還有工作沒做完時會拒絕）。
- 單一執行個體：`easyread/instance.py`，資料目錄裡的 `.server.lock` 用作業系統檔案鎖（Windows `msvcrt.locking`、其他 `flock`），鎖住服務整個生命週期；程序當掉時系統會放開，鎖檔不刪。暫用文獻庫（`EASYREAD_LIBRARY`）不佔鎖。第二個 `easyread serve` 會印出已在跑的位址並以代碼 3 結束，不建 App、不綁 port。
- 開機自動啟動：`easyread/autostart.py`，寫 `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` 的 `NewsRead`，指令是 `pythonw -c "...main(['serve'])"`（自己把套件目錄放進 sys.path，因為登入時的工作目錄不固定）；打包的後端是 `"exe" serve`。CLI：`easyread autostart on|off|status`。設定頁的開關和安裝版（Electron 的開機項目）在 66。
- 排程器：`easyread/scheduler.py`，狀態存在資料目錄的 `schedule.json`。錯過幾個週期都只補做一次；記錄的成功時間用開始時間；失敗不記成功，至少隔 `RETRY_AFTER`（300 秒，或間隔更短時照間隔）再試；同一工作同時只跑一份；記錄的時間比現在晚超過一個間隔視為時鐘錯誤，重新跑。目前還沒有登記任何工作，之後的 RSS、財報、簡報各自 `app.scheduler.add(...)`。
- 停止：`launch._stop` 依序停排程（最多 `STOP_TIMEOUT` 5 秒）、presence 監看（2 秒）、文獻庫標記（2 秒）；啟動到一半失敗也走同一段。卡住的工作是 daemon 執行緒，不擋程序結束。

## 延後

- 跑很久的工作只能自己看 `scheduler.stopping` 提早收工，排程器不會強制中斷。
- 停止逾時後卡住的工作若之後才跑完，仍會寫一次 `schedule.json`；正常使用時 serve 結束後程序就結束，不會發生。
- 常駐讓本機服務開著的時間變長：同一台電腦上的其他帳號可以從 `/api/library` 拿到 token（原本就是這樣，只是以前關頁就停）。README 已註明只在自己的電腦上用；要擋的話是另一張（token 改存 0600 檔案、只給 CLI 讀）。
- Windows 上程序被強制結束後，系統放開檔案鎖可能有一點延遲；Electron 立刻重開後端時偶爾會被擋成代碼 3，留給 66 決定要不要短暫重試。
- Electron 後端是 `serve --port 0`：已經有 start.cmd 的服務在跑時會被鎖擋下、顯示後端退出。改成接手已在跑的服務在 66。
