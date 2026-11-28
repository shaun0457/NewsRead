"""因果鏈清單（ticket 59）：在題材頁的版本上新增、修改、確認、移除環節，並建議領漲 / 補漲。

資料模型在 narratives.py（ChainLink 存在題材頁版本的 body.chain）。這裡只做「改一環」：
每次修改都從目前的版本（草稿比定稿新就用草稿）複製一份、改掉一環，寫成新的草稿；定稿只在 publish 時寫，
而且沿用 narratives 的規則：沒有出處的環節（AI 推論）要我確認過才進得了定稿。
"""
from __future__ import annotations

import copy
import statistics
import time

from . import narratives
from .log import log
from .entities import EntityError
from .i18n import tr

PREFIX = "/api/themes"
OPS = ("add", "update", "confirm", "remove", "role", "publish")
LINK_KEYS = ("from", "to", "relation", "source", "revenue_share", "role")  # 我能填的欄位；confirmed 只能走 confirm
ROLES = ("leader", "laggard", "unknown")
OTHER_FIELDS = ("one_liner", "analogy", "origin", "second_order", "stage")  # 因果鏈以外的欄位
MAX_LINKS = narratives.MAX_LINKS
MARKET_BUDGET = 3.0  # 一次畫面最多花幾秒查行情；超過的公司當成沒資料（unknown）


def _bad(field: str, message: str | None = None):
    return EntityError(message or tr("資料格式不對。"), field)


def handles(path: str) -> bool:
    parts = [p for p in path.split("/") if p]
    return len(parts) == 4 and path.startswith(PREFIX + "/") and parts[3] == "chain"


def _head(page: dict) -> dict | None:
    """目前的版本：草稿（一定比定稿新）優先，沒有草稿就是定稿。"""
    return page["draft"] or page["final"]


def _names(db, ids: set) -> dict:
    out = {}
    for i in sorted(ids)[:MAX_LINKS * 2]:
        row = db.execute("SELECT name, type FROM entities WHERE id=?", (i,)).fetchone()
        out[i] = {"name": row["name"], "type": row["type"]} if row else None
    return out


def suggest_roles(returns: dict) -> dict:
    """{公司 id: 題材起點以來的報酬或 None} → {公司 id: leader | laggard | unknown}。

    有資料的公司至少 2 家才建議：報酬不低於這些公司的中位數 = 領漲，低於 = 補漲。沒資料的一律 unknown。"""
    known = {k: v for k, v in returns.items() if isinstance(v, (int, float)) and not isinstance(v, bool) and v == v}
    if len(known) < 2:
        return {k: "unknown" for k in returns}
    mid = statistics.median(known.values())
    return {k: ("unknown" if k not in known else "leader" if known[k] >= mid else "laggard") for k in returns}


def _returns(app, store, theme_id: str, ids: list, clock=time.monotonic) -> dict:
    """向行情取題材起點以來的報酬。行情還沒做（ticket 30）或取不到就是 None。
    總時間超過 MARKET_BUDGET 就不再查，剩下的都是 None（行情來源要自己限制單次呼叫的時間）。"""
    provider = getattr(app, "market_returns", None)
    if not callable(provider) or not ids:
        return {i: None for i in ids}
    with store.index.read() as db:
        row = db.execute("SELECT min(created_at) AS t FROM theme_versions WHERE theme_id=?", (theme_id,)).fetchone()
    since = row["t"] if row else None
    out = {}
    deadline = clock() + MARKET_BUDGET
    for i in ids[:MAX_LINKS]:
        if clock() >= deadline:
            out[i] = None
            continue
        try:
            value = provider(i, since) if since else None
        except Exception as e:  # noqa: BLE001 只記類型：行情來源的例外文字不進 log
            log.warning("行情讀取失敗 %s", type(e).__name__)
            value = None
        out[i] = value
    return out


def view(app, store: narratives.Store, theme_id: str) -> dict:
    page = store.page(theme_id)
    head = _head(page)
    chain = (head["body"].get("chain") or []) if head else []
    prov = narratives.provenance_of(head)
    entity_ids = {n["entity_id"] for link in chain for n in (link["from"], link["to"]) if "entity_id" in n}
    companies = sorted({link["to"]["entity_id"] for link in chain if "revenue_share" in link})
    with store.index.read() as db:
        names = _names(db, entity_ids)
    suggestions = suggest_roles(_returns(app, store, theme_id, companies)) if companies else {}
    links = []
    for i, link in enumerate(chain):
        out = dict(link, index=i, provenance=prov["chain"][i])
        for side in ("from", "to"):
            node = link[side]
            out[side] = dict(node, **({"name": names[node["entity_id"]]["name"], "type": names[node["entity_id"]]["type"]}
                                      if node.get("entity_id") and names.get(node["entity_id"]) else {}))
        if "revenue_share" in link:
            out["role_suggestion"] = suggestions.get(link["to"]["entity_id"], "unknown")
        links.append(out)
    return {"theme_id": theme_id, "status": head["status"] if head else None, "version": head["version"] if head else 0,
            "final_version": page["final"]["version"] if page["final"] else None, "links": links,
            "unconfirmed": sum(1 for x in chain if x.get("inferred") and not x.get("confirmed")),
            # 這頁沒顯示的欄位：定稿前的預覽要列出來（ticket 106）
            "fields": {k: (head["body"].get(k) if head else None) for k in OTHER_FIELDS},
            "provenance": {k: prov[k] for k in OTHER_FIELDS},
            "market_data": callable(getattr(app, "market_returns", None))}


def edit(app, store: narratives.Store, theme_id: str, body) -> dict:
    """改一環。body：{op, base_version, index?, link?}。base_version 要等於目前版本，免得蓋掉別處的修改。"""
    if not isinstance(body, dict):
        raise _bad("body")
    op = body.get("op")
    if op not in OPS:
        raise _bad("op")
    page = store.page(theme_id)
    head = _head(page)
    version = head["version"] if head else 0
    base = body.get("base_version")
    if isinstance(base, bool) or base != version:
        raise _bad("base_version", tr("這一頁已經有新的版本，請重新整理再改。"))
    theme = copy.deepcopy(head["body"]) if head else {}
    theme.pop("provenance", None)
    prov = narratives.provenance_of(head)  # 只改這一環的來源；其他欄位照舊是誰寫的就是誰寫的（ticket 106）
    chain = theme.get("chain") or []
    if op == "publish":
        if not head or head["status"] != "draft":
            raise _bad("op", tr("沒有可以確認成定稿的草稿。"))
        # 定稿前畫面已經預覽過所有欄位：AI 寫的標成看過，但還是 AI 寫的
        reviewed = {k: narratives.mark(prov[k]["by"], True) for k in narratives.PROVENANCE_FIELDS}
        reviewed.update({k: [narratives.mark(e["by"], True) for e in prov[k]] for k in narratives.PROVENANCE_LISTS})
        store.add_theme_version(theme_id, "final", theme, expected_version=version, provenance=reviewed)
        return view(app, store, theme_id)
    index = body.get("index")
    if op != "add":
        if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < len(chain):
            raise _bad("index")
    if op in ("add", "update"):
        link = body.get("link")
        if not isinstance(link, dict):
            raise _bad("link")
        clean = {k: link[k] for k in LINK_KEYS if k in link}
        if op == "add":
            if len(chain) >= MAX_LINKS:
                raise _bad("link", tr("因果鏈最多 {n} 環。", n=MAX_LINKS))
            chain.append(clean)
            prov["chain"].append(narratives.mark(narratives.ME))
        else:
            chain[index] = clean  # 改過的環節要重新確認：confirmed 不帶過去
            prov["chain"][index] = narratives.mark(narratives.ME)
    elif op == "confirm":
        if not chain[index].get("inferred") or chain[index].get("confirmed"):
            raise _bad("index", tr("這一環有出處，或已經確認過了。"))
        chain[index] = dict(chain[index], confirmed=True)
    elif op == "role":  # 只換領漲 / 補漲（例如採用建議）：其他內容沒變，確認過的不用重新確認
        role = body.get("role")
        if role not in ROLES:
            raise _bad("role")
        if "revenue_share" not in chain[index]:
            raise _bad("index", tr("營收占比和領漲 / 補漲只在連到公司時填。"))
        chain[index] = dict(chain[index], role=role)
    else:
        del chain[index]
        del prov["chain"][index]
    theme["chain"] = chain
    store.add_theme_version(theme_id, "draft", theme, expected_version=version, provenance=prov)
    return view(app, store, theme_id)


def _theme_id(path: str) -> str:
    return [p for p in path.split("/") if p][2]  # 跟 handles 同一套拆法


def api_get(app, path: str, query: dict) -> dict | None:
    if not handles(path):
        return None
    store = narratives._store(app, create=False)
    if store is None:
        raise narratives.NotFound(path)
    return view(app, store, _theme_id(path))


def api_post(app, path: str, body) -> dict | None:
    if not handles(path):
        return None
    return edit(app, narratives._store(app, create=True), _theme_id(path), body)


__all__ = ["handles", "api_get", "api_post", "view", "edit", "suggest_roles"]
