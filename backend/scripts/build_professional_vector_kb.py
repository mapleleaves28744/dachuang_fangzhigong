import argparse
import json
import os
import pickle
import random
import re
import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from itertools import cycle

from scipy.sparse import save_npz
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_OUT_DIR = os.path.join(BACKEND_DIR, "data", "pro_kb")


@dataclass
class ChapterSpec:
    discipline: str
    chapter: str
    concept_seeds: list[str]
    formula_templates: list[str]
    question_types: list[str]
    exam_points: list[str]


DISCIPLINE_BLUEPRINTS = {
    "高等数学": {
        "chapters": ["极限与连续", "导数与微分", "积分与应用", "级数"],
        "concepts": ["定义", "判别", "性质", "收敛", "近似", "应用", "误差", "模型"],
        "formulas": ["f'(x)=lim(Δy/Δx)", "∫a^b f(x)dx", "e^x=Σx^n/n!", "sin(x)≈x"],
        "qtypes": ["概念辨析", "计算题", "证明题", "应用建模"],
        "points": ["定义域约束", "符号方向", "收敛条件", "边界处理"],
    },
    "线性代数": {
        "chapters": ["矩阵运算", "行列式", "向量空间", "特征值与对角化"],
        "concepts": ["秩", "基", "线性无关", "可逆", "特征结构", "变换", "投影", "分解"],
        "formulas": ["A^{-1}A=I", "det(AB)=det(A)det(B)", "Ax=λx", "A=PΛP^{-1}"],
        "qtypes": ["概念辨析", "推导题", "计算题", "综合题"],
        "points": ["维数一致", "初等变换", "可逆条件", "特征向量归一"],
    },
    "概率论与数理统计": {
        "chapters": ["随机变量", "分布与期望", "大数定律", "参数估计"],
        "concepts": ["分布", "独立性", "期望", "方差", "估计", "置信区间", "检验", "样本"],
        "formulas": ["E(X)=Σxp(x)", "Var(X)=E(X^2)-E(X)^2", "P(A|B)=P(AB)/P(B)", "Z=(X-μ)/σ"],
        "qtypes": ["概念辨析", "计算题", "统计推断", "案例分析"],
        "points": ["条件与边际", "样本假设", "显著性水平", "分布适用性"],
    },
    "离散数学": {
        "chapters": ["命题逻辑", "集合与关系", "图论", "组合计数"],
        "concepts": ["蕴含", "等价", "闭包", "连通性", "匹配", "递归", "生成函数", "复杂度"],
        "formulas": ["P→Q≡¬P∨Q", "C(n,k)=n!/(k!(n-k)!)", "|A∪B|=|A|+|B|-|AB|", "T(n)=aT(n/b)+f(n)"],
        "qtypes": ["概念辨析", "证明题", "构造题", "算法题"],
        "points": ["边界样例", "反例构造", "计数去重", "递归终止"],
    },
    "数据结构与算法": {
        "chapters": ["线性结构", "树与图", "排序查找", "动态规划"],
        "concepts": ["复杂度", "不变式", "堆", "平衡", "最短路", "贪心", "状态转移", "剪枝"],
        "formulas": ["T(n)=O(nlogn)", "dist[v]=min(dist[v],dist[u]+w)", "dp[i]=min(...) ", "heapify(i)"],
        "qtypes": ["概念辨析", "代码阅读", "手算追踪", "复杂度分析"],
        "points": ["下标边界", "循环不变式", "重复状态", "剪枝正确性"],
    },
    "计算机网络": {
        "chapters": ["分层模型", "传输控制", "路由转发", "应用协议"],
        "concepts": ["封装", "拥塞控制", "滑动窗口", "路由", "时延", "吞吐", "可靠性", "握手"],
        "formulas": ["吞吐=窗口/RTT", "总时延=传播+排队+处理", "RTT≈2d/v", "RTO=f(RTT)"],
        "qtypes": ["概念辨析", "流程题", "计算题", "故障分析"],
        "points": ["状态转换", "报文字段", "时序图", "异常重传"],
    },
    "操作系统": {
        "chapters": ["进程线程", "内存管理", "文件系统", "并发同步"],
        "concepts": ["调度", "死锁", "页替换", "虚拟内存", "inode", "缓存", "互斥", "信号量"],
        "formulas": ["利用率=CPU忙/总时间", "EAT=p*缺页开销+...", "周转时间=完成-到达", "等待时间=周转-运行"],
        "qtypes": ["概念辨析", "流程题", "计算题", "系统分析"],
        "points": ["临界区", "置换策略", "状态迁移", "资源有序"],
    },
    "数据库系统": {
        "chapters": ["关系模型", "SQL与优化", "事务并发", "索引存储"],
        "concepts": ["范式", "连接", "视图", "事务", "隔离级别", "B+树", "日志", "恢复"],
        "formulas": ["选择率=命中/总行数", "IO成本≈层高+页访问", "冲突图判定串行化", "WAL先写日志"],
        "qtypes": ["概念辨析", "SQL改写", "执行计划", "事务分析"],
        "points": ["谓词下推", "锁粒度", "索引覆盖", "幻读场景"],
    },
    "编译原理": {
        "chapters": ["词法分析", "语法分析", "语义分析", "代码生成"],
        "concepts": ["正则", "自动机", "FIRST/FOLLOW", "LR", "符号表", "中间代码", "优化", "寄存器分配"],
        "formulas": ["DFA=子集构造(NFA)", "FIRST(α)", "FOLLOW(A)", "活跃变量分析"],
        "qtypes": ["概念辨析", "构造题", "推导题", "优化分析"],
        "points": ["左递归", "冲突项", "作用域", "回填"],
    },
    "机器学习": {
        "chapters": ["监督学习", "无监督学习", "模型评估", "优化方法"],
        "concepts": ["损失函数", "正则化", "过拟合", "聚类", "交叉验证", "梯度", "泛化", "偏差方差"],
        "formulas": ["L=Σ(y-ŷ)^2", "J(θ)=L+λ||θ||", "θ=θ-η∇J", "AUC≈P(正样本得分>负样本)"],
        "qtypes": ["概念辨析", "推导题", "实验分析", "调参题"],
        "points": ["数据泄露", "评价指标", "学习率", "特征缩放"],
    },
    "深度学习": {
        "chapters": ["前馈网络", "卷积网络", "序列模型", "注意力机制"],
        "concepts": ["激活函数", "反向传播", "卷积", "池化", "RNN", "Transformer", "归一化", "正则"],
        "formulas": ["y=σ(Wx+b)", "∂L/∂W", "Attention(Q,K,V)", "BN=(x-μ)/σ"],
        "qtypes": ["概念辨析", "结构设计", "训练诊断", "推导题"],
        "points": ["梯度消失", "参数初始化", "过拟合", "mask机制"],
    },
    "信号与系统": {
        "chapters": ["时域分析", "频域分析", "系统响应", "采样重建"],
        "concepts": ["卷积", "傅里叶", "拉普拉斯", "稳定性", "冲激响应", "采样", "滤波", "带宽"],
        "formulas": ["y(t)=x(t)*h(t)", "X(ω)=∫x(t)e^{-jωt}dt", "H(s)=Y(s)/X(s)", "f_s>2f_max"],
        "qtypes": ["概念辨析", "推导题", "计算题", "系统分析"],
        "points": ["单位一致", "收敛域", "频谱混叠", "初始条件"],
    },
    "电路分析": {
        "chapters": ["基本定律", "等效变换", "暂态分析", "交流稳态"],
        "concepts": ["KCL", "KVL", "戴维南", "诺顿", "一阶电路", "相量", "阻抗", "功率"],
        "formulas": ["ΣI=0", "ΣU=0", "U=IR", "P=UIcosφ"],
        "qtypes": ["概念辨析", "计算题", "等效电路", "综合题"],
        "points": ["参考方向", "复数运算", "初始状态", "单位换算"],
    },
    "大学物理": {
        "chapters": ["力学", "电磁学", "振动波动", "热学"],
        "concepts": ["牛顿定律", "动量", "电场", "磁场", "简谐振动", "干涉", "热力学", "熵"],
        "formulas": ["F=ma", "p=mv", "E=q/r^2", "ΔS=Q/T"],
        "qtypes": ["概念辨析", "计算题", "图像题", "实验分析"],
        "points": ["方向与符号", "守恒条件", "边界条件", "近似假设"],
    },
    "普通化学": {
        "chapters": ["原子结构", "化学键", "热力学", "反应动力学"],
        "concepts": ["轨道", "杂化", "键能", "平衡", "速率", "催化", "酸碱", "氧化还原"],
        "formulas": ["K=Π产物/Π反应物", "ΔG=ΔH-TΔS", "v=k[A]^m[B]^n", "pH=-log[H+]"],
        "qtypes": ["概念辨析", "计算题", "方程配平", "实验题"],
        "points": ["条件控制", "单位量纲", "平衡移动", "电子守恒"],
    },
    "生物化学": {
        "chapters": ["蛋白质", "酶学", "代谢通路", "分子生物学"],
        "concepts": ["一级结构", "构象", "米氏方程", "抑制类型", "糖代谢", "脂代谢", "转录", "翻译"],
        "formulas": ["v=Vmax[S]/(Km+[S])", "ΔG=ΔG°+RTlnQ", "ATP产量估算", "碱基配对规则"],
        "qtypes": ["概念辨析", "机制题", "计算题", "实验设计"],
        "points": ["条件依赖", "速率限制步骤", "定位与隔室", "结构功能关联"],
    },
    "微观经济学": {
        "chapters": ["供需理论", "消费者理论", "生产成本", "市场结构"],
        "concepts": ["弹性", "效用", "预算约束", "边际成本", "均衡", "垄断", "博弈", "福利"],
        "formulas": ["E_d=(ΔQ/Q)/(ΔP/P)", "MR=MC", "π=TR-TC", "CS/PS面积"],
        "qtypes": ["概念辨析", "图像分析", "计算题", "政策分析"],
        "points": ["变量控制", "图像拐点", "比较静态", "假设前提"],
    },
    "宏观经济学": {
        "chapters": ["国民收入", "IS-LM", "通货膨胀", "经济增长"],
        "concepts": ["GDP", "乘数", "均衡", "货币供给", "失业", "菲利普斯曲线", "索洛模型", "政策组合"],
        "formulas": ["Y=C+I+G+NX", "k=1/(1-c)", "MV=PY", "g≈s/ν-δ"],
        "qtypes": ["概念辨析", "模型推导", "图像分析", "政策题"],
        "points": ["口径一致", "短长期区分", "政策时滞", "外生变量"],
    },
    "会计学": {
        "chapters": ["会计要素", "记账规则", "报表分析", "成本核算"],
        "concepts": ["资产", "负债", "权益", "借贷", "收入确认", "现金流", "比率", "成本分配"],
        "formulas": ["资产=负债+所有者权益", "毛利率=毛利/收入", "ROE=净利/权益", "现金流净额=流入-流出"],
        "qtypes": ["概念辨析", "分录题", "报表题", "分析题"],
        "points": ["期间匹配", "权责发生制", "科目方向", "口径统一"],
    },
    "法学基础": {
        "chapters": ["法理学", "民法总则", "合同法", "侵权责任"],
        "concepts": ["法律关系", "主体", "意思表示", "合同成立", "违约", "过错", "因果关系", "救济"],
        "formulas": ["构成要件=事实+规范", "责任=行为+损害+因果", "违约责任类型", "时效规则"],
        "qtypes": ["概念辨析", "案例分析", "条文适用", "论述题"],
        "points": ["构成要件", "举证责任", "免责事由", "法条位阶"],
    },
}


K12_BLUEPRINTS = {
    "初中数学": {
        "chapters": ["有理数", "整式与方程", "一次函数", "反比例函数", "几何基础", "勾股定理", "统计与概率"],
        "concepts": ["定义", "性质", "图像", "解法", "证明", "应用", "易错点", "题型"],
        "formulas": ["y=kx+b", "ax+b=0", "a²+b²=c²", "平均数=总和/个数", "概率=有利/总数"],
        "qtypes": ["概念辨析", "计算题", "证明题", "应用题"],
        "points": ["分类讨论", "图像与代数对应", "边界条件", "单位与符号"],
    },
    "高中数学": {
        "chapters": ["函数与导数", "三角函数", "数列", "立体几何", "解析几何", "概率统计", "不等式"],
        "concepts": ["单调性", "极值", "定义域", "通项", "向量", "轨迹", "分布", "最值"],
        "formulas": ["f'(x)", "sin²x+cos²x=1", "an=a1+(n-1)d", "|AB|", "P(A)=m/n"],
        "qtypes": ["选择题", "填空题", "解答题", "综合压轴"],
        "points": ["函数思想", "数形结合", "化归转化", "分类与讨论"],
    },
    "初中物理": {
        "chapters": ["声现象", "光现象", "力与运动", "压强与浮力", "功和机械能", "电学基础"],
        "concepts": ["折射", "反射", "受力", "平衡", "密度", "功率", "电流", "电压"],
        "formulas": ["v=s/t", "ρ=m/V", "W=Fs", "P=W/t", "I=U/R"],
        "qtypes": ["概念辨析", "实验题", "计算题", "综合题"],
        "points": ["单位换算", "受力分析", "实验误差", "物理意义"],
    },
    "高中物理": {
        "chapters": ["运动学", "牛顿定律", "电场磁场", "电磁感应", "动量与能量", "热学与原子物理"],
        "concepts": ["加速度", "合力", "场强", "感应电动势", "冲量", "守恒", "内能", "核反应"],
        "formulas": ["F=ma", "Ek=mv²/2", "E=F/q", "U=BLv", "p=mv"],
        "qtypes": ["选择题", "实验题", "计算题", "压轴综合"],
        "points": ["过程分析", "守恒定律", "图像读题", "边界建模"],
    },
    "初中化学": {
        "chapters": ["物质构成", "化学反应", "酸碱盐", "金属与溶液", "实验探究"],
        "concepts": ["元素", "化合价", "方程式", "中和", "溶解度", "氧化还原", "离子", "现象"],
        "formulas": ["m=ρV", "w(溶质)=m溶质/m溶液", "n=m/M", "pH=-log[H+]"],
        "qtypes": ["方程配平", "实验题", "推断题", "计算题"],
        "points": ["守恒思想", "实验条件", "现象与本质", "题干信息提取"],
    },
    "高中化学": {
        "chapters": ["化学平衡", "电化学", "有机化学", "物质结构", "化学实验"],
        "concepts": ["平衡移动", "原电池", "官能团", "杂化", "滴定", "速率", "焓变", "选择性"],
        "formulas": ["K=Π产物/Π反应物", "ΔG=ΔH-TΔS", "v=k[A]^m[B]^n", "Q=It"],
        "qtypes": ["机理分析", "实验设计", "推断题", "综合题"],
        "points": ["条件控制", "电子守恒", "结构决定性质", "实验安全"],
    },
    "初中英语": {
        "chapters": ["词汇与短语", "时态语态", "从句基础", "阅读理解", "写作与改错"],
        "concepts": ["词性", "时态", "主谓一致", "定语从句", "语境", "衔接", "改错", "表达"],
        "formulas": ["be+done", "have/has+done", "if+一般现在时", "主句+从句"],
        "qtypes": ["单项选择", "完形填空", "阅读理解", "书面表达"],
        "points": ["固定搭配", "语法一致", "上下文线索", "写作结构"],
    },
    "高中英语": {
        "chapters": ["复杂句法", "阅读与七选五", "语法填空", "应用文写作", "读后续写"],
        "concepts": ["非谓语", "虚拟语气", "逻辑关系", "篇章结构", "语篇衔接", "词块", "语域", "修辞"],
        "formulas": ["to do/doing/done", "if+had done", "therefore/however", "topic sentence"],
        "qtypes": ["阅读题", "语法填空", "写作题", "续写题"],
        "points": ["信息定位", "语义推断", "逻辑连贯", "高频词块"],
    },
    "初中生物": {
        "chapters": ["细胞基础", "生物体结构", "遗传与变异", "生态系统"],
        "concepts": ["细胞器", "组织", "器官", "显隐性", "DNA", "群落", "食物链", "稳态"],
        "formulas": ["遗传概率", "能量流动效率", "增长模型", "实验对照"],
        "qtypes": ["识图题", "实验题", "概念题", "综合题"],
        "points": ["结构功能对应", "对照实验", "变量控制", "图表解读"],
    },
    "高中生物": {
        "chapters": ["细胞代谢", "遗传规律", "进化与生态", "稳态与调节", "生物技术"],
        "concepts": ["酶", "呼吸作用", "减数分裂", "基因表达", "种群", "神经调节", "免疫", "工程"],
        "formulas": ["米氏方程", "遗传分离比", "种群增长", "能量传递"],
        "qtypes": ["实验探究", "遗传计算", "曲线分析", "综合压轴"],
        "points": ["过程拆解", "图像判读", "假设验证", "结论外推"],
    },
    "历史": {
        "chapters": ["古代史", "近代史", "现代史", "史料实证", "时空观念"],
        "concepts": ["制度", "变革", "战争", "思想", "经济", "比较", "因果", "评价"],
        "formulas": ["背景-过程-影响", "史料-论点-论证", "横向比较", "纵向演变"],
        "qtypes": ["材料题", "选择题", "论述题", "比较题"],
        "points": ["时序准确", "概念界定", "史料证据", "多角度评价"],
    },
    "地理": {
        "chapters": ["自然地理", "人文地理", "区域地理", "地理信息与图表"],
        "concepts": ["气候", "地形", "洋流", "人口", "城市", "产业", "区位", "可持续"],
        "formulas": ["区位因素分析", "气候要素", "产业转移", "区域联系"],
        "qtypes": ["图表题", "综合题", "原因分析", "措施题"],
        "points": ["读图能力", "区域比较", "因地制宜", "逻辑链条"],
    },
    "政治": {
        "chapters": ["经济生活", "政治生活", "文化生活", "哲学生活"],
        "concepts": ["价值规律", "市场与政府", "公民权利", "文化自信", "矛盾", "联系", "发展", "实践"],
        "formulas": ["观点-依据-分析", "原理+方法论", "材料映射知识点", "主体责任"],
        "qtypes": ["选择题", "辨析题", "材料分析", "论述题"],
        "points": ["观点准确", "术语规范", "结合材料", "逻辑完整"],
    },
}


PITFALL_TEMPLATES = [
    "忽略前提条件导致结论越界",
    "符号或方向处理错误",
    "把局部结论误当作全局结论",
    "单位/量纲不一致",
    "将近似条件用于非适用场景",
    "步骤跳跃导致推导不完整",
]


PRINCIPLE_TEMPLATES = [
    "先明确对象与约束，再根据定义推导核心关系，最后用边界条件校验结果。",
    "通过不变量与等价变换把复杂问题转化为标准形式，再进行计算或判定。",
    "将系统分解为可验证子问题，分别求解后再做一致性检查。",
    "结合几何/代数双视角验证同一结论，降低单一路径误差风险。",
]


EXAMPLE_TEMPLATES = [
    "已知场景参数，先列出核心关系式，再代入求解并解释每一步含义。",
    "给定题目条件，使用标准流程：识别类型 -> 建立模型 -> 求解 -> 回代验证。",
    "对同一知识点设置两个不同边界样例，比较结果差异并总结可迁移规则。",
    "将复杂题拆成基础子题，逐层合并结果，最终得到完整结论。",
]


ADDITIONAL_DISCIPLINES = [
    "软件工程",
    "人工智能导论",
    "控制工程",
    "通信原理",
    "电子技术",
    "机械原理",
    "材料科学",
    "统计学",
    "金融学",
    "运筹学",
    "心理学",
    "教育学",
    "社会学",
    "市场营销",
    "国际贸易",
]


GENERIC_CHAPTERS = ["基础概念", "核心模型", "方法与应用", "综合分析"]
GENERIC_CONCEPTS = ["定义", "假设", "结构", "判别", "推导", "应用", "边界", "评估"]
GENERIC_FORMULAS = ["核心关系式", "约束条件式", "目标函数", "误差估计式"]
GENERIC_QTYPES = ["概念辨析", "计算题", "步骤题", "综合题"]
GENERIC_POINTS = ["条件判定", "边界处理", "步骤完整性", "易混点识别"]


def expanded_blueprints() -> dict:
    merged = dict(DISCIPLINE_BLUEPRINTS)
    for name in ADDITIONAL_DISCIPLINES:
        if name in merged:
            continue
        merged[name] = {
            "chapters": list(GENERIC_CHAPTERS),
            "concepts": list(GENERIC_CONCEPTS),
            "formulas": list(GENERIC_FORMULAS),
            "qtypes": list(GENERIC_QTYPES),
            "points": list(GENERIC_POINTS),
        }
    return merged


def merged_blueprints(profile: str) -> dict:
    profile = str(profile or "full").strip().lower()
    if profile == "k12":
        return dict(K12_BLUEPRINTS)
    if profile == "full+k12":
        merged = expanded_blueprints()
        merged.update(K12_BLUEPRINTS)
        return merged
    return expanded_blueprints()


def estimate_tokens(text: str) -> int:
    cjk_count = len(re.findall(r"[\u4e00-\u9fff]", text or ""))
    latin_tokens = len(re.findall(r"[A-Za-z0-9_]+", text or ""))
    return cjk_count + latin_tokens


def enforce_token_window(text: str, min_tokens: int = 200, max_tokens: int = 300) -> str:
    fillers = [
        "作答时先确认定义与适用条件，再按步骤推导并进行结果复核。",
        "若出现多路径求解，应比较前提一致性，避免跨条件套用结论。",
        "本知识点常与相邻章节联动，需重点核查边界、单位与符号方向。",
        "检索命中后优先引用公式与步骤，再补充易错点与考点辨析。",
        "建议在结论前增加中间量解释，保证逻辑连续与可验证性。",
    ]
    out = str(text or "").strip()
    idx = 0
    while estimate_tokens(out) < min_tokens:
        out = out + "\n" + fillers[idx % len(fillers)]
        idx += 1

    if estimate_tokens(out) <= max_tokens:
        return out

    lines = [x.strip() for x in out.splitlines() if x.strip()]
    kept = []
    for line in lines:
        candidate = "\n".join(kept + [line])
        if estimate_tokens(candidate) > max_tokens:
            break
        kept.append(line)

    trimmed = "\n".join(kept)
    if estimate_tokens(trimmed) < min_tokens:
        return out
    return trimmed


def make_chapter_specs(profile: str = "full") -> list[ChapterSpec]:
    specs = []
    for discipline, cfg in merged_blueprints(profile).items():
        for chapter in cfg["chapters"]:
            specs.append(
                ChapterSpec(
                    discipline=discipline,
                    chapter=chapter,
                    concept_seeds=list(cfg["concepts"]),
                    formula_templates=list(cfg["formulas"]),
                    question_types=list(cfg["qtypes"]),
                    exam_points=list(cfg["points"]),
                )
            )
    return specs


def make_card(card_id: str, spec: ChapterSpec, idx: int) -> dict:
    concept = spec.concept_seeds[idx % len(spec.concept_seeds)]
    formula = spec.formula_templates[idx % len(spec.formula_templates)]
    qtype = spec.question_types[idx % len(spec.question_types)]
    exam_point = spec.exam_points[idx % len(spec.exam_points)]
    pit1 = PITFALL_TEMPLATES[idx % len(PITFALL_TEMPLATES)]
    pit2 = PITFALL_TEMPLATES[(idx + 2) % len(PITFALL_TEMPLATES)]
    principle = PRINCIPLE_TEMPLATES[idx % len(PRINCIPLE_TEMPLATES)]
    example = EXAMPLE_TEMPLATES[idx % len(EXAMPLE_TEMPLATES)]

    kp_name = f"{spec.chapter}-{concept}-K{idx % 30 + 1}"
    section = f"S{idx % 6 + 1}"

    definition = f"{kp_name}用于描述{spec.discipline}中与“{concept}”相关的核心对象、条件与判定标准。"
    exam_summary = f"高频考点聚焦：{exam_point}；常见题型：{qtype}；作答要点：先判定条件，再给出可复核步骤。"
    solve_steps = [
        "识别题干对象与章节约束，明确已知量与目标量。",
        "调用对应定义与公式，写出标准推导链路。",
        "代入边界条件并检查单位、符号与数量级。",
        "输出结论并给出可复核的中间量说明。",
    ]
    exam_discrimination = f"易与相邻知识点混淆，辨析关键：{exam_point}，强调条件触发与步骤完整性。"

    return {
        "card_id": card_id,
        "discipline": spec.discipline,
        "chapter": spec.chapter,
        "section": section,
        "knowledge_point": kp_name,
        "definition": definition,
        "principle": principle,
        "formula": formula,
        "pitfalls": [pit1, pit2],
        "example": example,
        "question_type": qtype,
        "exam_point": exam_point,
        "exam_summary": exam_summary,
        "solve_steps": solve_steps,
        "exam_discrimination": exam_discrimination,
        "tags": [spec.discipline, spec.chapter, concept, qtype, exam_point],
    }


def card_to_chunks(card: dict) -> list[dict]:
    # 每卡3片，单片保持200~300 token近似区间，保证可检索且不跨章节。
    base_meta = {
        "card_id": card["card_id"],
        "discipline": card["discipline"],
        "chapter": card["chapter"],
        "section": card["section"],
        "knowledge_point": card["knowledge_point"],
        "tags": card["tags"],
    }

    chunk_a_text = (
        f"章节：{card['discipline']} > {card['chapter']} > {card['section']}\n"
        f"知识点：{card['knowledge_point']}\n"
        f"概念定义：{card['definition']}\n"
        f"核心原理：{card['principle']}\n"
        f"关键公式：{card['formula']}\n"
        f"考点辨析：{card['exam_discrimination']}"
    )
    chunk_a = {
        "chunk_id": f"{card['card_id']}_A",
        "chunk_type": "core",
        "text": enforce_token_window(chunk_a_text, min_tokens=200, max_tokens=300),
        **base_meta,
    }

    chunk_b_text = (
        f"章节：{card['discipline']} > {card['chapter']} > {card['section']}\n"
        f"知识点：{card['knowledge_point']}\n"
        f"题型：{card['question_type']}\n"
        f"解题步骤：1){card['solve_steps'][0]} 2){card['solve_steps'][1]} 3){card['solve_steps'][2]} 4){card['solve_steps'][3]}\n"
        f"典型例题：{card['example']}\n"
        f"考点总结：{card['exam_summary']}"
    )
    chunk_b = {
        "chunk_id": f"{card['card_id']}_B",
        "chunk_type": "steps",
        "text": enforce_token_window(chunk_b_text, min_tokens=200, max_tokens=300),
        **base_meta,
    }

    chunk_c_text = (
        f"章节：{card['discipline']} > {card['chapter']} > {card['section']}\n"
        f"知识点：{card['knowledge_point']}\n"
        f"易错点：1){card['pitfalls'][0]}；2){card['pitfalls'][1]}\n"
        f"公式回查：{card['formula']}\n"
        f"题型对位：{card['question_type']}\n"
        f"考点辨析：{card['exam_discrimination']}\n"
        f"结论提示：先判定条件，再输出步骤与答案，避免跨章节迁移。"
    )
    chunk_c = {
        "chunk_id": f"{card['card_id']}_C",
        "chunk_type": "pitfall",
        "text": enforce_token_window(chunk_c_text, min_tokens=200, max_tokens=300),
        **base_meta,
    }
    return [chunk_a, chunk_b, chunk_c]


def write_jsonl(path: str, rows: list[dict]):
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def extract_formula_tokens(text: str) -> list[str]:
    tokens = []
    pattern = re.compile(r"[A-Za-z][A-Za-z0-9_\^\(\)=+\-*/]*")
    for tk in pattern.findall(text or ""):
        if len(tk) >= 2:
            tokens.append(tk)
    return list(dict.fromkeys(tokens))[:6]


def build_light_graph(cards: list[dict], card_vectors, similarity_threshold: float = 0.44, edge_min: int = 1800, edge_max: int = 2500) -> dict:
    nodes = {}
    edges = []

    def add_node(node_id: str, node_type: str, name: str, tags=None):
        if node_id in nodes:
            return
        nodes[node_id] = {
            "id": node_id,
            "type": node_type,
            "name": name,
            "tags": tags or [],
        }

    def add_edge(source: str, target: str, relation: str, weight: float = 1.0, evidence: str = ""):
        edges.append(
            {
                "source": source,
                "target": target,
                "relation": relation,
                "weight": round(float(weight), 4),
                "evidence": evidence,
            }
        )

    chapter_buckets = defaultdict(list)
    pitfall_to_kp = defaultdict(list)
    qtype_to_kp = defaultdict(list)
    point_to_kp = defaultdict(list)
    formula_nodes = []

    for i, card in enumerate(cards):
        chapter_id = f"chapter::{card['discipline']}::{card['chapter']}"
        kp_id = f"kp::{card['card_id']}"
        formula_id = f"formula::{card['card_id']}"
        qtype_id = f"qtype::{card['question_type']}"
        point_id = f"point::{card['exam_point']}"

        add_node(chapter_id, "章节", card["chapter"], tags=[card["discipline"]])
        add_node(kp_id, "知识点", card["knowledge_point"], tags=card["tags"])
        add_node(formula_id, "公式", card["formula"], tags=[card["discipline"], card["chapter"]])
        add_node(qtype_id, "题型", card["question_type"], tags=[card["discipline"]])
        add_node(point_id, "考点", card["exam_point"], tags=[card["discipline"]])

        add_edge(chapter_id, kp_id, "章节从属", evidence="章节归属")

        chapter_buckets[chapter_id].append((i, kp_id))
        qtype_to_kp[qtype_id].append(kp_id)
        point_to_kp[point_id].append((i, kp_id))
        formula_nodes.append((kp_id, formula_id))

        for pit in card["pitfalls"]:
            key = pit[:10]
            pitfall_to_kp[key].append(kp_id)

    # 前置依赖：同章节按生成顺序串联
    for _, seq in chapter_buckets.items():
        seq = sorted(seq, key=lambda x: x[0])
        for j in range(1, len(seq)):
            add_edge(seq[j - 1][1], seq[j][1], "前置依赖", evidence="章节内顺序依赖")

    # 题型同源：同题型知识点做受控连接
    def connect_group_pairs(items, relation, cap, evidence):
        cnt = 0
        for arr in items:
            uniq = list(dict.fromkeys(arr))
            for i in range(len(uniq) - 1):
                if cnt >= cap:
                    return cnt
                add_edge(uniq[i], uniq[i + 1], relation, evidence=evidence)
                cnt += 1
        return cnt

    base_edges = len(edges)
    extra_budget = max(0, min(edge_max, 2200) - base_edges)
    same_source_cap = max(50, int(extra_budget * 0.35))
    confuse_cap = max(50, int(extra_budget * 0.30))
    progress_cap = max(50, int(extra_budget * 0.25))
    formula_cap = max(30, int(extra_budget * 0.10))

    connect_group_pairs(qtype_to_kp.values(), "题型同源", same_source_cap, "同题型迁移")

    # 易混淆关联：共享易错点关键词
    pit_groups = []
    for _, kps in pitfall_to_kp.items():
        if len(kps) >= 2:
            pit_groups.append(kps)
    connect_group_pairs(pit_groups, "易混淆关联", confuse_cap, "共享易错模式")

    # 考点递进：同考点按章节序位递进
    progress_groups = []
    for _, seq in point_to_kp.items():
        seq = [x[1] for x in sorted(seq, key=lambda x: x[0])]
        if len(seq) >= 2:
            progress_groups.append(seq)
    connect_group_pairs(progress_groups, "考点递进", progress_cap, "同考点递进链")

    # 公式节点做轻量挂载，避免孤立
    for kp_id, formula_id in formula_nodes[:formula_cap]:
        add_edge(kp_id, formula_id, "前置依赖", evidence="公式支撑")

    # 相似关系：基于知识点文本向量余弦相似度（受控补齐，不超上限）
    sim = cosine_similarity(card_vectors)
    n = sim.shape[0]
    similarity_cap = max(0, edge_max - len(edges))
    similarity_cnt = 0
    for i in range(n):
        if similarity_cnt >= similarity_cap:
            break
        top = sorted(((j, sim[i, j]) for j in range(n) if j != i), key=lambda x: x[1], reverse=True)[:2]
        for j, s in top:
            if similarity_cnt >= similarity_cap:
                break
            if s >= similarity_threshold:
                add_edge(f"kp::{cards[i]['card_id']}", f"kp::{cards[j]['card_id']}", "易混淆关联", weight=s, evidence="语义近邻")
                similarity_cnt += 1

    # 去重并限制边数量
    dedup = []
    seen = set()
    for e in edges:
        key = (e["source"], e["target"], e["relation"])
        if key in seen:
            continue
        seen.add(key)
        dedup.append(e)
    edges = dedup[:edge_max]

    if len(edges) < edge_min:
        # 最低边数补齐：按题型同源补边
        fill_needed = edge_min - len(edges)
        for arr in qtype_to_kp.values():
            uniq = list(dict.fromkeys(arr))
            for i in range(len(uniq) - 1):
                if fill_needed <= 0:
                    break
                e = {
                    "source": uniq[i],
                    "target": uniq[i + 1],
                    "relation": "题型同源",
                    "weight": 1.0,
                    "evidence": "补齐边数",
                }
                key = (e["source"], e["target"], e["relation"])
                if key in seen:
                    continue
                seen.add(key)
                edges.append(e)
                fill_needed -= 1
            if fill_needed <= 0:
                break

    return {
        "nodes": list(nodes.values()),
        "edges": edges,
    }


def main():
    parser = argparse.ArgumentParser(description="Build professional vector KB (cards + chunks + tfidf + light graph).")
    parser.add_argument("--count", type=int, default=1000, help="知识点实体总数，建议 800~1200，默认1000")
    parser.add_argument("--target-chunks", type=int, default=0, help="目标chunk数量（优先于count），例如120000")
    parser.add_argument("--profile", type=str, default="full+k12", choices=["full", "k12", "full+k12"], help="学科配置档位")
    parser.add_argument("--vectorizer-mode", type=str, default="char", choices=["word", "char"], help="向量化模式，char对中文召回更稳")
    parser.add_argument("--max-features", type=int, default=24000, help="TF-IDF特征上限，数据量大时建议24000~60000")
    parser.add_argument("--seed", type=int, default=20260410, help="随机种子")
    parser.add_argument("--out", type=str, default=DEFAULT_OUT_DIR, help="输出目录")
    args = parser.parse_args()

    random.seed(args.seed)
    os.makedirs(args.out, exist_ok=True)

    specs = make_chapter_specs(profile=args.profile)
    spec_cycle = cycle(specs)

    card_count = max(1, int(args.count))
    if int(args.target_chunks or 0) > 0:
        card_count = max(1, int(math.ceil(int(args.target_chunks) / 3)))

    cards = []
    for idx in range(card_count):
        spec = next(spec_cycle)
        card = make_card(card_id=f"pro-kb-{idx + 1:04d}", spec=spec, idx=idx)
        cards.append(card)

    chunks = []
    for card in cards:
        chunks.extend(card_to_chunks(card))

    # 向量化（面向 RAG 的 chunk 级索引）
    chunk_texts = [c["text"] for c in chunks]
    if args.vectorizer_mode == "char":
        vectorizer = TfidfVectorizer(max_features=max(12000, int(args.max_features or 24000)), analyzer="char", ngram_range=(2, 4), min_df=1)
    else:
        vectorizer = TfidfVectorizer(max_features=max(12000, int(args.max_features or 24000)), ngram_range=(1, 2), min_df=1)
    chunk_matrix = vectorizer.fit_transform(chunk_texts)

    # 知识点级向量（用于轻量图谱相似关系）
    card_texts = [
        f"{c['discipline']} {c['chapter']} {c['knowledge_point']} {c['definition']} {c['principle']} {c['formula']} "
        f"{' '.join(c['pitfalls'])} {c['exam_summary']}"
        for c in cards
    ]
    card_matrix = vectorizer.transform(card_texts)
    light_graph = build_light_graph(cards, card_matrix, similarity_threshold=0.44, edge_min=1800, edge_max=2500)

    cards_path = os.path.join(args.out, "pro_kb_cards.jsonl")
    chunks_path = os.path.join(args.out, "pro_kb_chunks.jsonl")
    vec_path = os.path.join(args.out, "pro_kb_tfidf_vectorizer.pkl")
    mat_path = os.path.join(args.out, "pro_kb_tfidf_matrix.npz")
    graph_path = os.path.join(args.out, "pro_kb_graph.json")
    summary_path = os.path.join(args.out, "pro_kb_summary.json")

    write_jsonl(cards_path, cards)
    write_jsonl(chunks_path, chunks)
    with open(vec_path, "wb") as f:
        pickle.dump(vectorizer, f)
    save_npz(mat_path, chunk_matrix)
    with open(graph_path, "w", encoding="utf-8") as f:
        json.dump(light_graph, f, ensure_ascii=False, indent=2)

    chapter_counter = Counter((c["discipline"], c["chapter"]) for c in cards)
    summary = {
        "generated_at": datetime.now().isoformat(),
        "card_count": len(cards),
        "chunk_count": len(chunks),
        "token_window_target": "200~300 (estimated)",
        "token_window_stats": {
            "min_estimated": min(estimate_tokens(c["text"]) for c in chunks),
            "max_estimated": max(estimate_tokens(c["text"]) for c in chunks),
            "avg_estimated": round(sum(estimate_tokens(c["text"]) for c in chunks) / max(1, len(chunks)), 2),
        },
        "discipline_count": len({c["discipline"] for c in cards}),
        "chapter_count": len(chapter_counter),
        "knowledge_point_entities": len(cards),
        "profile": args.profile,
        "vectorizer_mode": args.vectorizer_mode,
        "graph_nodes": len(light_graph["nodes"]),
        "graph_edges": len(light_graph["edges"]),
        "files": {
            "cards": cards_path,
            "chunks": chunks_path,
            "vectorizer": vec_path,
            "matrix": mat_path,
            "graph": graph_path,
        },
        "entity_types": ["章节", "知识点", "公式", "题型", "考点"],
        "relation_types": ["前置依赖", "章节从属", "题型同源", "易混淆关联", "考点递进"],
    }
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print("Professional KB build completed")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
