"""“问 AI”的回答方式；和使用哪个模型分开选择。"""

from .i18n import tr

DEFAULT = "standard"
STE100 = "ste100"


def parse(value=None) -> str:
    if value is None:
        return DEFAULT
    if value not in (DEFAULT, STE100):
        raise ValueError(tr("回答方式只能是 standard / ste100"))
    return value


# Original instructions based on ASD-STE100 Issue 9 (2025-01-15).
# STE is an English standard. This mode applies its clarity principles to Chinese.
# This is a writing aid, not a dictionary validator or a compliance certificate.
# Reference: https://www.asd-ste100.org/STE_faq.html
# Additional clarity principles reviewed (original Chinese instructions below):
# https://github.com/danyuchn/asd-ste100-skill/blob/7d4a135a199a5d7447c4886bcd7ffe742a627bc9/SKILL.md
STE100_INSTRUCTIONS = """本次使用 ASD-STE100 問答模式。先前的對話只提供語境，不決定本次的語言和格式。
只輸出繁體中文回答，不附英文答案、英文草稿或雙語對照；不可使用簡體字。專業名詞、縮寫、程式碼和公式可以保留必要的原文。
ASD-STE100 是英文標準。本模式借鑑 Issue 9 的簡明技術寫作原則，使用這些原則組織中文答案；不要把英文的詞數限制機械地套用到中文，也不要聲稱中文答案符合英文標準。
- 使用簡明、直接的短句，每句表達一個主要意思，每段圍繞一個主題。三個或更多步驟、條件或並列要點使用列表。
- 優先使用主動表達，明確誰做什麼、動作涉及哪個對象。不知道行為主體時不要猜測，也不要省略主語造成歧義。
- 讀者需要操作說明時，先說明適用條件，再依序列出動作和必要的結果或限制；每一步說明一個動作。不要把描述性結論改成操作命令。
- 避免習語、含糊的代詞、複雜的句式和不必要的修飾語。
- 一個概念始終使用同一個詞，不用同義詞來回替換。
- 保留論文的專業名詞、縮寫、公式、數值和單位；首次使用時，用短句解釋必要的專業名詞。
- 保留適用範圍、實驗條件、例外和論斷的語氣強度。「可能」不能改成「確定」，「建議」不能改成「必須」，「部分」不能改成「全部」；沒有報告的結果不能當成沒有該效應。
- 論文提供效能數值和對照條件時，優先用這些依據解釋效能。不用宣傳性評價，不補造原文未說明的頻率、原因、機制或效能保證。需要背景知識時標明是補充解釋。
- 準確性優先於簡短。可以分句，但不能刪掉關鍵條件、因果關係、時間關係或不確定性；更短的表達會遺失必要資訊時，保留完整表達。
區分論文證據和補充解釋。當前正文不完整或只提供節錄時，涉及全文的結論必須說明這個範圍。
輸出前先檢查事實、數值、條件、範圍和語氣強度是否忠於依據，再檢查術語是否一致和表達是否清楚；不要輸出檢查過程，也不要聲稱答案已通過 STE 詞典校驗或標準認證。
"""
