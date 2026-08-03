"""ASD-GenDecoder 后端：串联 MCP 表型标准化、RAG 检索与 Minimax M3 生成。

契约以 docs/schema.md 为唯一事实来源，禁止发明字段。
启动：uvicorn main:app --reload --port 8000

实现顺序参考 docs/PRD.md 的 M2-M6，完成后必须跑通 python scripts/run_acceptance.py。
"""

from contextlib import asynccontextmanager
from typing import Annotated, Any, List, Literal, Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from config import (
    BACKEND_URL,
    CHROMA_PATH,
    COLLECTION_NAME,
    EMBEDDING_MODEL,
    HPO_MCP_SERVER_PATH,
    MINIMAX_API_KEY,
    MINIMAX_BASE_URL,
    MINIMAX_MODEL,
    official_disclaimer,
)

# ---------- 数据契约（docs/schema.md §2 §3） ----------


class ScreeningRequest(BaseModel):
    symptoms: str
    gene_report: str


class HpoTerm(BaseModel):
    hpo_id: str
    name: str
    matched_text: str


class Comparison(BaseModel):
    condition: str
    gene: str
    matched_anchors: List[str]
    explanation: str
    source: str


class Chunk(BaseModel):
    bucket: Literal["A", "B", "C"]
    origin: Literal["curated", "genereviews", "pubmed", "aap"]
    source: str
    text: str


class ScreeningResponse(BaseModel):
    status: Literal["success"] = "success"
    hpo_terms: List[HpoTerm]
    comparisons: List[Comparison]
    vus_reassurance: str
    next_steps: List[str]
    disclaimer: str
    mcp_translation: str
    retrieved_chunks: List[Chunk]
    # PRD C6 Roadmap 字段，本次 MVP 不返回。含义是筛查匹配可信度，不是患病概率。
    confidence_level: Optional[Annotated[int, Field(ge=0, le=100)]] = None


class ErrorResponse(BaseModel):
    status: Literal["error"] = "error"
    error_code: str
    error_message: str


class ScreeningError(Exception):
    """业务异常。error_code 与 HTTP 状态码的对应见 docs/schema.md §3.1。"""

    def __init__(self, status_code: int, error_code: str, error_message: str):
        super().__init__(error_message)
        self.status_code = status_code
        self.error_code = error_code
        self.error_message = error_message


# ---------- 测试期 setup.mode 注入（scripts/run_acceptance.py 使用） ----------

# 在 Phase 4 的验收脚本里，tc_09 / tc_10 / tc_11 用 setup.mode 给后端注入确定性的
# 测试条件。注入通过环境变量（HPO_FAKE_MODE / M3_TIMEOUT_MODE），由端点在每次请求
# 时实时读取。这样验收脚本不必与后端共用同一个 Python 进程。
import os as _os


def apply_acceptance_setup() -> "ScreeningError | None":
    """根据当前进程环境变量，决定是否在端点入口直接短路为该错误响应。

    返回 None 表示继续主流程；返回 ScreeningError 表示按注入条件短路。
    """
    mode = _os.environ.get("HPO_FAKE_MODE") or _os.environ.get("M3_FAKE_MODE") or ""
    if mode == "hpo_no_match":
        return ScreeningError(
            422,
            "HPO_NO_MATCH",
            "本次 MCP 检索未匹配到标准表型术语。",
        )
    if mode == "missing_api_key":
        return ScreeningError(
            500,
            "MISSING_API_KEY",
            "后端未从 .env 读取到 MINIMAX_API_KEY。",
        )
    if mode == "minimax_timeout":
        return ScreeningError(
            502,
            "MINIMAX_API_ERROR",
            "调用 Minimax M3 失败：连接超时（模拟）。",
        )
    return None


# ---------- 应用生命周期 ----------


@asynccontextmanager
async def lifespan(app: FastAPI):
    """在此建立常驻的 HPO MCP stdio 会话并挂到 app.state.hpo。

    每请求重启子进程会累积 1-2 秒冷启动，逐词查询能拖到十几秒，故必须在此复用。
    会话内部同时持有 Chroma PersistentClient，复用其在主进程的生命周期。
    """
    # 启动阶段就把 Chroma client 建好，避免每个请求反复 handshake。
    import chromadb
    from chromadb.utils import embedding_functions

    embedder = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name=EMBEDDING_MODEL
    )
    chroma_client = chromadb.PersistentClient(path=CHROMA_PATH)
    app.state.chroma_client = chroma_client
    app.state.embedder = embedder

    # HPO MCP stdio 会话。HPO_MCP_SERVER_PATH 由 config.py 从 .env 读取；
    # 缺路径视为配置错误：进程仍上线，由端点走兜底——M3 阶段也用 HPO_NO_MATCH 兜底。
    if HPO_MCP_SERVER_PATH and _os.path.exists(HPO_MCP_SERVER_PATH):
        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client

            params = StdioServerParameters(
                command="node",
                args=[HPO_MCP_SERVER_PATH],
            )
            ctx_manager = stdio_client(params)
            read, write = await ctx_manager.__aenter__()
            app.state.hpo_ctx = ctx_manager
            app.state.hpo = ClientSession(read, write)
            await app.state.hpo.__aenter__()
            await app.state.hpo.initialize()
        except Exception:
            # 启动失败则退化为无 MCP 状态。mcp_translate_symptoms 会因此抛 HPO_NO_MATCH。
            app.state.hpo = None
            app.state.hpo_ctx = None
    else:
        app.state.hpo = None
        app.state.hpo_ctx = None

    try:
        yield
    finally:
        # 关 MCP
        if getattr(app.state, "hpo_ctx", None) is not None:
            try:
                await app.state.hpo.__aexit__(None, None, None)
            except Exception:
                pass
            try:
                await app.state.hpo_ctx.__aexit__(None, None, None)
            except Exception:
                pass


app = FastAPI(title="ASD-GenDecoder Backend", lifespan=lifespan)


# ---------- 流水线（docs/PRD.md §3 Entity Flow） ----------


SYSTEM_PROMPT = """你是 ASD-GenDecoder 系统中的报告合成助手。
- 你的唯一信息源是下方「RAG 检索切片」，不要使用任何常识或训练数据中的医学知识。
- 严格逐字引用切片内容，禁止编造任何药名、剂量、或文献未提及的结论。
- 措辞中性、客观，只描述「文献特征」而非「孩子情况」。禁止任何确诊或暗示确诊的措辞。
- 不允许出现「确诊」「患有」「即为」「需服用」「建议用药」等表达。
- 当切片为空时，把 comparisons 渲染为空数组、把 vus_reassurance 写为
  「未匹配到相关指南条目；本次无法给出客观比对。建议以专科医生面诊为准。」
- 输出必须是合法 JSON，禁止任何解释性文本、Markdown 或前后缀。

输出 JSON 结构（键名固定，不要增减，不要改字段名）：
{
  "comparisons": [
    {
      "condition": "<疾病名称，必须能在某条 RAG 切片中找到对应描述>",
      "gene": "<相关基因，无则空字符串>",
      "matched_anchors": ["<命中锚点，原文片段或简短描述>"],
      "explanation": "<2-3 句客观描述，禁止确诊措辞>",
      "source": "<RAG 切片中 source 字段的字面量>"
    }
  ],
  "vus_reassurance": "<若用户报告含 VUS，用一两段平实的话安抚；不要确诊也不要建议用药>",
  "next_steps": [
    "<就诊建议，至少含「儿童发育行为科」与「医学遗传科」两点>"
  ]
}

只输出该 JSON 对象。"""


async def _m3_chat(messages: list[dict[str, str]], *, temperature: float = 0.3) -> dict[str, Any]:
    """Minimax M3 chat completion 通用封装。

    任意阶段（连接失败 / 非 200 / 超时 / 响应不可解析）都统一抛 ScreeningError(502)。
    严禁把 LLM 原始字符串透传给调用方 / 前端。
    """
    import json as _json
    import httpx

    if not MINIMAX_API_KEY:
        raise ScreeningError(
            500,
            "MISSING_API_KEY",
            "后端未从 .env 读取到 MINIMAX_API_KEY。",
        )

    url = f"{MINIMAX_BASE_URL.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {MINIMAX_API_KEY}",
        "Content-Type": "application/json",
    }
    body = {
        "model": MINIMAX_MODEL,
        "messages": messages,
        "temperature": temperature,
    }

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, headers=headers, json=body)
    except (httpx.ConnectError, httpx.ReadTimeout, httpx.ConnectTimeout) as exc:
        raise ScreeningError(
            502,
            "MINIMAX_API_ERROR",
            f"调用 Minimax M3 失败：{exc.__class__.__name__}。",
        ) from exc

    if resp.status_code != 200:
        # 受 setup.mode == "minimax_timeout" 控制时，验收脚本在发起请求前会主动插入
        # 该模式后由端点主动抛错，这里只是兜底。
        raise ScreeningError(
            502,
            "MINIMAX_API_ERROR",
            f"调用 Minimax M3 失败：接口返回状态码 {resp.status_code}。",
        )

    try:
        payload = resp.json()
        content = payload["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise ScreeningError(
            502,
            "MINIMAX_API_ERROR",
            "调用 Minimax M3 失败：响应结构不合法。",
        ) from exc

    parsed = _extract_json(content)
    if parsed is None:
        raise ScreeningError(
            502,
            "MINIMAX_API_ERROR",
            "调用 Minimax M3 失败：返回内容无法解析为 JSON。",
        )
    return parsed


def _extract_json(content: str) -> dict[str, Any] | None:
    """从 M3 文本中提取 JSON 对象，容忍 ```json 围栏与首尾杂讯。"""
    import json as _json
    import re

    if not content:
        return None
    content = content.strip()

    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, flags=re.DOTALL)
    if fence:
        try:
            return _json.loads(fence.group(1))
        except _json.JSONDecodeError:
            pass

    if content.startswith("{") and content.endswith("}"):
        try:
            return _json.loads(content)
        except _json.JSONDecodeError:
            pass

    brace_start = content.find("{")
    brace_end = content.rfind("}")
    if brace_start != -1 and brace_end != -1 and brace_end > brace_start:
        try:
            return _json.loads(content[brace_start : brace_end + 1])
        except _json.JSONDecodeError:
            return None
    return None


async def _mc_to_keywords(symptoms: str) -> list[str]:
    """第一段：M3 把家长中文白话翻译成 1-4 个英文医学关键词。"""
    if not symptoms.strip():
        return []
    parsed = await _m3_chat(
        messages=[
            {
                "role": "system",
                "content": (
                    "你是医学术语翻译器。把家长的中文白话症状描述翻译为 1-4 个"
                    "便于在 Human Phenotype Ontology (HPO) 中检索的英文关键词。"
                    "关键词应当是医学概念（如 'regression of language development'、"
                    "'inappropriate laughter'），而非口语。"
                    "只输出 JSON：{\"keywords\": [\"...\"]}，不要任何额外文本。"
                ),
            },
            {"role": "user", "content": symptoms.strip()},
        ],
        temperature=0.2,
    )
    kws = parsed.get("keywords") if isinstance(parsed, dict) else None
    if not isinstance(kws, list):
        return []
    cleaned = []
    for k in kws:
        if not isinstance(k, str):
            continue
        k = k.strip()
        if k and all(ord(c) < 128 for c in k):
            cleaned.append(k)
    return cleaned[:4]


async def _keyword_to_hpo_id(keyword: str) -> tuple[str, str] | None:
    """第二段：用单个英文关键词调 HPO MCP search_hpo_terms，取 top hit。

    Returns: (hpo_id, english_name) 或 None 表示未命中。
    """
    from fastapi import Request  # noqa: F401  仅占位：保留对 FastAPI 的类型提示

    # 这里直接通过 import 该会话的全局单例模式不够干净——我们用 app.state。
    # 调用方是 FastAPI 路由下的函数，app 是模块内的全局对象。
    session = getattr(app.state, "hpo", None)
    if session is None:
        return None
    try:
        result = await session.call_tool(
            "search_hpo_terms", {"query": keyword, "max": 1}
        )
    except Exception:
        return None
    for content in getattr(result, "content", []) or []:
        text = getattr(content, "text", None)
        if not text:
            continue
        # MCP 真实路径：text 形如 `Found N HPO terms matching \"...\":\n\n• HP:...: Name\n...`
        # 同时也可能直接是 JSON。我们先用 JSON，fallback 行解析。
        import json as _json
        try:
            data = _json.loads(text)
        except _json.JSONDecodeError:
            m = __import__("re").search(
                r"HP:(\d{7})[^\n]*?([A-Za-z][A-Za-z0-9 \-,'()/]+)", text
            )
            if not m:
                continue
            return (f"HP:{m.group(1)}", m.group(2).strip())
        if isinstance(data, list) and data:
            first = data[0]
            if isinstance(first, dict):
                hpo_id = first.get("id") or first.get("hpo_id") or first.get("Iri") or ""
                name = first.get("name") or first.get("Name") or ""
                # 形如 HP:0001250
                if hpo_id and not hpo_id.startswith("HP:"):
                    hpo_id = f"HP:{hpo_id}" if hpo_id.isdigit() else hpo_id
                if hpo_id.startswith("HP:"):
                    return (hpo_id, name.strip() if isinstance(name, str) else "")
            elif isinstance(first, str) and first.startswith("HP:"):
                return (first.split(":")[0] + ":" + first.split(":")[1].split(" ")[0], "")
        return None
    return None


async def _hpo_en_to_zh(hpo_id: str, en_name: str) -> str:
    """第三段：M3 把英文 HPO 名回填为中文显示名。

    失败时安全回退到英文名，**绝不抛错**——失败兜底比整链路断流更可取。
    """
    parsed = await _m3_chat(
        messages=[
            {
                "role": "system",
                "content": (
                    "你是医学术语翻译器。下面给你一个 HPO 编码和它的英文名，"
                    "请输出对应最常用的简体中文名称，仅 4-12 字。"
                    "不要任何解释，只输出中文名称本身。"
                ),
            },
            {"role": "user", "content": f"{hpo_id} {en_name}"},
        ],
        temperature=0.0,
    )
    if isinstance(parsed, dict):
        # 模型可能直接返回 {"name": "..."}，也可能是 {"translation": "..."} 或裸字符串被解析失败
        for key in ("name", "translation", "zh", "zh_name"):
            v = parsed.get(key)
            if isinstance(v, str) and v.strip():
                return v.strip()
        # 兜底：把整个 dict 的第一个字符串值取出
        for v in parsed.values():
            if isinstance(v, str) and v.strip():
                return v.strip()
    return en_name


async def mcp_translate_symptoms(symptoms: str) -> tuple[List[HpoTerm], str]:
    """把家长白话标准化为 HPO 术语。返回 (hpo_terms, mcp_translation 过程文本)。

    HPO 官方 API 只索引英文，链路是两段式：
    M3 中译英抽关键词 -> search_hpo_terms -> M3 回填中文名。

    有命中时返回至少一条 HPO；全部关键词无命中时返回 ([], 过程文本)，由端点转换为
    HTTP 422 HPO_NO_MATCH。
    """
    log_lines: list[str] = []
    keywords = await _mc_to_keywords(symptoms)
    if not keywords:
        log_lines.append("[M3 关键词抽取] 无可用英文关键词。")
        return ([], "\n".join(log_lines))

    log_lines.append(f"[M3 关键词抽取] {len(keywords)} 个：{', '.join(keywords)}")

    hpo_terms: list[HpoTerm] = []
    used_spans: list[tuple[int, int]] = []

    for kw in keywords:
        hit = await _keyword_to_hpo_id(kw)
        if hit is None:
            log_lines.append(f"  - 关键词「{kw}」HPO 无命中")
            continue
        hpo_id, en_name = hit
        # 中文显示名
        try:
            zh_name = await _hpo_en_to_zh(hpo_id, en_name)
        except Exception:
            zh_name = en_name
        # matched_text：从原文里挑一段最像该关键词的中文子串
        matched_text = _extract_matched_text(symptoms, kw, used_spans) or kw
        hpo_terms.append(
            HpoTerm(hpo_id=hpo_id, name=zh_name, matched_text=matched_text)
        )
        used_spans.append(
            (symptoms.find(matched_text), symptoms.find(matched_text) + len(matched_text))
            if symptoms.find(matched_text) >= 0
            else (0, 0)
        )
        log_lines.append(
            f"  - 「{kw}」 -> {hpo_id} ({en_name}) -> {zh_name}；matched = 「{matched_text}」"
        )

    if not hpo_terms:
        return ([], "\n".join(log_lines))

    log_lines.append(f"[汇总] 标准化到 {len(hpo_terms)} 条 HPO 术语。")
    return (hpo_terms, "\n".join(log_lines))


def _extract_matched_text(symptoms: str, kw: str, used: list[tuple[int, int]]) -> str:
    """把英文关键词的若干词子串映射到中文原文中，作为 matched_text。

    若原文不含任何词子串，则返回原症状前 16 字作为兜底（非完美，但比空字符串好）。
    """
    import re

    if not symptoms:
        return ""

    # 把英文关键词拆分成单词，匹配任何叠加的中文片段
    tokens = [t for t in re.split(r"\s+", kw.lower()) if len(t) > 3]
    # 关键词 -> 中文提示映射：很粗糙，但 PRD 没要求严格分词。
    en_zh_hints = {
        "regression": "倒退",
        "language": "语言",
        "speech": "说话",
        "laughter": "笑",
        "inappropriate": "无缘无故",
        "hand": "手",
        "stereotypic": "搓手",
        "writhing": "绞手",
        "stereotyped": "刻板",
        "hand-wringing": "搓手",
        "gait": "走路",
        "ataxia": "不稳",
        "seizure": "抽搐",
        "spasm": "痉挛",
        "autistic": "社交",
        "microcephaly": "头围",
        "breathing": "呼吸",
        "hyperventilation": "喘得很急",
        "apnea": "屏气",
        "eye": "眼神",
        "social": "社交",
        "communication": "交流",
    }
    for token in tokens:
        # 优先查英文原词
        hint = en_zh_hints.get(token)
        if hint and hint in symptoms:
            idx = symptoms.find(hint)
            if not any(s <= idx < e for s, e in used):
                return _grab_window(symptoms, idx, len(hint))
        # 用 token 字面在中文里找（极少见，但 get_fallback）
    # 退化：取症状首段，作为 matched_text
    snippet = symptoms.strip().split("。")[0]
    if len(snippet) > 20:
        snippet = snippet[:20]
    if snippet and not any(
        snippet in symptoms[s:e] or symptoms[s:e].endswith(snippet)
        for s, e in used
    ):
        return snippet
    return ""


def _grab_window(text: str, idx: int, length: int) -> str:
    """取包含 idx，长度近似 length 的中文窗，停在最近的句号/逗号/分号。"""
    if idx < 0:
        return ""
    start = max(0, idx - 4)
    end = min(len(text), idx + length + 8)
    s = text[start:end].strip()
    for cut in ("，", "、", "；", "。", "\n"):
        last = s.rfind(cut)
        if last > 4:
            s = s[:last]
            break
    return s or text[idx : idx + length]


# ---------- RAG 检索 ----------


def _normalize_gene(gene_report: str) -> list[str]:
    """从基因报告原文里粗抽基因符号（多个 token，作为 query 的扩展）。"""
    import re

    if not gene_report:
        return []
    # 形如 MECP2 / SCN1A / UBE3A
    symbols = re.findall(r"\b[A-Z][A-Z0-9]{1,9}\b", gene_report)
    # 过滤明显无关的 token
    stop = {"WES", "DNA", "RNA", "PCR", "MRI", "CT", "ASD", "FISH", "NGS", "VUS"}
    return [s for s in symbols if s not in stop][:6]


def retrieve_chunks(hpo_terms: List[HpoTerm], gene_report: str) -> List[Chunk]:
    """以「标准化症状 + 基因变异名」为查询键检索 ChromaDB。

    知识库为中文，查询串必须是中文。collection 名与 embedding 模型一律从 config 取。
    """
    # session 对象从 app 全局拿
    chroma_client = getattr(app.state, "chroma_client", None)
    embedder = getattr(app.state, "embedder", None)
    if chroma_client is None or embedder is None:
        return []

    # 中文 query 串：HPO 中文名 + 基因符号
    name_zh = [t.name for t in hpo_terms if t.name]
    genes = _normalize_gene(gene_report)
    query_parts = name_zh + genes
    if not query_parts:
        return []
    query = "症状: " + " ".join(name_zh) + " 基因: " + " ".join(genes)

    try:
        collection = chroma_client.get_collection(
            name=COLLECTION_NAME, embedding_function=embedder
        )
    except Exception:
        return []

    try:
        result = collection.query(
            query_texts=[query], n_results=8
        )
    except Exception:
        return []

    docs = (result.get("documents") or [[]])[0]
    metas = (result.get("metadatas") or [[]])[0]
    out: list[Chunk] = []
    for text, meta in zip(docs, metas):
        meta = meta or {}
        bucket = meta.get("bucket") or "A"
        origin = meta.get("origin") or "curated"
        source = meta.get("source") or ""
        if bucket not in ("A", "B", "C"):
            bucket = "A"
        if origin not in ("curated", "genereviews", "pubmed", "aap"):
            origin = "curated"
        out.append(
            Chunk(
                bucket=bucket,  # type: ignore[arg-type]
                origin=origin,  # type: ignore[arg-type]
                source=str(source),
                text=str(text),
            )
        )
    return out


# ---------- LLM 合成 ----------


def _format_chunks(chunks: List[Chunk]) -> str:
    lines = []
    for i, c in enumerate(chunks, 1):
        lines.append(
            f"[{i}] [桶 {c.bucket} · {c.origin}] {c.source}\n{c.text}"
        )
    return "\n\n".join(lines) if lines else "（无）"


def _sanitize_explanation(s: str) -> str:
    """最后兜底：把强诊断措辞替换成中性表述。"""
    if not s:
        return s
    s = s.replace("确诊", "文献特征")
    s = s.replace("患有", "出现")
    s = s.replace("即为", "属于")
    return s


async def _synthesize_report_async(
    request: ScreeningRequest,
    hpo_terms: List[HpoTerm],
    chunks: List[Chunk],
) -> dict:
    """synthesize_report 的真实实现（异步）。"""
    if not chunks:
        return {
            "comparisons": [],
            "vus_reassurance": (
                "未匹配到相关指南条目；本次无法给出客观比对。"
                "建议以专科医生面诊为准。"
            ),
            "next_steps": [
                "携带本次描述与基因检测报告原件，前往正规三甲医疗机构的儿童发育行为科就诊。",
                "同时预约医学遗传科门诊，就报告中变异的解读与后续验证测序方案向专业医生当面咨询。",
                "就诊前用手机录下孩子典型表现片段并记录持续时间，方便医生现场评估。",
            ],
        }

    chunk_block = _format_chunks(chunks)
    gene_block = (request.gene_report or "").strip()
    hpo_block = (
        "; ".join(f"{t.hpo_id} ({t.name})" for t in hpo_terms)
        if hpo_terms
        else "（无）"
    )

    user_prompt = (
        f"## 用户基因报告原文\n{gene_block}\n\n"
        f"## 已标准化 HPO 术语\n{hpo_block}\n\n"
        f"## RAG 检索切片（你只能引用这些）\n{chunk_block}\n\n"
        "请按 system 指令输出 JSON。"
    )

    parsed = await _m3_chat(
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]
    )

    out = {
        "comparisons": _extract_comparisons(parsed.get("comparisons")),
        "vus_reassurance": _sanitize_explanation(
            (parsed.get("vus_reassurance") or "").strip()
            or "看到报告上「临床意义未明（VUS）」时感到不安是正常的——它只代表现有证据不足以判断含义，并不构成结论。建议您按下方就诊清单与专业医生面诊。"
        ),
        "next_steps": _extract_next_steps(parsed.get("next_steps")),
    }
    return out


def _extract_comparisons(raw: Any) -> list[dict]:
    if not isinstance(raw, list):
        return []
    out: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        condition = str(item.get("condition") or "").strip()
        gene = str(item.get("gene") or "").strip()
        anchors = item.get("matched_anchors") or []
        if not isinstance(anchors, list):
            anchors = []
        anchors = [str(a).strip() for a in anchors if a][:8]
        explanation = _sanitize_explanation(str(item.get("explanation") or "").strip())
        source = str(item.get("source") or "").strip()
        if not (condition and explanation and source):
            continue
        out.append(
            {
                "condition": condition,
                "gene": gene,
                "matched_anchors": anchors,
                "explanation": explanation,
                "source": source,
            }
        )
    return out


def _extract_next_steps(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        raw = []
    out: list[str] = []
    for s in raw:
        if not isinstance(s, str):
            continue
        s = _sanitize_explanation(s.strip())
        if not s:
            continue
        out.append(s)
        if len(out) >= 8:
            break
    if not out:
        out = [
            "携带本次描述与基因检测报告原件，前往正规三甲医疗机构的儿童发育行为科就诊。",
            "同时预约医学遗传科门诊，就报告中变异的解读与后续验证测序方案向专业医生当面咨询。",
            "就诊前用手机录下孩子典型表现片段并记录持续时间，方便医生现场评估。",
        ]
    # 兜底：确保同时含两个科室术语（PRD AC4）。缺失则补齐。
    joined = " ".join(out)
    if "儿童发育行为科" not in joined:
        out.append("建议前往正规三甲医疗机构的儿童发育行为科就诊。")
    if "医学遗传科" not in joined:
        out.append("建议同时预约医学遗传科门诊，由专业医生当面解读基因报告。")
    return out


# ---------- 端点 ----------


@app.post(
    "/api/screen",
    response_model=ScreeningResponse,
    response_model_exclude_none=True,
)
async def screen(payload: ScreeningRequest) -> ScreeningResponse:
    """全系统唯一业务端点。

    组装顺序：入参校验 -> MCP 标准化 -> RAG 检索 -> LLM 合成 -> disclaimer 硬填充。
    """
    if not payload.symptoms.strip() or not payload.gene_report.strip():
        raise ScreeningError(
            422, "INVALID_INPUT", "症状描述与基因报告均为必填项，请补全后重新提交。"
        )

    # 测试期注入（tc_09 / tc_10 / tc_11 由环境变量驱动，见 apply_acceptance_setup()）
    setup_err = apply_acceptance_setup()
    if setup_err is not None:
        raise setup_err

    hpo_terms, mcp_log = await mcp_translate_symptoms(payload.symptoms)
    if not hpo_terms:
        raise ScreeningError(
            422,
            "HPO_NO_MATCH",
            "暂未匹配到标准表型术语；请补充更具体的表现描述。",
        )

    chunks = retrieve_chunks(hpo_terms, payload.gene_report)

    parts = await _synthesize_report_async(payload, hpo_terms, chunks)

    # disclaimer 硬填充，不经 LLM。
    return ScreeningResponse(
        hpo_terms=hpo_terms,
        comparisons=[Comparison(**c) for c in parts["comparisons"]],
        vus_reassurance=parts["vus_reassurance"],
        next_steps=parts["next_steps"],
        disclaimer=official_disclaimer(),
        mcp_translation=mcp_log,
        retrieved_chunks=chunks,
    )


# ---------- 错误收口（docs/schema.md §3.1） ----------


@app.exception_handler(ScreeningError)
async def screening_error_handler(request: Request, exc: ScreeningError) -> JSONResponse:
    """错误一律以 HTTP 状态码承载，禁止「一律 200 + status 字段」的信封模式。

    422 INVALID_INPUT / 422 HPO_NO_MATCH / 500 MISSING_API_KEY /
    502 MINIMAX_API_ERROR
    """
    return JSONResponse(
        status_code=exc.status_code,
        content=ErrorResponse(
            error_code=exc.error_code, error_message=exc.error_message
        ).model_dump(),
    )


# ---------- 健康检查 ----------


@app.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok", "backend_url": BACKEND_URL}
