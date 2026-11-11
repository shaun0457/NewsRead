"""心智圖：產生、快取和背景工作（ticket 03 從研究模組抽出來，閱讀器透過 /api/reader 使用）。

快取放在 planning_store 的 cache 表，鍵名（mindmap:*、mindmap:task:*）沿用舊的，舊的心智圖照樣讀得到。
"""
from __future__ import annotations

import json
import re
import threading
from datetime import datetime
from hashlib import sha256
from pathlib import Path

from . import config, langs, planning_store, prompts, tasks
from .i18n import tr

TASK_CACHE_PREFIX = "mindmap:task:"
_TASK_CACHE_LOCK = threading.Lock()

LANGUAGE_GUIDES = {
    "ko": {
        "name": "韓語（한국어，Korean）",  # i18n-ok: model prompt content
        "branches": [
            "`연구 배경 및 문제`：연구 동기, 해결하려는 핵심 문제 또는 기존 기술의 한계.",  # i18n-ok: model prompt content
            "`핵심 구조 및 이론`：전체 시스템/모델 아키텍처, 이론적 기초, 핵심 컴포넌트 및 모듈.",  # i18n-ok: model prompt content
            "`방법론 및 핵심 메커니즘`：알고리즘 프로세스, 주요 설계, 손실 함수 또는 수학적 표현.",  # i18n-ok: model prompt content
            "`실험 설계 및 벤치마크`：벤치마크 테스트, 평가 데이터셋, 비교 베이스라인, 평가 지표.",  # i18n-ok: model prompt content
            "`주요 발견 및 성과`：주요 실험 결론, SOTA 비교 성과, 어블레이션(Ablation) 분석 인사이트.",  # i18n-ok: model prompt content
            "`연구 기여 및 혁신`：핵심 학술적 기여, 방법론적 혁신 또는 실용적 가치.",  # i18n-ok: model prompt content
            "`한계점 및 향후 연구`：방법의 한계, 미해결 과제 또는 향후 연구 방향.",  # i18n-ok: model prompt content
        ],
        "lang_rule": (
            "1. 全文節點（包含根節點、一級分支名稱與所有子節點）一律使用韓語（한국어）生成。\n"  # i18n-ok: model prompt content
            "2. 保留標準英文學術術語與縮寫（如 Transformer, Self-Attention, BLEU, SOTA, FLOPs, Zero-shot 等），避免生硬直譯。\n"  # i18n-ok: model prompt content
            "3. 嚴格基於所提供的文字整理，嚴禁虛構未出現的數據、資料集或實驗結果。"  # i18n-ok: model prompt content
        ),
    },
    "ja": {
        "name": "日語（日本語，Japanese）",  # i18n-ok: model prompt content
        "branches": [
            "`研究背景と課題`：研究の動機、解決を目指す中心課題や既存技術のボトルネック。",  # i18n-ok: model prompt content
            "`コアアーキテクチャと理論`：システム・モデル全体の構造、理論的基礎、主要コンポーネント。",  # i18n-ok: model prompt content
            "`手法と主要メカニズム`：アルゴリズムのフロー、主要な設計、損失関数や数式表現。",  # i18n-ok: model prompt content
            "`実験設計とベンチマーク`：ベンチマーク、評価データセット、ベースライン、評価指標。",  # i18n-ok: model prompt content
            "`主要な発見と成果`：主要な実験結果、SOTA との比較、アブレーション (Ablation) 解析の洞察。",  # i18n-ok: model prompt content
            "`研究の貢献と新規性`：主要な學術的貢献、手法の新規性や実用的な価値。",  # i18n-ok: model prompt content
            "`限界と今後の課題`：手法の適用範囲・制限、未解決の課題や将来の研究方向。",  # i18n-ok: model prompt content
        ],
        "lang_rule": (
            "1. 全文節點（包含根節點、一級分支名稱與所有子節點）一律使用日語（日本語）生成。\n"  # i18n-ok: model prompt content
            "2. 保留標準英文學術術語與縮寫（如 Transformer, Self-Attention, BLEU, SOTA, FLOPs 等），避免不自然的直譯。\n"  # i18n-ok: model prompt content
            "3. 嚴格基於所提供的文字整理，嚴禁虛構未出現的數據、資料集或實驗結果。"  # i18n-ok: model prompt content
        ),
    },
    "zh": {
        "name": "中文（簡體中文）",  # i18n-ok: model prompt content
        "branches": [
            "`研究背景与问题`：研究动机、欲解决的核心问题或现有技术瓶颈。",  # i18n-ok: model prompt content
            "`核心架构与理论`：整体系统或模型架构、理论基础、核心组件模块。",  # i18n-ok: model prompt content
            "`方法与关键机制`：算法流程、关键设计、损失函数或数学表达。",  # i18n-ok: model prompt content
            "`实验设计与基准`：基准测试 (Benchmarks)、评估数据集、对照基准 (Baselines)、评估指标。",  # i18n-ok: model prompt content
            "`核心发现与成果`：主要实验结论、SOTA 对比成果、消融实验 (Ablation) 洞察。",  # i18n-ok: model prompt content
            "`研究贡献与创新`：核心学术突破、方法创新或实务价值。",  # i18n-ok: model prompt content
            "`局限性与未来方向`：方法边界、未解决问题或改进方向。",  # i18n-ok: model prompt content
        ],
        "lang_rule": (
            "1. 全文一律使用簡體中文生成，包含根節點、一級分支名稱與所有子節點。\n"  # i18n-ok: model prompt content
            "2. 保留標準英文學術術語與縮寫（如 Transformer、Self-Attention、BLEU、Zero-shot、SOTA、FLOPs 等），不進行生硬直譯。\n"  # i18n-ok: model prompt content
            "3. 嚴格基於所提供的文字整理，嚴禁虛構未出現的數據、資料集或實驗結果。"  # i18n-ok: model prompt content
        ),
    },
    "en": {
        "name": "English",
        "branches": [
            "`Research Background & Problem`：Motivation, core problem addressed, or limitations of existing methods.",  # i18n-ok: model prompt content
            "`Core Architecture & Theory`：Overall system/model architecture, theoretical foundation, key components.",  # i18n-ok: model prompt content
            "`Methodology & Mechanisms`：Algorithm workflow, key design choices, loss functions or mathematical formulations.",  # i18n-ok: model prompt content
            "`Experimental Design & Benchmarks`：Benchmark tasks, datasets, baseline comparisons, evaluation metrics.",  # i18n-ok: model prompt content
            "`Key Findings & Results`：Main empirical conclusions, SOTA comparisons, ablation study insights.",  # i18n-ok: model prompt content
            "`Contributions & Innovations`：Key academic breakthroughs, methodological innovations, or practical value.",  # i18n-ok: model prompt content
            "`Limitations & Future Work`：Scope boundaries, unaddressed challenges, or potential extensions.",  # i18n-ok: model prompt content
        ],
        "lang_rule": (
            "1. Generate all nodes (root node, top-level branch names, and all child nodes) entirely in English.\n"
            "2. Retain standard academic acronyms and terminology (e.g., Transformer, Self-Attention, BLEU, Zero-shot, SOTA, FLOPs).\n"
            "3. Strictly base content on provided text; do not hallucinate datasets or experimental numbers."
        ),
    },
    "es": {
        "name": "西班牙語（Español）",  # i18n-ok: model prompt content
        "branches": [
            "`Contexto y Problema`：Motivación de la investigación, problema central abordado o limitaciones previas.",  # i18n-ok: model prompt content
            "`Arquitectura y Teoría Central`：Estructura del sistema/modelo, fundamentos teóricos y componentes clave.",  # i18n-ok: model prompt content
            "`Metodología y Mecanismos Clave`：Flujo algorítmico, diseño metodológico, funciones de pérdida o formulaciones.",  # i18n-ok: model prompt content
            "`Diseño Experimental y Benchmarks`：Pruebas de referencia, conjuntos de datos, líneas base y métricas.",  # i18n-ok: model prompt content
            "`Hallazgos y Resultados Principales`：Conclusiones empíricas, comparaciones SOTA y análisis de ablación.",  # i18n-ok: model prompt content
            "`Contribuciones e Innovaciones`：Aportes académicos clave, innovaciones prácticas o metodológicas.",  # i18n-ok: model prompt content
            "`Limitaciones y Trabajo Futuro`：Límites del método, desafíos abiertos o direcciones futuras.",  # i18n-ok: model prompt content
        ],
        "lang_rule": (
            "1. 全文節點（包含根節點、一級分支名稱與所有子節點）一律使用西班牙語（Español）生成。\n"  # i18n-ok: model prompt content
            "2. 保留標準英文學術術語與縮寫（如 Transformer, Self-Attention, BLEU, SOTA, FLOPs 等），避免不自然的直譯。\n"  # i18n-ok: model prompt content
            "3. 嚴格基於所提供的文字整理，嚴禁虛構未出現的數據、資料集或實驗結果。"  # i18n-ok: model prompt content
        ),
    },
    "fr": {
        "name": "法語（Français）",  # i18n-ok: model prompt content
        "branches": [
            "`Contexte et Problématique`：Motivation de recherche, problème central abordé ou verrous scientifiques.",  # i18n-ok: model prompt content
            "`Architecture et Théorie Fondamentale`：Structure globale du modèle/système, fondements théoriques et modules clés.",  # i18n-ok: model prompt content
            "`Méthodologie et Mécanismes Clés`：Déroulement algorithmique, choix de conception, fonctions de perte.",  # i18n-ok: model prompt content
            "`Protocole Expérimental et Benchmarks`：Jeux de données, bancs d'essai, modèles de référence et métriques.",  # i18n-ok: model prompt content
            "`Résultats et Découvertes Clés`：Conclusions empiriques, comparaison à l'état de l'art (SOTA), études d'ablation.",  # i18n-ok: model prompt content
            "`Contributions et Innovations`：Apports scientifiques majeurs, innovations méthodologiques ou pratiques.",  # i18n-ok: model prompt content
            "`Limites et Perspectives Futures`：Limites de l'approche, questions ouvertes et axes futurs.",  # i18n-ok: model prompt content
        ],
        "lang_rule": (
            "1. 全文節點（包含根節點、一級分支名稱與所有子節點）一律使用法語（Français）生成。\n"  # i18n-ok: model prompt content
            "2. 保留標準英文學術術語與縮寫（如 Transformer, Self-Attention, BLEU, SOTA, FLOPs 等），避免生硬直譯。\n"  # i18n-ok: model prompt content
            "3. 嚴格基於所提供的文字整理，嚴禁虛構未出現的數據、資料集或實驗結果。"  # i18n-ok: model prompt content
        ),
    },
    "de": {
        "name": "德語（Deutsch）",  # i18n-ok: model prompt content
        "branches": [
            "`Forschungshintergrund & Problemstellung`：Forschungsmotivation, adressiertes Kernproblem oder bisherige Grenzen.",  # i18n-ok: model prompt content
            "`Kernarchitektur & Theoretische Grundlagen`：Gesamtsystem/Modellarchitektur, theoretische Basis, Hauptkomponenten.",  # i18n-ok: model prompt content
            "`Methodik & Schlüsselmechanismen`：Algorithmischer Ablauf, zentrale Designentscheidungen, Verlustfunktionen.",  # i18n-ok: model prompt content
            "`Experimentelles Design & Benchmarks`：Evaluations-Datensätze, Baselines, Benchmarks und Metriken.",  # i18n-ok: model prompt content
            "`Wichtigste Erkenntnisse & Ergebnisse`：Empirische Hauptergebnisse, SOTA-Vergleiche, Ablationsstudien.",  # i18n-ok: model prompt content
            "`Wissenschaftliche Beiträge & Innovationen`：Zentrale wissenschaftliche Durchbrüche und methodische Innovationen.",  # i18n-ok: model prompt content
            "`Grenzen & Zukünftige Forschungsrichtungen`：Einschränkungen der Methode, offene Fragen und zukünftige Arbeiten.",  # i18n-ok: model prompt content
        ],
        "lang_rule": (
            "1. 全文節點（包含根節點、一級分支名稱與所有子節點）一律使用德語（Deutsch）生成。\n"  # i18n-ok: model prompt content
            "2. 保留標準英文學術術語與縮寫（如 Transformer, Self-Attention, BLEU, SOTA, FLOPs 等），避免不自然的直譯。\n"  # i18n-ok: model prompt content
            "3. 嚴格基於所提供的文字整理，嚴禁虛構未出現的數據、資料集或實驗結果。"  # i18n-ok: model prompt content
        ),
    },
    "zh-TW": {
        "name": "繁體中文（臺灣學術用語）",  # i18n-ok: model prompt content
        "branches": [
            "`研究背景與問題`：研究動機、欲解決的核心問題或既有技術瓶頸。",  # i18n-ok: model prompt content
            "`核心架構與理論`：整體系統或模型架構、理論基礎、核心組件模組。",  # i18n-ok: model prompt content
            "`方法與關鍵機制`：演算法流程、關鍵設計、損失函數或數學表達。",  # i18n-ok: model prompt content
            "`實驗設計與基準`：基準測試 (Benchmarks)、評估資料集、對照基準 (Baselines)、評估指標。",  # i18n-ok: model prompt content
            "`核心發現與成果`：主要實驗結論、SOTA 對比成果、消融實驗 (Ablation) 洞察。",  # i18n-ok: model prompt content
            "`研究貢獻與創新`：核心學術突破、方法創新或實務價值。",  # i18n-ok: model prompt content
            "`局限性與未來方向`：方法邊界、未解決問題或改進方向（若原文未提及可精簡或略過）。",  # i18n-ok: model prompt content
        ],
        "lang_rule": (
            "1. 全文一律使用繁體中文（臺灣學術慣用語，如資料集、演算法、最佳化、消融實驗），包含根節點、一級分支名稱與所有子節點。\n"  # i18n-ok: model prompt content
            "2. 保留標準英文學術術語與縮寫（如 Transformer、Self-Attention、BLEU、Zero-shot、SOTA、FLOPs 等），不進行生硬直譯。\n"  # i18n-ok: model prompt content
            "3. 嚴格基於所提供的文字整理，嚴禁虛構未出現的數據、資料集或實驗結果。"  # i18n-ok: model prompt content
        ),
    },
}


def language_guide(meta: dict | None) -> tuple[str, dict]:
    target_lang = langs.of_paper(meta or {})
    guide = LANGUAGE_GUIDES.get(target_lang) or LANGUAGE_GUIDES.get("zh-TW")
    return target_lang, guide


SOURCE_BUDGET = 48000
MAX_MODEL_ID = 100  # 背景工作記下的模型名稱長度上限


def legacy_evidence_hash(paper: dict) -> str:
    evidence = []
    for block in paper.get("blocks") or []:
        if not isinstance(block, dict):
            continue
        parts = [str(block.get(k) or "").strip() for k in ("en", "zh", "text", "caption_en", "caption_zh", "alt_en", "alt_zh")]
        text = " | ".join(dict.fromkeys(x for x in parts if x))
        if text:
            evidence.append({"id": str(block.get("id") or ""), "type": block.get("type"), "page": block.get("page"), "text": text[:1800]})
    return sha256(json.dumps(evidence, ensure_ascii=False).encode()).hexdigest()


def paper_source(paper: dict) -> tuple[str, str]:
    """提取心智圖來源文字與快取 hash：原文優先、涵蓋表格與數學公式、結構化 Markdown 緊湊格式。"""
    meta = paper.get("meta") or {}
    blocks = paper.get("blocks") or []
    gl = paper.get("glossary") or []
    out = []
    used = 0
    if gl:
        gl_lines = [f"- {g['en']} = {g['zh']}" for g in gl if isinstance(g, dict) and g.get("en")]
        if gl_lines:
            gl_text = "已有術語表（專有名詞請依此對照）：\n" + "\n".join(gl_lines)  # i18n-ok: prompt
            out.append(gl_text)
            used += len(gl_text)
    for block in blocks:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "references":
            break
        if prompts._is_note(block):
            continue
        btype = block.get("type")
        page = block.get("page")
        page_tag = f"[p.{page}] " if page else ""
        if btype == "heading":
            title_text = str(block.get("en") or block.get("zh") or "").strip()
            num = str(block.get("num") or "").strip()
            t = f"\n## {page_tag}{num} {title_text}".strip()
        elif btype == "table":
            cap = str(block.get("caption_en") or block.get("caption_zh") or "").strip()
            rows = [r for r in (block.get("head") or []) + (block.get("rows") or []) if isinstance(r, list)]
            table_lines = [" | ".join(str(cell).replace("\n", " ").strip() for cell in row) for row in rows]
            tbl_body = "\n".join(table_lines)
            t = f"\n{page_tag}Table: {cap}\n{tbl_body}".strip()
        elif btype == "figure":
            cap = str(block.get("caption_en") or block.get("caption_zh") or "").strip()
            t = f"\n{page_tag}Figure: {cap}".strip()
        elif btype == "math":
            tex = str(block.get("tex") or "").strip()
            t = f"$${tex}$$" if tex else ""
        elif btype == "list":
            items = [str(it.get("en") or it.get("zh") or "").strip() for it in block.get("items", []) if isinstance(it, dict)]
            t = "\n".join(f"- {it}" for it in items if it)
        else:
            t = str(block.get("en") or block.get("zh") or block.get("text") or "").strip()
        if not t:
            continue
        if used + len(t) > SOURCE_BUDGET:
            out.append("……（後續章節依長度上限省略）")  # i18n-ok: prompt content
            break
        out.append(t)
        used += len(t)
    source_text = "\n\n".join(out).strip()
    source_hash = str(meta.get("source_sha256") or sha256(source_text.encode("utf-8")).hexdigest())
    return source_text, source_hash


def persist_task(root: Path, pid: str, request: dict, task: dict) -> None:
    cache_key = TASK_CACHE_PREFIX + pid
    with _TASK_CACHE_LOCK:
        previous, _ = planning_store.cache_get(root, cache_key)
        same_task = isinstance(previous, dict) and (previous.get("task") or {}).get("id") == task.get("id")
        clean_task = {key: value for key, value in task.items() if key != "result"}
        result = task.get("result")
        if isinstance(result, dict):
            clean_task["result"] = result
        clean_task["paper_id"] = pid
        planning_store.cache_put(root, cache_key, {
            "task": clean_task,
            "request": request,
            "paper_id": pid,
            "acknowledged": bool(previous.get("acknowledged")) if same_task else False,
        })


def current_task(root: Path, pid: str | None = None) -> dict | None:
    scope = tasks.scope_id(root)
    live_list = tasks.list_tasks(scope=scope)
    live = next((task for task in live_list
                 if task.get("kind") == "mindmap" and (not pid or task.get("paper_id") == pid or task.get("key") == pid)), None)
    target_pid = pid or (live.get("paper_id") if live else "")
    if not target_pid:
        return live
    cache_key = TASK_CACHE_PREFIX + target_pid
    saved, _ = planning_store.cache_get(root, cache_key)
    record = saved if isinstance(saved, dict) else {}
    stored = record.get("task") if isinstance(record.get("task"), dict) else None
    if live:
        same_task = bool(stored and stored.get("id") == live.get("id"))
        full_live = tasks.get(live["id"], scope=scope) or live
        result = full_live.get("result") if same_task else None
        if not isinstance(result, dict) and same_task:
            result = stored.get("result")
        return {**live, **({"result": result} if isinstance(result, dict) else {}),
                "paper_id": target_pid,
                "acknowledged": bool(record.get("acknowledged")) if same_task else False,
                "request": record.get("request") if stored and stored.get("id") == live.get("id")
                and live.get("state") in ("failed", "interrupted") else None}
    if not stored:
        return None
    if stored.get("state") in ("queued", "running", "cancelling"):
        stored = {**stored, "state": "interrupted", "phase": "interrupted",
                  "message": tr("心智圖分析已中斷；可保留輸入並手動重新產生。")}
        record = {**record, "task": stored}
        with _TASK_CACHE_LOCK:
            latest, _ = planning_store.cache_get(root, cache_key)
            latest = latest if isinstance(latest, dict) else record
            latest_task = latest.get("task") if isinstance(latest.get("task"), dict) else stored
            if latest_task.get("state") in ("queued", "running", "cancelling"):
                latest = {**latest, "task": {**latest_task, "state": "interrupted", "phase": "interrupted",
                          "message": tr("心智圖分析已中斷；可保留輸入並手動重新產生。")}}
                planning_store.cache_put(root, cache_key, latest)
            record = latest
            stored = record.get("task") if isinstance(record.get("task"), dict) else stored
    retry_request = record.get("request") if stored.get("state") in ("failed", "interrupted") else None
    return {**stored, "paper_id": target_pid, "acknowledged": bool(record.get("acknowledged")), "request": retry_request}


def _paper(app, pid: str) -> tuple[dict, dict]:
    ws = app.lib.ws(pid) if pid else None
    if not ws:
        raise ValueError(tr("找不到這篇論文。"))
    paper = ws.load("paper") or {}
    return paper, paper.get("meta") or {}


def cached(app, pid: str) -> dict:
    """讀快取的心智圖，不呼叫模型。沒有快取時 cached=False。"""
    paper, meta = _paper(app, pid)
    root = app.lib.root
    target_lang, _ = language_guide(meta)
    _, source_hash = paper_source(paper)
    found, checked = planning_store.cache_get(root, f"mindmap:{target_lang}:" + sha256(source_hash.encode()).hexdigest())
    if not found:
        found, checked = planning_store.cache_get(root, "mindmap:" + sha256(source_hash.encode()).hexdigest())
    if not found and not meta.get("source_sha256"):
        legacy_ev_hash = legacy_evidence_hash(paper)
        found, checked = planning_store.cache_get(root, f"mindmap:{target_lang}:" + sha256(legacy_ev_hash.encode()).hexdigest())
        if not found:
            found, checked = planning_store.cache_get(root, "mindmap:" + sha256(legacy_ev_hash.encode()).hexdigest())
    return {**(found or {}), "cached": bool(found), "checked_at": checked, "target": target_lang, "paper_id": pid,
            "task": current_task(root, pid)}


def submit(app, pid: str, body: dict | None = None, *, generator=None) -> dict:
    """把產生心智圖丟到背景工作。generator 預設是 generate，測試可以換掉。"""
    body = body if isinstance(body, dict) else {}
    _, meta = _paper(app, pid)
    root = app.lib.root
    title = str(meta.get("title_zh") or meta.get("title_en") or tr("未命名論文"))[:300]
    model = body.get("model")
    # 這份 request 會存進快取再回傳，只留短字串，不收任意 JSON
    request = {"model": model if isinstance(model, str) and len(model) <= MAX_MODEL_ID else None}
    make = generator or generate

    def persist(task):
        persist_task(root, pid, request, task)

    def run(cancel, report):
        report("starting", 0, 2, tr("正在整理論文文字…"))
        result = make(app, pid, body, cancel=cancel, report=report)
        report("completed", 2, 2, tr("心智圖已完成"))
        return result

    task = tasks.submit("mindmap", run, retry_failed=True, scope=tasks.scope_id(root), on_update=persist,
                        key=pid, paper_id=pid, title=title)
    return {"task": task}


def task(app, identity: str, pid: str = "") -> dict:
    """查一個心智圖工作；pid 空白時從工作本身找論文。"""
    root = app.lib.root
    found = tasks.get(identity, scope=tasks.scope_id(root))
    if found and found.get("kind") == "mindmap":
        target_pid = pid or found.get("paper_id") or found.get("key") or ""
        saved, _ = planning_store.cache_get(root, TASK_CACHE_PREFIX + target_pid) if target_pid else (None, None)
        found["acknowledged"] = (bool(saved.get("acknowledged"))
                                 if isinstance(saved, dict) and (saved.get("task") or {}).get("id") == identity else False)
        return {"task": found}
    current = current_task(root, pid or None)
    return {"task": current if current and current.get("id") == identity else None}


def cancel(app, identity: str) -> dict:
    scope = tasks.scope_id(app.lib.root)
    # 先確認是心智圖工作再取消；不然別種工作（例如智慧標註）會先被取消、才回 400
    found = tasks.get(identity, scope=scope)
    if not found or found.get("kind") != "mindmap":
        raise ValueError(tr("找不到這個心智圖分析工作。"))
    return {"task": tasks.cancel(identity, scope=scope) or found}


def acknowledge(app, identity: str, pid: str = "") -> dict:
    root = app.lib.root
    found = tasks.get(identity, scope=tasks.scope_id(root))
    if found and found.get("kind") != "mindmap":
        raise ValueError(tr("找不到這個心智圖分析工作。"))
    pid = (found.get("paper_id") if found else None) or pid
    if pid:
        cache_key = TASK_CACHE_PREFIX + pid
        with _TASK_CACHE_LOCK:
            saved, _ = planning_store.cache_get(root, cache_key)
            if isinstance(saved, dict) and (saved.get("task") or {}).get("id") == identity:
                saved["acknowledged"] = True
                planning_store.cache_put(root, cache_key, saved)
    tasks.acknowledge(identity, scope=tasks.scope_id(root))
    current = current_task(root, pid)
    return {"task": current or found}


def generate(app, pid: str, body: dict | None = None, *, cancel=None, report=None) -> dict:
    """產生（或重新產生）心智圖：一定呼叫模型，結果寫進快取。"""
    body = body if isinstance(body, dict) else {}
    paper, meta = _paper(app, pid)
    root = app.lib.root
    target_lang, guide = language_guide(meta)
    title = str(meta.get("title_zh") or meta.get("title_en") or tr("未命名論文"))[:300]
    source_text, source_hash = paper_source(paper)
    if not source_text:
        raise ValueError(tr("這篇論文目前沒有可供分析的內文。"))
    cache_key = f"mindmap:{target_lang}:" + sha256(source_hash.encode()).hexdigest()
    # POST is the explicit "產生/重新產生" action.  It must always invoke
    # the model; cache lookup belongs to the GET path above.
    from . import chat_models, engines, usage
    cfg, model = chat_models.engine_cfg(config.load(), body.get("model"))
    meter = usage.Meter(cfg.get("engine", ""))
    branch_lines = "\n".join(f"   - {b}" for b in guide["branches"])
    prompt = (
        "你是一位資深的學術架構分析專家。請根據下方提供的論文文字，為其建構一份結構清晰、資訊密度高且具備強大可讀性的「Mermaid 心智圖 (mindmap)」。\n\n"  # i18n-ok: prompt
        f"重要語言指引：此篇論文目標語言為【{guide['name']}】。心智圖的根節點、所有一級分類分支名稱、以及二級至末端節點文字，請一律使用【{guide['name']}】輸出。\n\n"  # i18n-ok: prompt
        "【架構與層級規範】\n"  # i18n-ok: prompt
        f"1. 根節點：論文核心主題或簡化標題（使用目標語言），語法如 `  root((論文標題))`。\n"  # i18n-ok: prompt
        f"2. 主要分支（一級分支，請使用目標語言表達，依學術邏輯組織 5 至 7 個核心維度）：\n"  # i18n-ok: prompt
        f"{branch_lines}\n"
        "3. 層級深度：建議展開至 3 至 4 層；主要分支下設 2 至 4 個子分支（二級節點），末端節點（三級/四級節點）列出具體變數、數據指標、方法細節。\n\n"  # i18n-ok: prompt
        "【節點內容與視覺渲染強化】\n"  # i18n-ok: prompt
        "1. 精煉原則：節點文字必須精簡有力（建議控制在 6 至 20 個字），使用名詞短語或精要摘要，嚴禁整段複製長句。\n"  # i18n-ok: prompt
        r"2. KaTeX 數學公式：遇到數學變數、維度、複雜度或重要公式時，自然運用行內 KaTeX 格式（如 $O(N^2)$、$d=512$、$\mathcal{L}_{\text{task}}$、$\alpha=0.5$）。" "\n"  # i18n-ok: prompt
        "3. 基礎 Markdown 語法：\n"  # i18n-ok: prompt
        "   - 專有名詞、模組名稱、演算法或程式碼變數，適當使用行內代碼（如 `ResNet-50`、`CrossAttention`、`AdamW`）。\n"  # i18n-ok: prompt
        "   - 關鍵突破、重要量化成果或核心結論，適當使用粗體突顯（如 `提升 **+3.4%**`、`達到 **92.1%**`、`減少 **40%** 延遲`）。\n"  # i18n-ok: prompt
        "4. 自然融入：以上格式化元素請自然融入學術脈絡中，切勿在每個節點硬性堆砌特殊符號，保持整體視覺清爽乾淨。\n\n"  # i18n-ok: prompt
        "【語言與真實性規範】\n"  # i18n-ok: prompt
        f"{guide['lang_rule']}\n\n"  # i18n-ok: prompt
        "【Mermaid 語法與輸出格式嚴格要求】\n"  # i18n-ok: prompt
        "1. 第 1 行必須為 `mindmap`。\n"  # i18n-ok: prompt
        "2. 根節點緊接其後，縮排 2 個空格。\n"  # i18n-ok: prompt
        "3. 層級縮排：每一層級嚴格固定縮排 2 個空格（第一層 2 空格、第二層 4 空格、第三層 6 空格、第四層 8 空格），嚴禁使用 Tab。\n"  # i18n-ok: prompt
        '4. 標點安全：若節點文字中包含圓括號 ()、方括號 [] 或冒號等符號，請以雙引號與方括號包裹（例如 `    ["Cross-Entropy (CE) 損失"]`），防止 Mermaid 語法樹解析中斷。\n'  # i18n-ok: prompt
        "5. 絕對限制：只輸出 Mermaid 程式碼本身！不要包含 Markdown 程式碼區塊標記（不要輸出 ```mermaid 或 ```），不要包含任何引言、前言、解釋或結尾問候語。\n\n"  # i18n-ok: prompt
        f"論文標題：{title}\n"  # i18n-ok: prompt
        f"目標語言：{guide['name']}\n"  # i18n-ok: prompt
        f"來源文字（論文結構化原文與實驗數據）：\n{source_text}"  # i18n-ok: prompt
    )
    if cancel and cancel.is_set():
        return {}
    if report:
        report("generating", 1, 2, tr("正在依據論文內文產生心智圖…"))
    answer = engines.run(engines.for_translation(cfg), prompt, app.lib.root, [], cancel, meter).strip()
    bt = chr(96) * 3
    match = re.search(r"(?is)\b(mindmap\b.*?)(?:\n\s*" + bt + r"|$)", answer)
    if match:
        answer = match.group(1).strip()
    answer = re.sub(r"^```(?:mermaid)?\s*", "", answer, flags=re.I)
    answer = re.sub(r"\s*```.*$", "", answer, flags=re.I | re.S).strip()
    if not answer.lower().startswith("mindmap") or len(answer) > 20000 or re.search(r"<\s*/?\s*(?:script|iframe|foreignObject)|javascript:", answer, re.I):
        raise ValueError(tr("模型未回傳安全且可辨識的 Mermaid mindmap，請重試。"))
    result = {"mermaid": answer, "title": title, "target": target_lang, "source_sha256": source_hash, "model": model.get("name", model.get("id", "")), "usage": meter.snapshot(), "generated_at": datetime.now().astimezone().isoformat(), "cached": False, "paper_id": pid}
    planning_store.cache_put(root, cache_key, result)
    planning_store.cache_put(root, "mindmap:" + sha256(source_hash.encode()).hexdigest(), result)
    return result
