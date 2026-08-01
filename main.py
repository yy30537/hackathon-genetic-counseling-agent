"""ASD-GenDecoder 后端：串联 MCP 表型标准化、RAG 检索与 Minimax M3 生成。

骨架文件，只定义结构与签名，不含业务实现。属主为后端智能体（见 AGENTS.md 第 1 节）。

契约以 docs/schema.md 为唯一事实来源，禁止发明字段。
启动：uvicorn main:app --reload --port 8000

实现顺序参考 docs/PRD.md 的 M2-M6，完成后必须跑通 python scripts/run_acceptance.py。
"""

from contextlib import asynccontextmanager
from typing import List, Literal, Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from config import official_disclaimer

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
    confidence_level: Optional[int] = None


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


# ---------- 应用生命周期 ----------


@asynccontextmanager
async def lifespan(app: FastAPI):
    """在此建立常驻的 HPO MCP stdio 会话并挂到 app.state.hpo。

    每请求重启子进程会累积 1-2 秒冷启动，逐词查询能拖到十几秒，故必须在此复用。
    骨架见 docs/env-setup.md §4.3。
    """
    # TODO(M3): stdio_client(StdioServerParameters(command="node", args=[HPO_MCP_SERVER_PATH]))
    #           -> ClientSession -> await session.initialize() -> app.state.hpo = session
    app.state.hpo = None
    yield


app = FastAPI(title="ASD-GenDecoder Backend", lifespan=lifespan)


# ---------- 流水线（docs/PRD.md §3 Entity Flow） ----------


async def mcp_translate_symptoms(symptoms: str) -> tuple[List[HpoTerm], str]:
    """把家长白话标准化为 HPO 术语。返回 (hpo_terms, mcp_translation 过程文本)。

    HPO 官方 API 只索引英文，链路必须是两段式：
    M3 中译英抽关键词 -> search_hpo_terms -> M3 回填中文名。

    AC2：任一非空症状必产出 >=1 条，每条含形如 HP:0000733 的 hpo_id。
    """
    raise NotImplementedError("M3")


def retrieve_chunks(hpo_terms: List[HpoTerm], gene_report: str) -> List[Chunk]:
    """以「标准化症状 + 基因变异名」为查询键检索 ChromaDB。

    知识库为中文，查询串必须是中文。collection 名与 embedding 模型一律从 config 取。
    """
    raise NotImplementedError("M4")


def synthesize_report(
    request: ScreeningRequest,
    hpo_terms: List[HpoTerm],
    chunks: List[Chunk],
) -> dict:
    """把切片注入 system prompt，要求 M3 返回结构化 JSON。

    只返回 comparisons / vus_reassurance / next_steps 三块，disclaimer 不经此处。
    解析失败抛 ScreeningError(502, MINIMAX_API_ERROR)，禁止把原始文本透传给前端。
    切片为空时应短路，不要把空上下文丢给模型自由发挥（不变量 I8）。
    """
    raise NotImplementedError("M5")


# ---------- 端点 ----------


@app.post("/api/screen", response_model=ScreeningResponse)
async def screen(payload: ScreeningRequest) -> ScreeningResponse:
    """全系统唯一业务端点。

    组装顺序：入参校验 -> MCP 标准化 -> RAG 检索 -> LLM 合成 -> disclaimer 硬填充。
    """
    if not payload.symptoms.strip() or not payload.gene_report.strip():
        raise ScreeningError(
            422, "INVALID_INPUT", "症状描述与基因报告均为必填项，请补全后重新提交。"
        )

    # TODO(M2): 依次调用 mcp_translate_symptoms / retrieve_chunks / synthesize_report
    #           并组装为 ScreeningResponse。
    #
    # disclaimer 必须走下面这一行：桶 C 逐字原文，不经 LLM，任何执行路径（含降级路径）
    # 都必须填充。验收脚本用的是同一个函数，走这条路就不可能对不上（不变量 I1 / AC4）。
    _ = official_disclaimer()

    raise NotImplementedError("M2")


# ---------- 错误收口（docs/schema.md §3.1） ----------


@app.exception_handler(ScreeningError)
async def screening_error_handler(request: Request, exc: ScreeningError) -> JSONResponse:
    """错误一律以 HTTP 状态码承载，禁止「一律 200 + status 字段」的信封模式。

    422 INVALID_INPUT / 500 MISSING_API_KEY / 502 MINIMAX_API_ERROR
    """
    return JSONResponse(
        status_code=exc.status_code,
        content=ErrorResponse(
            error_code=exc.error_code, error_message=exc.error_message
        ).model_dump(),
    )
