"""ASD-GenDecoder 前端：单文件 Streamlit 应用「静谧证据台」。

骨架文件，只定义结构与签名，不含业务实现。属主为前端智能体（见 AGENTS.md 第 1 节）。

函数清单与调用顺序照 docs/UI_BLUEPRINT.md §8，**函数名不得改、不得增删**。
视觉令牌、组件编号（C-xx）与验收清单同见该文档。

启动：streamlit run app.py（需后端 uvicorn 进程同时运行）
"""

import streamlit as st

from config import BACKEND_URL  # noqa: F401  骨架暂未使用，实现 call_backend 时接上

# ---------- 常量与工具 ----------

# 后端未就绪时置 True，改读 data/fixtures/ 下的 mock，可跑通全部渲染分区。
USE_MOCK: bool = False

# 比对卡页脚的引用编号（§5.3）
CIRCLED = "①②③④⑤⑥⑦⑧⑨"

# docs/UI_BLUEPRINT.md §7 全文，通过 st.markdown(unsafe_allow_html=True) 注入。
CSS: str = """
:root{
  --bg-canvas:#FAFAF7; --bg-surface:#FFFFFF; --bg-panel:#F4F3EE;
  --brand:#5B8C85; --brand-strong:#47726C; --brand-soft:#E4EFEC;
  --text-primary:#1F2321; --text-muted:#7A807C; --text-muted-strong:#636965;
  --border:#E6E4DD;
  --bucket-a:#5B8C85; --bucket-a-soft:#E4EFEC;
  --bucket-b:#7C6BA8; --bucket-b-soft:#EDE9F5;
  --bucket-c:#C08A3E; --bucket-c-soft:#F7EDDC;
  --radius:12px; --shadow:0 1px 3px rgba(31,35,33,.06);
  --font-sans:-apple-system,BlinkMacSystemFont,"PingFang SC","Noto Sans SC","Microsoft YaHei",Inter,sans-serif;
  --font-mono:"JetBrains Mono","SF Mono",Menlo,Consolas,monospace;
}

/* 全局 */
html, body, [class*="css"]{ font-family:var(--font-sans); color:var(--text-primary); }
.stApp{ background:var(--bg-canvas); }
.block-container{ max-width:1180px; padding:32px 32px 64px; }
#MainMenu, footer{ visibility:hidden; }

/* C-01 */
.ced-header{ border-bottom:1px solid var(--border); padding-bottom:16px; margin-bottom:24px; }
.ced-title{ font-size:24px; line-height:1.4; font-weight:600; }
.ced-sub{ font-size:16px; line-height:1.8; color:var(--text-muted); margin-top:4px; }

/* 通用分区 */
.ced-section{ margin-bottom:32px; }
.ced-section-title{ font-size:18px; line-height:1.5; font-weight:600; margin-bottom:12px; }
.ced-note{ font-size:13px; line-height:1.6; color:var(--text-muted-strong); }
.ced-card{ background:var(--bg-surface); border:1px solid var(--border);
           border-radius:var(--radius); box-shadow:var(--shadow); padding:20px; margin-bottom:16px; }

/* C-05 */
.ced-quote{ border-left:3px solid var(--bucket-b); padding-left:16px;
            font-size:17px; line-height:1.9; }

/* C-06 */
.ced-hpo{ width:100%; border-collapse:collapse; }
.ced-hpo th{ text-align:left; font-size:13px; font-weight:400; color:var(--text-muted-strong);
             padding:0 0 8px; border-bottom:1px solid var(--border); }
.ced-hpo td{ padding:12px 0; border-bottom:1px solid var(--border);
             font-size:16px; line-height:1.8; vertical-align:top; }
.ced-hpo tr:last-child td{ border-bottom:none; }
.ced-hpo .ced-std{ font-weight:600; }
.ced-hpoid{ font-family:var(--font-mono); font-size:13px; color:var(--text-muted-strong); margin-left:8px; }

/* C-07 */
.ced-cmp-head{ display:flex; align-items:center; gap:8px; margin-bottom:12px; }
.ced-cmp-title{ font-size:18px; font-weight:600; }
.ced-gene{ font-family:var(--font-mono); font-size:13px; background:var(--brand-soft);
           color:var(--brand-strong); border-radius:999px; padding:2px 10px; }
.ced-anchors{ display:flex; flex-wrap:wrap; gap:6px; margin-bottom:12px; }
.ced-anchor{ font-size:13px; background:var(--brand-soft); color:var(--brand-strong);
             border-radius:999px; padding:2px 10px; }
.ced-cmp-body{ font-size:16px; line-height:1.8; }
.ced-cmp-src{ margin-top:12px; padding-top:12px; border-top:1px solid var(--border);
              text-align:right; font-family:var(--font-mono); font-size:13px; color:var(--text-muted-strong); }

/* C-08 */
.ced-step{ display:flex; gap:12px; margin-bottom:12px; }
.ced-step-idx{ flex:0 0 20px; height:20px; margin-top:4px; border-radius:4px;
               background:var(--brand-soft); color:var(--brand-strong);
               font-size:13px; text-align:center; line-height:20px; }
.ced-step-txt{ font-size:16px; line-height:1.8; }

/* C-09 / C-10 右栏 */
.ced-panel{ background:var(--bg-panel); border-radius:var(--radius); padding:20px; }
.ced-chunk{ background:var(--bg-surface); border:1px solid var(--border);
            border-radius:var(--radius); padding:16px; margin-bottom:12px; }
.ced-chunk-head{ display:flex; align-items:center; gap:8px; margin-bottom:8px; flex-wrap:wrap; }
.ced-refno{ font-family:var(--font-mono); font-size:13px; color:var(--text-muted-strong); }
.ced-tag{ font-size:13px; border-radius:4px; padding:2px 8px; }
.ced-tag-a{ background:var(--bucket-a-soft); color:var(--bucket-a); }
.ced-tag-b{ background:var(--bucket-b-soft); color:var(--bucket-b); }
.ced-tag-c{ background:var(--bucket-c-soft); color:var(--bucket-c); }
.ced-origin{ font-size:13px; background:var(--bg-panel); color:var(--text-muted-strong);
             border-radius:4px; padding:2px 8px; }
.ced-chunk-src{ margin-left:auto; font-family:var(--font-mono); font-size:13px; color:var(--text-muted-strong); }
.ced-chunk-text{ font-size:13px; line-height:1.7; }
.ced-chunk-text summary{ cursor:pointer; color:var(--brand-strong); }

/* C-11 / C-12 */
.ced-disclaimer{ background:var(--bucket-c-soft); border-left:4px solid var(--bucket-c);
                 border-radius:var(--radius); padding:20px; margin-top:32px; }
.ced-disclaimer-label{ font-size:13px; font-weight:600; color:var(--bucket-c); margin-bottom:8px; }
.ced-disclaimer-body{ font-size:16px; line-height:1.8; }
.ced-error{ background:var(--bucket-c-soft); border:1px solid var(--bucket-c);
            border-radius:var(--radius); padding:20px; }
.ced-error-title{ font-size:18px; font-weight:600; color:var(--bucket-c); margin-bottom:8px; }

/* Streamlit 控件覆盖 */
.stButton>button, .stFormSubmitButton>button{
  background:var(--brand); color:#fff; border:none; border-radius:var(--radius);
  font-weight:600; padding:10px 20px; }
.stButton>button:hover, .stFormSubmitButton>button:hover{ background:var(--brand-strong); color:#fff; }
.stTextArea textarea{ background:var(--bg-surface); border:1px solid var(--border);
  border-radius:var(--radius); font-size:16px; line-height:1.8; color:var(--text-primary); }
.stTextArea textarea:focus{ border-color:var(--brand); box-shadow:none; }
.st-key-gene_report textarea{ font-family:var(--font-mono); }
div[data-baseweb="notification"]{ background:var(--bucket-c-soft) !important;
  border-left:4px solid var(--bucket-c) !important; color:var(--text-primary) !important; }
"""


def load_fallback_disclaimer() -> str:
    """非成功态没有响应体时的免责声明来源。

    读 data/knowledge/bucket_c_compliance.json 中 is_disclaimer == true 的 text，
    启动时读一次缓存。**禁止在本文件里硬编码该段文字**（验收项 V2）。
    读取失败时返回空字符串，并由 render_disclaimer 渲染一行读取失败提示——
    绝不静默隐藏免责条。
    """
    # TODO: 复用 config.official_disclaimer()，与后端共用同一读取入口，杜绝文案漂移
    return ""


def load_mock(kind: str) -> dict:
    """读取 data/fixtures/mock_response.{success,error}.json。kind in {"success", "error"}。"""
    # TODO
    return {}


def call_backend(symptoms: str, gene_report: str):
    """POST 到 {BACKEND_URL}/api/screen，返回 (stage, payload_or_err)。

    stage in {"success", "error"}。请求与 JSON 解析全程 try/except：
    连接失败、超时、非 200、响应无法解析都必须落到 error 分支，
    进程不崩溃、不白屏、不把 traceback 打到页面（AC6 / 验收项 S3、V5）。
    """
    # TODO
    return "error", {}


def match_chunk_refs(comparisons: list, chunks: list) -> list:
    """为每张比对卡算出它引用了右栏哪几条切片，返回下标列表的列表。算法见 §5.2。"""
    # TODO
    return []


# ---------- 渲染函数（每个内部只做一次 st.markdown） ----------


def render_header() -> None:
    """页眉。"""
    # TODO


def render_idle_hint() -> None:
    """C-13 空闲态提示。"""
    # TODO


def render_loading() -> None:
    """C-14 加载态。"""
    # TODO


def render_reassurance(text: str) -> None:
    """C-05 VUS 降焦虑话术。"""
    # TODO


def render_hpo_table(hpo_terms: list) -> None:
    """C-06 表型标准化对照表。hpo_id 用等宽字体。"""
    # TODO


def render_comparisons(comparisons: list, refs: list) -> None:
    """C-07 逐病比对卡；comparisons 为空数组时渲染 C-16 静默态。

    静默态下**不得出现任何推测性病名**（验收项 V3）。页脚用 CIRCLED 标注引用编号。
    """
    # TODO


def render_next_steps(steps: list) -> None:
    """C-08 就诊建议清单。"""
    # TODO


def render_confidence_line(value) -> None:
    """C-17 筛查可信度，PRD C6 Roadmap 字段。

    字段缺失时**静默不渲染**本行。文案只能用「筛查可信度」「匹配可信度」等中性表述，
    禁止「概率」「可能性」「几率」，禁止用颜色梯度暗示数值越高越可能得病（不变量 I9）。
    """
    # TODO


def render_error(err: dict) -> None:
    """C-12 错误卡。任何异常都必须落到这张卡上。"""
    # TODO


def render_intake_form(disabled: bool) -> None:
    """C-03 / C-04 双输入表单与提交按钮。

    两输入框任一为空时 st.warning 拦截并提示补全，**不向后端发请求**（AC8 / 验收项 V6）。
    """
    # TODO


def render_evidence_panel(payload: dict) -> None:
    """C-09 / C-10 / C-15 右栏证据面板：MCP 标准化过程卡 + RAG 命中切片卡。"""
    # TODO


def render_disclaimer(text: str) -> None:
    """C-11 合规免责条，固定置底。

    idle / loading / success / error 四种状态下都必须出现，且必须在 st.columns 之外，
    与桶 C 原文逐字一致（验收项 V1）。用琥珀样式，页面不得出现纯红色像素。
    """
    # TODO


# ---------- 主流程（调用顺序见 §8，不得调整） ----------


def main() -> None:
    st.set_page_config(
        page_title="ASD-GenDecoder",
        layout="wide",
        initial_sidebar_state="collapsed",
    )
    st.markdown(CSS, unsafe_allow_html=True)

    state_defaults = {
        "stage": "idle",
        "payload": None,
        "err": None,
        "symptoms": "",
        "gene_report": "",
    }
    for key, default in state_defaults.items():
        if key not in st.session_state:
            st.session_state[key] = default

    render_header()

    left, right = st.columns([62, 38], gap="large")

    with left:
        # TODO: 按 stage 分发结果区
        #   idle    -> render_idle_hint()                                  C-13
        #   loading -> render_loading()                                    C-14
        #   success -> render_reassurance / render_hpo_table /
        #              render_comparisons / render_next_steps /
        #              render_confidence_line                              C-05..C-08, C-17
        #   error   -> render_error()                                      C-12
        render_intake_form(disabled=False)

    with right:
        render_evidence_panel({})

    # 必须在 columns 之外，保证任何状态下都置底且横跨整页
    render_disclaimer(load_fallback_disclaimer())


if __name__ == "__main__":
    main()
