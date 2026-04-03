# 计设web赛道

项目名称：坊知工：面向社会化学习的知识融合智能学伴

## 第一章 需求分析

“坊知工：面向社会化学习的知识融合智能学伴”是我们围绕真实学习过程打磨的作品。做这个系统的起点很直接：很多学习者并不缺内容，真正缺的是“把零散知识串起来”的能力，以及“为什么学不会”的及时反馈。为此，项目把人工智能大模型（以 Qwen 兼容接口为主，可配置切换）放在核心位置，再与认知诊断和知识图谱结合，形成“提问/作答 -> 诊断 -> 推荐 -> 图谱更新”的闭环。系统面向高校学生、自学者和需要个性化陪学的人群。功能上覆盖智能问答辅学、知识图谱构建与路径查询、学习画像、掌握度评估、个性化推荐和题库训练；性能上兼顾云端与本地部署，支持 Celery+Redis 异步削峰，并在外部依赖不可用时自动降级到 rule/mock/json，保证服务连续可用。

### 竞品分析（软件设计与开发赛道视角）

| 维度 | 本作品：坊知工：面向社会化学习的知识融合智能学伴 | 传统题库类产品 | 通用大模型助手 |
| --- | --- | --- | --- |
| 产品定位 | 诊断+图谱+推荐的一体化学习系统 | 刷题与答案检索 | 通用问答 |
| 知识组织 | Neo4j/NetworkX 图结构 + 概念关系 | 章节树/题单 | 上下文文本 |
| 大模型应用深度 | 大模型用于问答生成、知识抽取、概念扩展，并与规则引擎融合 | 主要是检索和规则策略，生成能力弱 | 生成能力强但教育场景缺少结构化约束 |
| 诊断能力 | 错因分类、严重度、建议动作可解释 | 以对错统计为主 | 解释依赖提示词，状态不持久 |
| 个性化 | 学习画像（style/interests/focus）+ 掌握度引擎 | 规则推荐为主 | 可对话但缺少长期画像 |
| 工程可用性 | 支持异步队列、降级容错、多存储后端 | 常规 Web 架构 | 非专用教育业务架构 |

---

## 第二章 概要设计

### 2.1 总体架构与模块层次

本章以图示为主，文字只保留结构结论。整体采用“五层协同”的经典分层架构：前端展示层负责交互体验，API 与鉴权层负责请求编排与安全控制，智能服务层负责大模型与诊断决策，异步任务层负责承接高耗时计算，数据与外部模型层负责长期沉淀与能力供给。该拆分使系统同时具备主链路同步响应、重任务异步处理和外部依赖故障可降级三项能力。

### 2.2 调用关系与模块接口

调用链建议直接放在时序图中展示：用户行为进入 API 后，先走大模型语义处理，再进入诊断与掌握度计算，最终写回数据库与图谱并反馈到 Dashboard/Knowledge Map。接口层采用统一响应结构（success、request_id、error_code），并保留 AI/Rule 来源字段，便于审计与复现实验。

### 2.3 人机界面设计（概要）

界面层聚焦三件事：
- 让用户快速进入任务（首页/导航）；
- 让用户看懂当前状态（仪表盘/图谱）；
- 让用户持续产生高质量学习数据（聊天/题库交互）。
建议在本节减少文字说明，采用“页面截图 + 人机交互流程图”联合呈现。

### 建议插图（第二章）

1) 图名：系统分层架构图
- 图内容要点（丰富版）：
	- 五层结构自上而下排布：用户终端层、前端展示层、API与鉴权层、智能业务服务层、异步与数据层。
	- 前端展示层细分为：首页、学习仪表盘、知识图谱、智能问答、题库训练、学习空间。
	- API 与鉴权层细分为：Flask Router、统一响应封装、请求追踪 request_id、Auth Token 校验、CORS。
	- 智能业务服务层细分为：认知诊断（错误类型/严重度）、掌握度引擎（遗忘曲线+新评分融合）、学习画像（KMeans+规则回退）、概念映射（关键词+序列匹配阈值）、图谱服务（路径计算/同步策略）。
	- 异步与数据层细分为：Celery Worker、Redis Broker、SQLite、JSON 回退存储、Neo4j Aura 图数据库、外部 LLM 服务。
	- 明确三类链路：
		1. 同步主链路（实线蓝色箭头）：用户请求 -> API -> 服务 -> 返回前端。
		2. 异步计算链路（虚线橙色箭头）：服务 -> Celery/Redis -> 结果回写。
		3. 容错降级链路（点划线灰色箭头）：外部依赖异常 -> rule/mock/json 回退。
	- 图右下角增加图例：实线=同步，虚线=异步，点划线=降级；颜色标识强相关模块。
	- 图上增加“关键指标注释框”：低耦合分层、高可用回退、可解释诊断、可扩展部署。
- Gemini 提示词（高保真版，可直接出图）：
“请绘制一张用于计算机设计大赛答辩的‘智能学习伴侣平台系统分层架构图’，画布 16:9，信息密度高但结构清晰。采用自上而下五层架构：
第1层 用户终端层：Web浏览器、学习者、教师（可选）。
第2层 前端展示层：首页、学习仪表盘Dashboard、知识图谱Knowledge Map、智能问答Chat、题库Question Bank、学习空间Spaces。
第3层 API与鉴权层：Flask API Gateway、Auth Token、Request ID Trace、统一响应协议、CORS。
第4层 智能业务服务层：认知诊断服务、掌握度引擎、学习画像服务、概念映射服务、图谱路径与同步服务。
第5层 异步与数据层：Celery Worker、Redis Broker、SQLite、JSON回退存储、Neo4j Aura、外部LLM（Qwen）。

请在图中体现三种连线并加图例：
1）同步主链路（蓝色实线） 用户请求->API->服务->前端回包；
2）异步任务链路（橙色虚线） 服务->Celery/Redis->结果回写数据库；
3）降级容错链路（灰色点划线） 当LLM或Neo4j不可用时回退到rule/mock/json。

视觉要求：
- 科技感、学术答辩风格，主色蓝青+少量橙色强调。
- 模块卡片圆角、轻阴影、统一图标风格。
- 在右下角放“设计亮点”注释框：可解释诊断、异步削峰、多存储容错、接口契约稳定。
- 输出为高清矢量风格，中文标签，适合直接放入论文或答辩PPT。”

2) 图名：核心请求调用时序图
- 图内容要点：User -> Frontend -> API -> Services -> Celery/Redis -> DB/Neo4j -> Frontend。
- Gemini 提示词：
“请绘制一张 UML 风格时序图，描述学习平台一次‘提问-诊断-推荐-可视化’流程。参与者包括用户、前端、Flask API、认知诊断服务、掌握度服务、Celery Worker、Redis、Neo4j、SQLite。要求标注同步与异步调用，布局清晰、论文风格。”

3) 图名：人机交互闭环图（建议新增）
- 图内容要点：用户目标 -> 页面触点 -> 系统反馈 -> 下一步学习动作，突出“看-学-测-改”的闭环。
- Gemini 提示词：
“请生成一张面向教育软件的人机交互闭环图，主题为‘坊知工学习交互流程’。流程分为四段：1）用户目标与输入（提问/答题/上传内容）；2）界面触点（首页、聊天、仪表盘、知识图谱）；3）系统反馈（大模型回答、诊断结论、推荐任务、掌握度变化）；4）用户下一步行动（复习、练习、追问）。要求使用清晰的中文标签、箭头形成闭环、配色与前两张架构图一致（蓝青为主），适合论文与答辩PPT。”

4) 图名：部署拓扑图（建议新增）
- 图内容要点：浏览器端、Flask 服务、Celery Worker、Redis、SQLite、Neo4j Aura、外部大模型 API 之间的部署与连接关系。
- Gemini 提示词：
“请生成一张教育软件系统部署拓扑图，展示浏览器客户端、Flask 后端、Celery Worker、Redis、SQLite、Neo4j Aura、外部 LLM API 的连接关系。请区分‘本地/云端’边界，标注主要端口与数据流向，采用蓝青配色、简洁学术风格，适合计算机设计大赛论文与答辩PPT。”

5) 图名：接口契约矩阵图（建议新增）
- 图内容要点：核心接口与关键字段的对应关系（如 success、request_id、error_code、extraction_method、confidence）。
- Gemini 提示词：
“请生成一张接口契约矩阵图，主题为‘智能学习平台核心 API 契约’。纵轴为接口（学习画像、个性化推荐、知识路径查询、知识抽取、行为映射等），横轴为关键字段（success、request_id、error_code、method、confidence、storage）。请用勾选或颜色区分字段覆盖情况，整体风格清晰、论文化、便于展示系统规范性。”

### 2.4 补充设计说明（用于版面扩展）

为保证系统在竞赛展示和真实使用中都“看得见、跑得稳、讲得清”，概要设计阶段额外强调以下三点：

- 可扩展性：服务层按能力拆分（诊断、画像、映射、图谱），后续新增算法模块时可平滑接入，不破坏现有接口。
- 可用性：主链路优先保证同步可返回；遇到高耗时任务自动异步化；外部依赖异常时支持 rule/mock/json 回退，避免前端无响应。
- 可审计性：接口统一携带 request_id，关键流程保留 AI/Rule 方法来源和置信度字段，便于答辩演示“结果从哪里来、为什么可信”。

建议排版：第二章可采用“3 图 + 1 表（接口矩阵）+ 1 段补充说明”的组合，以图为主、以文为辅，版面饱满且逻辑清晰。

---

## 第三章 详细设计

### 3.1 界面设计与典型流程

界面层采用“多页面 + 共享脚本”模式，目标是把学习动作拆成清晰步骤，而不是把所有功能堆在一个页面。

- 首页（index）：统一入口和导航。
- 智能对话（chat）：围绕“智能问答接口”做问答与会话管理，支持多会话本地持久化。
- 仪表盘（dashboard）：聚合“学习概览接口”，集中展示画像、诊断、推荐、复习提醒。
- 知识图谱（knowledge-map）：对接“图谱查询、路径规划、知识抽取、行为映射”等能力接口，支持路径查询与节点掌握度更新。
- 题库（question-bank）：对接“抽题、判题、生题”接口，形成练习闭环。
- 学习空间（spaces）：对接“空间与条目管理”接口，支持内容上传、摘要、预览。

典型使用流程（基于当前代码实现）：
1. 用户在 chat 或 question-bank 发起提问/作答。
2. 后端先做语义处理，再进入规则诊断与掌握度计算。
3. 结果写入事件日志与图谱状态，必要时触发异步任务。
4. dashboard 拉取聚合结果，knowledge-map 展示节点和路径变化。
5. 用户根据推荐继续学习，形成“输入-诊断-反馈-再学习”闭环。

### 3.2 数据库设计（含违背范式理由）

项目使用“SQL/JSON + Neo4j + 本地文件回退”的混合存储。原因是：账号与业务配置偏结构化，知识关系偏图结构，单一存储难以同时兼顾可维护性和路径推理效率。

#### 3.2.1 关系型/结构化数据（SQLite）

| 实体 | 关键字段示例 | 作用 |
| --- | --- | --- |
| user_profile | user_id, learning_style, style_scores, focus_minutes, updated_at | 存储学习画像 |
| auth/session | token_hash, expires_at, user_id | 登录会话与鉴权 |
| recommendations | user_id, items, generated_at | 推荐结果缓存 |

说明：结构化数据通过统一接口返回，响应中普遍包含 `success`、`request_id`、`error_code`。

#### 3.2.2 JSON/文件存储（工程回退层）

| 文件/数据域 | 作用 |
| --- | --- |
| backend/data/auth_users.json | 账号数据持久化 |
| backend/data/auth_sessions.json | 会话状态与过期管理 |
| backend/data/question_bank_*.json | 题库数据（官方/自定义） |
| backend/data/user_plans.json | 学习计划与任务 |

说明：当部分外部依赖不可用时，JSON 层用于保障核心流程继续可用。

#### 3.2.3 图数据（Neo4j）

| 节点/关系 | 说明 |
| --- | --- |
| (:User)-[:MASTERY]->(:Concept) | 用户对知识点掌握关系 |
| (:Concept)-[:PREREQUISITE_OF]->(:Concept) | 前置依赖关系 |
| (:Concept)-[:RELATED_TO]->(:Concept) | 关联知识关系 |

说明：知识路径查询在 Neo4j 可用时优先走图数据库；不可用时回退 JSON/NetworkX 路径推断。

#### 3.2.4 违背传统三范式说明

在知识关系查询场景里，如果完全按三范式拆分，系统会把大量性能开销消耗在多表 Join 上，实时交互体验会明显下降。因此我们在关系建模上做了“有意识的反范式”取舍：将“概念-关系-掌握度”直接落到图结构中，用更贴近业务语义的方式换取路径推理速度和交互实时性。这一取舍符合学习场景“关联推理 + 即时反馈”的核心需求。

### 3.3 关键算法/关键技术设计

本项目的难点不是“把模型接上去”，而是让结果在教学场景里可解释、可追踪、可回退。

1. 认知诊断（`cognitive_diagnosis` + `mastery_engine`）
- 规则引擎 `classify_error_by_rules` 对错误进行类型与严重度判定。
- 诊断输出包含 `error_type`、`severity`、`confidence`、`signals`、`recent_accuracy`、`near_miss` 等字段。

2. 题库判题与诊断联动（题库判题接口）
- 判题结果返回 `is_correct`、`score`、`evaluation_method`、`mastery_assessment`、`diagnosis`、`learning_advice`。
- 错题会写入错题事件与诊断事件，支撑后续推荐和报告。

3. 掌握度更新（`knowledge_graph`）
- 在 `KnowledgeGraph.update_mastery` 中使用遗忘曲线衰减：`forgetting_rate = 0.08`。
- 新评分与衰减历史融合后写回，并计算 `next_review`。

4. 概念映射（`concept_mapping`）
- 使用“关键词 + 子串 + 序列匹配”混合策略。
- 采用分场景阈值（`question/video/note/generic`）输出映射置信度。

5. 学习画像（`learning_profile`）
- 特征来源包括内容类型计数、QA 日志、概念数量等。
- 优先 KMeans（`n_clusters=3`）判定学习风格，不可用时回退规则推断（`rule_fallback`）。

6. 大模型与系统可靠性（工程保障）
- 请求统一封装 `request_id`，便于端到端追踪。
- Celery worker 有在线探测缓存（TTL 2.0s），不可用时可走同步兜底。
- 图谱路径接口支持 Neo4j 主路径和 JSON fallback 双通道。

### 建议插图（第三章）

1) 图名：界面总览拼图（建议用真实截图）
- 图内容要点：首页、聊天、仪表盘、知识图谱四图并排，标注“入口/交互/状态/关系”四个职责。
- Gemini 提示词：
“请生成一张论文风格的四联界面展示图，标题为‘核心界面总览’。四个分图分别为：首页、智能对话、学习仪表盘、知识图谱。每张图下方给出一句中文说明（入口导航/问题交互/状态总览/关系可视化）。整体版式整齐，蓝青配色，适合软件设计大赛文档。”

2) 图名：典型使用流程图（用户视角）
- 图内容要点：登录 -> chat/question-bank 输入 -> 判题与诊断 -> dashboard 推荐 -> knowledge-map 路径学习 -> 复习追问。
- Gemini 提示词：
“请绘制一张用户视角流程图，主题为‘典型学习使用流程’。流程节点包含：登录、提问/作答（chat 或 question-bank）、语义理解、错误归因、掌握度更新、推荐任务、图谱路径学习、复习追问。请用中文标签和闭环箭头，风格简洁学术。”

3) 图名：数据库 ER+图谱联合模型图
- 图内容要点：SQLite/JSON 业务域 + Neo4j 图结构的联合建模与回退关系。
- Gemini 提示词：
“请生成一张‘关系型/JSON + 图数据库联合模型图’，左侧展示业务数据域（UserProfile、AuthSession、Recommendations、QuestionBank、SpaceItems），右侧展示 Neo4j 图结构（User、Concept、PREREQUISITE_OF、RELATED_TO、MASTERY）。请标注主路径和 fallback 路径，风格清晰论文化。”

4) 图名：反范式设计说明图
- 图内容要点：关系型多表 Join 路径 vs 图数据库多跳查询路径的对比。
- Gemini 提示词：
“请绘制一张对比图，主题为‘反范式设计取舍说明’。左侧展示关系型多表 Join 的复杂链路，右侧展示图数据库多跳查询的简化链路，并标注‘实时性更优、语义更直观’。风格简洁、适合论文插图。”

5) 图名：认知诊断与掌握度算法流程图
- 图内容要点：题库作答输入 -> 判题评分 -> 错因分类 -> 掌握度衰减融合 -> 学习建议 -> 推荐/图谱反馈。
- Gemini 提示词：
“请画一张算法流程图，主题为‘判题-诊断-掌握度更新引擎’。流程包含：作答输入、评分与相似度计算、错误类型判定、严重度评估、遗忘曲线衰减融合、学习建议生成、仪表盘与图谱反馈。使用标准流程图图元，强调可解释和闭环迭代。”

6) 图名：大模型融合与降级机制图
- 图内容要点：LLM 主路径、Rule 校验路径、Celery 异步路径、异常降级路径（sync_fallback/json）。
- Gemini 提示词：
“请生成一张技术流程图，主题为‘LLM 融合与降级机制’。展示四条路径：LLM 主推理路径、规则校验路径、Celery 异步任务路径、异常降级路径（sync_fallback 或 json）。请标注触发条件、返回字段（success/request_id/mode）与结果流向，配色与前文一致，适合答辩展示。”

7) 图名：题库判题接口返回结构图（建议新增）
- 图内容要点：题库判题接口的返回字段分层（判题结果、诊断结果、掌握度结果、下一步动作）。
- Gemini 提示词：
“请生成一张接口返回结构图，主题为‘题库判题接口响应结构’。分四层展示字段：判题层（is_correct/score/evaluation_method）、诊断层（diagnosis.error_type/severity/confidence）、掌握度层（mastery_assessment/graph_sync）、引导层（learning_advice/next_action）。风格清晰、适合论文图示。”

---

## 附：本章写作与源码对应关系（便于答辩）

- 后端主入口与 API：backend/app/server.py
- 认知诊断：backend/app/services/cognitive_diagnosis.py
- 掌握度与建议：backend/app/services/mastery_engine.py
- 概念映射：backend/app/services/concept_mapping.py
- 学习画像：backend/app/services/learning_profile.py
- 图谱服务：backend/app/services/knowledge_graph.py, backend/app/services/neo4j_store.py
- 接口契约：backend/docs/API_CONTRACT.md
- 前端页面：frontend/index.html, frontend/chat.html, frontend/dashboard.html, frontend/knowledge-map.html, frontend/question-bank.html, frontend/spaces.html
- 前端页面脚本：frontend/assets/js/pages/chat-page.js, frontend/assets/js/pages/dashboard-page.js, frontend/assets/js/pages/knowledge-map.js, frontend/assets/js/pages/question-bank-page.js, frontend/assets/js/pages/spaces-page.js

（全文写作已按“软件设计与开发赛道”组织，重点突出工程结构、模块分层、接口契约，以及大模型能力的可解释与可落地实现。）
