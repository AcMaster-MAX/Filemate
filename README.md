# FileMate

面向大学生的本地优先 AI 学习规划助手：把课程资料转化为可追踪、可复习、可验证的学习闭环。

> 国家级大学生创新创业训练计划项目
> 2026 暑期开发阶段 | 负责人：胡希
> 成员：汤新阳、张金宝、徐书和、余恒、杨乐

---

## 🚀 最新版本

**FileMate v1.2 Reliable Foundation 开发版** (2026-08-09)

- 前端：Vue3 + Vite + Element Plus（自然绿色亮色设计系统）
- 后端：FastAPI + Python
- 核心功能：文件解析 / AI分类 / 里程碑识别 / 日程生成(.ics)
- AI 学习工具：摘要 / 知识卡 / 练习题 / 结构化笔记 / 文档问答
- 学习闭环：按考试日期生成每日复习计划 / SQLite 持久进度 / 重启续学 / CSV 与日历导出
- 今日学习：自动合并逾期计划、下一学习日与高频错题，按优先级生成每日队列
- 深度学习：资料分块检索与引用 / 交互练习 / 自动错题本 / 掌握追踪
- 间隔重复：根据作答质量安排下次复习，今日队列只推送已到期错题
- AI 导师：证据问答 / 苏格拉底追问 / 费曼讲解训练
- 真实评测：检索相关性匿名标注 / 正向率统计 / 95% Wilson 区间 / 脱敏 CSV 导出
- 个人知识库：持久化资料列表 / 跨资料检索 / 页码引用 / 学习产物回看
- 模拟面试：求职、竞赛答辩、保研复试 / 语音问答 / 四维评分 / 持久化复盘
- 可信执行：分类草稿 / 最终确认归档 / 冲突保护 / 失败回滚 / 一键撤销
- 数据可靠性：SQLite v1–v8 迁移 / Source-Artifact-Context / 重启恢复

**当前交付方式：** 优先保证开发者和队友可一键本地运行；Python Sidecar 与 Tauri 2 工程保留，NSIS/MSI 安装包调整到产品功能稳定后的发布阶段。

---

## 📋 8月计划（重要更新）

### ⚡ 8月3日前完成（提前）

| 任务 | 说明 | 状态 |
|------|------|------|
| 移动端适配 | 手机端UI兼容 | ✅ 已完成响应式布局 |
| 桌面打包 | Tauri打包成exe | 🟡 Tauri 配置已建立，待产物验收 |
| 用户认证 | 登录/注册功能 | 待规划 |
| 多语言支持 | i18n | 待规划 |
| 数据导出 | 知识卡与学习计划导出 | ✅ CSV / JSON / ICS 已完成 |
| AI 学习计划 | 资料 + 考试日期生成每日计划 | ✅ 已完成 MVP |

### 🎯 8月3日后：FileMate 2.0 规划

**核心目标：** 从文件管理升级为**个人知识操作系统**

```
FileMate 1.0 (当前)     →     FileMate 2.0 (未来)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
文件管理                      知识管理
用户找文件                    AI主动规划学习
被动存储                      主动成长
单一用户                      知识图谱 + RAG
```

---

## 目录

- [快速开始](#快速开始)
- [项目定位](#项目定位)
- [四层架构](#四层架构)
- [目录结构](#目录结构)
- [模块负责人与分工](#模块负责人与分工)
- [五个核心接口](#五个核心接口)
- [接口变更规则](#接口变更规则)
- [里程碑](#里程碑)
- [运行测试](#运行测试)
- [代码风格](#代码风格)
- [Git 工作流](#git-工作流)
- [周会机制](#周会机制)
- [常见问题](#常见问题)
- [项目文档索引](#项目文档索引)

---

## 快速开始

### 环境要求

- Python >= 3.10（推荐 3.11/3.12）
- Windows 11（主要开发平台）/ macOS / Linux
- Git

### 安装步骤

```bash
# 1. 克隆仓库
git clone https://github.com/cooooooosdas/Filemate.git
cd FileMate

# 2. 创建虚拟环境
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS / Linux:
source .venv/bin/activate

# 3. 安装项目与开发依赖（推荐）
uv sync --extra dev
# 或继续使用：pip install -r requirements.txt

# 4. 配置 LLM
cp .env.example .env
# 用文本编辑器打开 .env，填入 LLM_API_KEY / LLM_BASE_URL / LLM_MODEL
# .env 不会被提交到 Git（已在 .gitignore 中）

# 5. 验证安装
python -c "from filemate.llm_client import LLMClient; print('OK')"
```

安装完成后也可直接运行 `filemate <文件路径>` 或 `filemate-server`。提交前执行 `powershell -ExecutionPolicy Bypass -File scripts/verify.ps1`，会依次完成 Python 静态检查、后端测试和前端生产构建；GitHub Actions 使用相同质量门槛。

### Windows 队友一键运行（推荐）

```powershell
# 首次运行：自动安装 Python 与前端依赖，并检查环境
powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 -Setup

# 后续运行：双击“启动FileMate.bat”，或执行
powershell -ExecutionPolicy Bypass -File scripts/dev.ps1

# 停止前后端
powershell -ExecutionPolicy Bypass -File scripts/stop-dev.ps1

# 只检查环境，不启动
powershell -ExecutionPolicy Bypass -File scripts/doctor.ps1
```

启动成功后访问 `http://127.0.0.1:5173`，后端接口文档位于 `http://127.0.0.1:8001/docs`。未配置 LLM Key 时基础文件与界面功能仍可启动，AI 功能会给出明确配置提示。

### 使用方式

```bash
# 处理单个文件
python main.py <file_path>

# 监控目录模式（持续运行，新文件自动处理）
python main.py --watch-dir C:\Users\胡希\Downloads\CourseFiles

# 跳过 .ics 生成
python main.py <file_path> --no-calendar

# 指定数据库路径
python main.py <file_path> --db D:\data\filemate.db

# 详细日志
python main.py <file_path> -v
```

---

## 项目定位

**FileMate 解决什么问题：** 大学生的课件、作业、竞赛通知、考试通知散落在电脑里，命名杂乱，deadline 藏在文档深处容易漏掉。

**产品做三件事：**

1. 你拖一个文件进来 → 系统自动判断它是什么课、什么类型
2. 自动生成规范的文件名，一眼看出课程 / 类型 / 截止时间
3. 长通知（竞赛通知）→ 自动提取所有关键时间节点，生成日历提醒

**用户核心动作 = "点确认"。** AI 建议好之后，用户点一下确认，系统执行。

---

## 四层架构

```
  ┌──────────────┐      ┌──────────────┐      ┌──────────────┐      ┌──────────────┐
  │   感知层      │      │   理解层      │      │   确认层      │      │   执行层      │
  │ perception/  │ ────▶│ understanding│ ────▶│     ui/      │ ────▶│  execution/  │
  │              │      │              │      │              │      │              │
  │ • 文件解析    │      │ • 分类        │      │ • Gradio     │      │ • 文件归档    │
  │ • 目录监控    │      │ • 实体抽取    │      │   四 Tab     │      │ • .ics 生成  │
  │ • OCR        │      │ • 里程碑识别  │      │ • 确认/修改  │      │ • SQLite     │
  │              │      │ • 命名生成    │      │ • 进度展示   │      │ • 哈希去重   │
  └──────────────┘      └──────────────┘      └──────────────┘      └──────────────┘
        ▲                     ▲                    ▲                    ▲
        │                     │                    │                    │
  watchdog / PyPDF2    规则引擎 + LLM       用户交互界面            os / shutil
  python-docx           Prompt 工程           Gradio 4.x             icalendar
  PaddleOCR（可选）
        │                     │                    │                    │
        └─────────────────────┼────────────────────┼────────────────────┘
                              │                    │
                       ┌──────▼──────┐      ┌──────▼──────┐
                       │   core/     │      │   core/     │
                       │ Pipeline    │      │  Session    │
                       │ Worker      │      │ 状态机      │
                       │ (异步队列)   │      └─────────────┘
                       └─────────────┘
```

**数据流：** 文件 → 感知层提取文本 → 理解层分类/抽取/命名 → 确认层展示给用户 → 用户确认 → 执行层归档 / 生成 .ics / 写入 SQLite

---

## 目录结构

```
FileMate/
├── .env.example                 # 环境变量模板（复制为 .env 填入真实值）
├── .gitignore                   # Git 忽略规则
├── requirements.txt             # Python 依赖
├── main.py                      # 命令行入口（单文件 + watch 模式）
├── README.md                    # 本文件
│
├── datasets/                    # 样本数据（不入库）
│   ├── raw/                     #   课程文件样本（PDF / Word / PPT / 截图）
│   └── long_text/               #   长文本样本（竞赛通知 / 大创通知）
│
└── filemate/                    # 主包
    ├── __init__.py
    │
    ├── llm_client/              # ── LLM 统一封装（胡希）──
    │   ├── __init__.py
    │   ├── client.py            #   LLMClient — 统一调用入口（含重试 / 超时 / JSON 解析）
    │   ├── config.py            #   LLMConfig — 从 .env 加载配置
    │   ├── exceptions.py        #   异常体系（LLMAPIError / LLMTimeoutError / LLMRateLimitError）
    │   ├── providers/
    │   │   ├── __init__.py
    │   │   ├── base.py          #   BaseLLMProvider — 抽象基类
    │   │   └── step_speed.py    #   StepSpeedProvider — 对接 Step 3.7 Speed
    │   └── models/
    │       ├── __init__.py
    │       ├── message.py       #   Message 模型
    │       └── response.py      #   LLMResponse 模型
    │
    ├── perception/              # ── 感知层（汤新阳）──
    │   ├── __init__.py
    │   ├── file_parser.py       #   FileParser — 统一入口，按后缀选解析器
    │   ├── watcher.py           #   FileWatcher — watchdog / 轮询监控目录
    │   ├── ocr.py               #   OCRBackend — PaddleOCR 封装（可选）
    │   └── parsers/
    │       ├── __init__.py      #   解析器注册表
    │       ├── pdf.py           #   PDFParser（PyPDF2 / pdfplumber）
    │       ├── word.py          #   WordParser（python-docx）
    │       └── ppt.py           #   PPTParser（python-pptx）
    │
    ├── understanding/           # ── 理解层（张金宝）──
    │   ├── __init__.py
    │   ├── classifier.py        #   Classifier — 关键词规则兜底 + LLM 分类
    │   ├── entity_extractor.py  #   EntityExtractor — 抽取课程名 / 截止时间等
    │   ├── milestone_detector.py #  MilestoneDetector — 长通知多时间节点识别
    │   ├── namer.py             #   Namer — 生成规范文件名
    │   ├── rules/
    │   │   └── keywords.json    #   关键词规则库
    │   └── prompts/
    │       ├── __init__.py
    │       ├── classify.md      #   分类 Prompt 模板
    │       ├── extract.md       #   实体抽取 Prompt 模板
    │       ├── milestone.md     #   多里程碑 Prompt 模板
    │       └── naming.md        #   命名生成 Prompt 模板
    │
    ├── core/                    # ── Pipeline + Session（胡希）──
    │   ├── __init__.py
    │   ├── session.py           #   ProcessingSession — 单个文件全生命周期 + 状态机
    │   ├── pipeline.py          #   PipelineWorker — 异步消费队列 + 阶段链
    │   └── state_store.py       #   SQLiteStateStore — 薄封装，委托给 execution.storage
    │
    ├── execution/               # ── 执行层（徐书和）──
    │   ├── __init__.py
    │   ├── storage.py           #   SQLiteStorage — 四张表 + 线程安全
    │   ├── file_ops.py          #   FileOps — ensure_dir / move / rename / copy / hash
    │   ├── scheduler.py         #   CalendarBuilder — .ics 生成（RFC 5545）
    │   ├── archiver.py          #   Archiver — 归档到 <base>/<course>/<category>
    │   └── batch_processor.py   #   BatchProcessor — 并发限制 + 进度回调
    │
    ├── ui/                      # ── 确认层（余恒）──
    │   ├── __init__.py
    │   ├── app.py               #   FileMateUI — Gradio 主界面（4 Tab）
    │   ├── backend_api.py       #   BackendAPI — Gradio 与后端的胶水层
    │   └── components/
    │       └── __init__.py      #   可复用 Gradio 组件
    │
    ├── tests/                   # ── 测试（全体）──
    │   ├── __init__.py
    │   ├── test_file_ops.py     #   文件操作单元测试
    │   ├── test_calendar.py     #   .ics 生成测试
    │   ├── test_classifier.py   #   分类契约测试
    │   └── test_e2e.py          #   端到端集成测试（W4 里程碑）
    │
    └── docs/                    # ── 项目文档 ──
        ├── PROMPT_LIB.md        #   Prompt 库（v1→v5 迭代记录）
        └── API_SPEC.md          #   5 个接口契约（W4 后冻结）
```

---

## 模块负责人与分工

| 模块 | 路径 | 负责人 | 状态 | 备注 |
|---|---|---|---|---|
| LLM 统一封装 | `llm_client/` | 胡希 | ✅ 已完成 | Step 3.7 Speed 供应商已对接 |
| 感知层 | `perception/` | 汤新阳 | ✅ 已实现 | PDF / Word / PPT / TXT + OCR 可选 |
| 理解层 | `understanding/` | 张金宝 | ✅ MVP 已实现 | 分类 / 抽取 / 命名 / AI 学习工具 |
| Pipeline + Session | `core/` | 胡希 | ✅ 已完成 | 状态机 + 异步消费循环 |
| 执行层 | `execution/` | 徐书和 | ✅ 已完成 | SQLite / 文件 I/O / .ics / 归档 |
| Web 界面 | `filemate/web/` | 余恒 | ✅ MVP 已实现 | Vue 3 + FastAPI，含响应式布局 |
| 功能设计 + 协调 | 各模块 | 杨乐 | ⬜ 待启动 | 对齐各模块进度 |
| 测试 | `tests/` | 全体 | 🟡 部分 | 文件操作 + 日历 + 契约已覆盖 |

### 感知层开发指引（汤新阳）

你的目标是让 `FileParser.parse(path)` 返回如下结构：

```python
{
    "raw_text": "文件里的文字内容（字符串）",
    "metadata": {
        "filename": "原始文件名",
        "suffix": "文件后缀（小写，不含点）",
        "size_bytes": 12345,
    },
}
```

**开发顺序：**

1. 先实现 `parsers/word.py`（python-docx 最简单，用来验证流程）
2. 再实现 `parsers/pdf.py`（PyPDF2 / pdfplumber）
3. 然后 `parsers/ppt.py`（python-pptx）
4. 最后 `watcher.py`（watchdog 或轮询）+ `ocr.py`（PaddleOCR，可选）

验证方式：

```bash
python -c "
from filemate.perception import FileParser
p = FileParser()
print(p.parse('测试.docx'))   # 替换成你电脑上的真实文件
"
```

**模块使用示例：**

```python
from filemate.perception import FileParser

parser = FileParser()
result = parser.parse("实验报告.docx")
# {
#   "raw_text": "实验三：实现一个线程池...",
#   "metadata": {"filename": "实验报告.docx", "suffix": "docx", "size_bytes": 20480},
# }
text = result["raw_text"]
```

### 理解层开发指引（张金宝）

四个子模块的接口契约已经写在代码里，你只需要：

1. 读 `understanding/classifier.py` 里的 `classify()` 输出格式要求
2. 写 Prompt 模板到 `understanding/prompts/*.md`
3. 让 `classify()` 调用 `llm_client.call_structured()` 拿结构化 JSON
4. 用 `rules/keywords.json` 做规则引擎兜底

**开发顺序：** classifier → entity_extractor → milestone_detector → namer

**模块使用示例：**

```python
from filemate.llm_client import LLMClient
from filemate.understanding import Classifier, EntityExtractor, MilestoneDetector, Namer

llm = LLMClient()  # 自动从 .env 读取配置

# 1. 分类
classifier = Classifier(llm)
cat = classifier.classify(text="实验三：实现一个线程池...", filename="lab3.docx")
# {"category": "作业", "confidence": 0.83, "course_name": None, "reason": "关键词规则命中"}

# 2. 实体抽取
extractor = EntityExtractor(llm)
entities = extractor.extract(text)
# {"course_name": "操作系统", "task_description": "实验三", "deadline": "2026-05-20", ...}

# 3. 多里程碑识别
detector = MilestoneDetector(llm)
milestones = detector.detect(long_text)
# [{"event": "报名截止", "date": "2026-05-10", "order": 1}, ...]

# 4. 命名生成
namer = Namer(llm)
name = namer.generate(
    category=cat["category"],
    course=entities["course_name"] or "未分类",
    task=entities["task_description"] or "未命名",
    deadline=entities["deadline"] or "待定",
)
# "[操作系统]-[作业]-[实验三]-[0520]-[待处理]"
```

每个 Prompt 迭代到 v5 后归档到 `docs/PROMPT_LIB.md`。

### UI 层开发指引（余恒）

1. 读 `ui/backend_api.py`，理解 `submit / confirm / get_queue` 三个接口
2. 在 `ui/app.py` 里用 Gradio 4.x 搭四个 Tab
3. 先跑通"上传文件 → 展示解析文本"的最小链路，再逐步加功能

参考：

```bash
pip install gradio
python -m filemate.ui.app   # 或你写好的启动方式
```

**模块使用示例：**

```python
from filemate.ui.backend_api import BackendAPI
from filemate.execution.storage import SQLiteStorage
from filemate.core.pipeline import PipelineWorker
from filemate.core.session import ProcessingSession

# 1. 初始化
storage = SQLiteStorage("filemate.db")
storage.init_schema()
pipeline = PipelineWorker(stages=...)  # 见 main.py _make_stages()
api = BackendAPI(pipeline_worker=pipeline, state_store=storage)

# 2. 提交文件
result = api.submit("/path/to/lab3.docx")
# {"session_id": "a1b2c3d4e5f6", "source_path": "...", "status": "pending"}

# 3. 查询队列
queue = api.get_queue(status="pending")

# 4. 用户确认 / 拒绝
api.confirm(session_id="a1b2c3d4e5f6", accepted=True, edits={"suggested_name": "..."})

# 5. 查看操作日志
ops = api.get_operations("a1b2c3d4e5f6")
```

---

## 五个核心接口

> W4 里程碑后接口冻结，变更必须经过胡希。

| # | 接口 | 输入 | 输出 | 负责人 |
|---|---|---|---|---|
| 4.1 | 分类模块 | `text: str, filename: str` | `{category, confidence, course_name}` | 张金宝 |
| 4.2 | 实体抽取 | `raw_text: str` | `{course_name, task_description, deadline, location, extra_entities}` | 张金宝 |
| 4.3 | 多里程碑识别 | `raw_text: str` | `[{"event", "date", "order"}, ...]` | 张金宝 |
| 4.4 | 命名生成 | `category, course_name, task_description, deadline, status` | `str`（规范文件名） | 张金宝 |
| 4.5 | 执行层 | `file_path, new_name, target_dir` | `{success, error, dest_path}` | 徐书和 |

详见 `filemate/docs/API_SPEC.md`。

---

## 接口变更规则

1. **W4 前（8 月 3 日之前）：** 接口可调整，但必须先在群里告知胡希，胡希更新 `API_SPEC.md` 后你再改实现
2. **W4 后：** 接口冻结。需要变更 → 胡希评估影响 → 发版本更新
3. **私自改接口 = 阻塞他人开发**，会被记入周报

---

## 里程碑

| 里程碑 | 日期 | 验收标准 |
|---|---|---|
| **W1 启动** | 2026-07-13 | 环境搭建 + 各模块 Demo |
| **W2 感知层** | 2026-07-20 | 一个 .docx 丢进去能输出文本 + 元数据 |
| **W3 理解层** | 2026-07-27 | 分类准确率 ≥ 85%（50 份样本） |
| **里程碑 1** | **2026-08-03** | `python main.py <file>` + FastAPI + Vue3 完整流程 ✅ |
| **里程碑 2** | **2026-08-24** | 移动端适配 ✅；桌面工程 ✅；NSIS/MSI 与干净机验收 🟡 |
| **后续** | 2026-08-31 | 中期检查材料 |

---

## 📅 FileMate 2.0 展望（8月3日后启动）

### 项目简介

FileMate 2.0 是一个基于大语言模型与知识图谱的大学生个人知识操作系统。

随着数字化学习的发展，大学生积累了大量碎片化学习资源：PDF教材、课程PPT、学习笔记、实验代码、论文资料、图片资料。

然而，传统文件管理工具只能解决"文件存在哪里"，无法解决"这些知识之间有什么关系"、"我目前掌握了什么"、"下一步应该学习什么"。

因此，FileMate 2.0 提出一种面向大学生学习场景的 Personal Knowledge OS（个人知识操作系统）。

系统通过：多模态大模型理解学习资料、知识图谱组织个人知识、RAG增强知识检索、AI Agent主动规划学习路径，实现从文件管理→知识管理→个人成长管理的升级。

### 项目目标

构建一个属于大学生自己的：AI Knowledge Brain（个人知识大脑）。

帮助用户实现：自动理解学习资料、构建个人知识网络、分析知识掌握情况、发现学习薄弱点、生成个性化成长路线。

### 系统架构

```
User → Multimodal Knowledge Input (PDF/PPT/Image/Code/Notes) → Multimodal AI Engine (OCR/Document Parsing/Semantic Understanding)
→ Personal Knowledge Graph (Knowledge Nodes/Relations/User Knowledge Map)
→ AI Learning Agent (RAG Retrieval/Reasoning/Planning)
→ Personal Growth Model (Ability Assessment/Weakness Detection/Learning Recommendation)
→ Intelligent Learning Interface
```

### 核心创新点

**Innovation 1: 多模态个人知识图谱构建**

传统文件管理系统只能按照文件夹→文件组织信息，但是学习知识天然具有复杂关联。FileMate 通过文档解析、实体抽取、语义理解、知识关联自动构建个人知识图谱。

技术：Multimodal LLM, Embedding, Knowledge Graph, Entity Extraction

**Innovation 2: 基于知识状态感知的主动式AI学习Agent**

传统AI助手是用户提问→AI回答，缺少用户背景理解、长期学习规划、主动发现问题。FileMate Agent能够分析用户学习资料、知识掌握情况、学习目标，主动生成学习建议、知识补充、复习计划。

技术：LLM Agent, RAG, Reasoning, Planning

**Innovation 3: 面向个人成长目标的动态能力建模**

当前学习软件关注"有什么资料"，但忽略"用户能力如何变化"。FileMate建立个人知识画像，结合用户目标（保研/科研/就业/竞赛），生成个性化成长路径。

技术：User Modeling, Knowledge Tracing, Recommendation System

### 技术栈

| 模块 | 技术 |
|------|------|
| Framework | Vue3 |
| Language | TypeScript |
| UI | Element Plus |
| Visualization | ECharts / D3.js |
| Backend | FastAPI |
| Language | Python |
| Database | PostgreSQL |
| LLM | DeepSeek / Qwen / GLM |
| Embedding | BGE Series |
| RAG | LlamaIndex |
| Agent | LlamaIndex Agent |
| OCR | PaddleOCR |
| Vector Database | Chroma |
| Graph Database | Neo4j |

### MVP版本规划

- **v1.1** (当前)：文件上传 → 多格式解析 → AI知识提取 → 文档上下文问答 → 考试复习计划
- **v2.0** (目标)：持久化知识库 / 真正的向量 RAG → 用户画像 → 能力评估 → 主动式 Agent

> 当前问答使用单文档截断上下文，尚未实现向量检索、引用定位和跨文档知识库；README 不再将其标记为完整 RAG。

### Future Research Directions

1. **Knowledge Graph Optimization** - 知识抽取、图谱融合、知识推理
2. **LLM Agent** - Agent Planning、Tool Calling、Autonomous Learning
3. **Personalized Learning** - User Modeling、Knowledge Tracing、Recommendation System

### 项目一句话总结

FileMate 2.0 是一个基于大语言模型、知识图谱和智能Agent技术的个人知识操作系统，通过理解用户学习资料、构建个人知识网络，并主动规划学习路径，实现从文件管理到知识成长管理的智能化升级。

---

## 运行测试

```bash
# 安装测试依赖
pip install pytest pytest-asyncio

# 运行全部测试
pytest tests/ -v

# 只跑文件操作测试
pytest tests/test_file_ops.py -v

# 带覆盖率
pytest tests/ -v --cov=filemate --cov-report=term-missing
```

**测试提交要求：** 每个 milestone 前，你负责的模块必须有对应的测试用例通过。

---

## 代码风格

- **PEP 8**，缩进 4 空格
- 提交前运行 `black .` + `ruff check .`（见 `requirements.txt`）
- 所有公开函数/类必须有 docstring
- 每个 TODO 标记格式：`TODO(姓名): 描述`，方便 grep 追踪
- 日志用 `logging.getLogger(__name__)`，不用 print
- 接口函数必须写明输入输出格式（参考已有代码注释）

---

## Git 工作流

```
main (受保护，只能由胡希合并)
  │
  ├─ feat/perception-parser     (汤新阳)
  ├─ feat/classifier            (张金宝)
  ├─ feat/gradio-ui             (余恒)
  └─ ...
```

**工作方式：**

1. 从 main 拉一条新分支：`git checkout -b feat/你的模块名`
2. 开发，多次 commit（每周至少 2 次有效 commit）
3. 推送到远端：`git push -u origin feat/你的模块名`
4. 在 GitHub 上发 PR，@ 胡希 review
5. 胡希合并到 main

**禁止：**
- 直接 push 到 main
- -force push 到 main
- 提交 `.env` / `filemate.db` / `datasets/raw/*`（.gitignore 已覆盖）

---

## 周会机制

| 会议 | 频率 | 时间 | 内容 |
|---|---|---|---|
| 周站会 | 每周一 20:00 | 30 min | 上周完成 / 本周计划 / blockers |
| 里程碑评审 | W4 末 / W7 末 | 1–2 h | 端到端演示 + Bug 清理 + 下一阶段计划 |
| 结项会 | W8 末 | 2 h | 阶段总结 + 成果展示 + 开学后分工 |

**卡住超过 2 小时 → 群里喊胡希，不要自己闷着。**

---

## 常见问题

**Q：需要训练 AI 模型吗？**
> 不需要。分类、抽取、命名都是调 Step 3.7 Speed 的 API，Prompt 写好就行。

**Q：不会 Python 能参与吗？**
> 感知层、理解层、执行层、UI 层都需要写 Python。如果某块完全不熟悉，找胡希调整分工。

**Q：Gradio 是什么？难学吗？**
> 几行代码就能出界面。胡希有参考代码，照着搭就行。

**Q：Step API 额度够吗？**
> 暑期开发阶段够用。具体用量胡希有统计。

**Q：我负责的模块看不懂接口文档怎么办？**
> 找胡希，单独过一遍。接口文档不是让你一次全看懂，先有一个"知道要输出什么、输入什么"的概念。

**Q：AI 生成的代码能用吗？**
> 可以用，但必须读懂再提交。答辩时如果被问到细节答不上来，算你自己的问题。

**Q：Git 是什么？我没用过。**
> Git 就是"代码的云盘"。胡希会初始化好仓库，clone 下来直接用，不会的单独教。

---

## 部署

### 生产环境一键启动

```bash
# 1. 克隆 + 安装
git clone https://github.com/cooooooosdas/Filemate.git && cd FileMate
python -m venv .venv && source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env   # 填入真实 LLM key

# 2. 命令行模式（无界面）
python main.py --watch-dir C:\Users\胡希\Downloads\CourseFiles

# 3. Vue + FastAPI 界面（两个终端）
python server.py  # http://127.0.0.1:8001
cd filemate/web
npm install
npm run dev       # http://127.0.0.1:5173

# 4. 旧版 Gradio 界面（可选）
python -m filemate.ui.app
```

### Windows 桌面应用（最终发布阶段）

```powershell
cd filemate/web
npm ci
npm run desktop:build
```

该命令先构建 FastAPI sidecar，再生成 Tauri 的 NSIS/MSI 安装包。当前开发阶段无需执行；待核心功能与竞赛演示稳定后再恢复安装器验收。完整环境要求与数据目录说明见 `filemate/web/README.md`。

### Docker（计划中，W5 前完成）

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
CMD ["python", "-m", "filemate.ui.app"]
```

---

## 项目文档索引

- [`docs/FILEMATE_AI_PRODUCT_MASTER_PLAN.md`](docs/FILEMATE_AI_PRODUCT_MASTER_PLAN.md) — 学习、科研、竞赛、求职与数字人方向的长期产品总规划
- [`docs/PHASE0_ACCEPTANCE_REPORT.md`](docs/PHASE0_ACCEPTANCE_REPORT.md) — 可信执行、质量门禁、Sidecar 与 Windows 安装包的逐项验收证据
- [`docs/FILEMATE_EVALUATION_BASELINE.md`](docs/FILEMATE_EVALUATION_BASELINE.md) — 检索、面试评分与工程回归的可复现竞赛评测基线
- [`docs/COMPETITION_DEMO_SCRIPT.md`](docs/COMPETITION_DEMO_SCRIPT.md) — 7 分钟现场演示流程、话术与离线兜底
- [`docs/COMPETITION_JUDGE_QA.md`](docs/COMPETITION_JUDGE_QA.md) — 差异化、RAG、数字人、隐私与评测口径答辩问答

> 桌面 `FileMate_*.md` 系列为项目总纲级文档，clone 仓库后可从项目主页链接过去。

| 文档 | 位置 | 内容 |
|---|---|---|
| 项目总纲 | `FileMate_项目总纲_v1.0_2026.07.14.md` | 项目概述、技术决策、里程碑、分工 |
| 开会前速查手册 | `FileMate_开会前速查手册_2026.07.14.md` | 名词大白话 + 发言稿 + 常见追问 |
| 技术决策定稿 | `FileMate_技术决策定稿_v1.0_2026.07.14.md` | 6 项技术决策 + 理由 + 影响范围 |
| 核心框架架构 | `FileMate_核心框架架构_v1.0_2026.07.14.md` | 目录结构 + LLM 封装设计 + Pipeline + SQLite Schema + 接口契约 |
| 暑假任务里程碑 | `FileMate_暑假任务里程碑_v1.0_2026.07.14.md` | 8 周逐周计划 + 交付物 + 依赖图 + 风险矩阵 |
| Prompt 库 | `filemate/docs/PROMPT_LIB.md` | Prompt 模板 + 迭代记录（W6 前整理） |
| API 规范 | `filemate/docs/API_SPEC.md` | 5 个接口契约（W4 后冻结） |
