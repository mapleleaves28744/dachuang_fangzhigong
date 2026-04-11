from datetime import datetime

from .topic_guard import filter_learning_topics, is_learning_topic

try:
    import numpy as _np
except Exception:
    _np = None

try:
    from sklearn.cluster import KMeans as _KMeans
except Exception:
    _KMeans = None


class LearningProfileService:
    """学习画像单一实现：负责画像推断、结构生成与持久化。"""

    def __init__(self, kmeans_cls=None, np_module=None):
        self.kmeans_cls = kmeans_cls if kmeans_cls is not None else _KMeans
        self.np_module = np_module if np_module is not None else _np

    @staticmethod
    def parse_datetime_safe(value):
        if not value:
            return None

        if isinstance(value, datetime):
            return value

        text = str(value).strip()
        if not text:
            return None

        # 兼容常见 UTC 后缀与空格分隔格式。
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        text = text.replace(" ", "T")

        try:
            return datetime.fromisoformat(text)
        except Exception:
            return None

    @staticmethod
    def _normalize_user_knowledge_fallback(knowledge):
        if not isinstance(knowledge, dict):
            return {"concepts": [], "relations": [], "deleted_concepts": []}

        concepts = knowledge.get("concepts", [])
        relations = knowledge.get("relations", [])
        deleted_concepts = knowledge.get("deleted_concepts", [])

        if not isinstance(concepts, list):
            concepts = []
        if not isinstance(relations, list):
            relations = []
        if not isinstance(deleted_concepts, list):
            deleted_concepts = []

        knowledge["concepts"] = concepts
        knowledge["relations"] = relations
        knowledge["deleted_concepts"] = deleted_concepts
        return knowledge

    @staticmethod
    def _empty_style_scores():
        return {
            "visual": 0.0,
            "auditory": 0.0,
            "kinesthetic": 0.0,
        }

    @staticmethod
    def _empty_style_features():
        return {
            "image_count": 0,
            "link_count": 0,
            "qa_content_count": 0,
            "note_count": 0,
            "other_count": 0,
            "qa_log_count": 0,
            "concept_count": 0,
        }

    @staticmethod
    def _empty_content_type_counter():
        return {"note": 0, "link": 0, "image": 0, "qa": 0, "other": 0}

    def _infer_learning_style(self, content_type_counter, qa_logs, concept_count):
        visual_score = content_type_counter.get("image", 0) + content_type_counter.get("link", 0)
        auditory_score = max(0, len(qa_logs) // 3)
        kinesthetic_score = content_type_counter.get("qa", 0) + content_type_counter.get("note", 0)
        style_scores = {
            "visual": float(visual_score),
            "auditory": float(auditory_score),
            "kinesthetic": float(kinesthetic_score),
        }

        profile_method = "rule"
        feature_vector = [
            float(content_type_counter.get("image", 0)),
            float(content_type_counter.get("link", 0)),
            float(content_type_counter.get("qa", 0)),
            float(content_type_counter.get("note", 0)),
            float(content_type_counter.get("other", 0)),
            float(len(qa_logs)),
            float(concept_count),
        ]

        learning_style = ""
        if self.kmeans_cls is not None and self.np_module is not None:
            try:
                anchors = self.np_module.array([
                    [8, 6, 1, 1, 1, 2, 4],
                    [1, 2, 6, 2, 1, 8, 4],
                    [1, 1, 5, 7, 1, 4, 6],
                ], dtype=float)
                sample = self.np_module.array([feature_vector], dtype=float)
                data = self.np_module.vstack([anchors, sample])

                norm = data.max(axis=0)
                norm[norm == 0] = 1.0
                data_norm = data / norm

                km = self.kmeans_cls(n_clusters=3, random_state=42, n_init=10)
                labels = km.fit_predict(data_norm)
                centers = km.cluster_centers_

                anchor_map = {
                    labels[0]: "visual",
                    labels[1]: "auditory",
                    labels[2]: "kinesthetic",
                }
                sample_label = int(labels[-1])
                learning_style = anchor_map.get(sample_label, "visual")
                profile_method = "kmeans"

                anchor_centers = {
                    "visual": centers[labels[0]],
                    "auditory": centers[labels[1]],
                    "kinesthetic": centers[labels[2]],
                }
                s = data_norm[-1]
                for name, c in anchor_centers.items():
                    dist = float(self.np_module.linalg.norm(s - c))
                    style_scores[name] = round(1.0 / (1.0 + dist), 3)
            except Exception:
                profile_method = "rule_fallback"

        if not learning_style:
            learning_style = max(style_scores, key=style_scores.get) if sum(style_scores.values()) > 0 else "visual"
            if profile_method == "rule":
                profile_method = "rule_fallback"

        return learning_style, style_scores, profile_method, feature_vector

    def build_profile(
        self,
        user_id,
        get_user_profile,
        set_user_profile,
        load_user_event_list,
        get_user_knowledge,
        normalize_user_knowledge=None,
    ):
        profile = get_user_profile(user_id) or {}

        content_logs = load_user_event_list(user_id, "content")
        qa_logs = load_user_event_list(user_id, "qa")
        normalize_fn = normalize_user_knowledge or self._normalize_user_knowledge_fallback
        knowledge = normalize_fn(get_user_knowledge(user_id))
        concept_items = knowledge.get("concepts", []) if isinstance(knowledge, dict) else []
        blocked_topics = {
            str(item or "").strip()
            for item in (knowledge.get("deleted_concepts", []) if isinstance(knowledge, dict) else [])
            if str(item or "").strip()
        }
        has_learning_signal = bool(content_logs or qa_logs or concept_items)

        if not has_learning_signal:
            profile.update({
                "user_id": user_id,
                "updated_at": datetime.now().isoformat(),
                "learning_style": "",
                "style_scores": self._empty_style_scores(),
                "style_method": "",
                "style_features": self._empty_style_features(),
                "interests": [],
                "best_time_range": "",
                "focus_minutes": None,
                "content_type_counter": self._empty_content_type_counter(),
            })
            set_user_profile(user_id, profile)
            return profile

        content_type_counter = self._empty_content_type_counter()
        hour_counter = {}
        interest_counter = {}

        for item in content_logs:
            content_type = item.get("content_type", "other")
            if content_type not in content_type_counter:
                content_type = "other"
            content_type_counter[content_type] += 1

            ts = self.parse_datetime_safe(item.get("timestamp"))
            if ts:
                hour_counter[ts.hour] = hour_counter.get(ts.hour, 0) + 1

            for topic in filter_learning_topics(item.get("topics"), blocked_topics=blocked_topics):
                interest_counter[topic] = interest_counter.get(topic, 0) + 1

        for item in concept_items:
            concept = str(item.get("concept") or "").strip()
            if concept and concept not in blocked_topics and is_learning_topic(concept):
                interest_counter[concept] = interest_counter.get(concept, 0) + 1

        learning_style, style_scores, profile_method, feature_vector = self._infer_learning_style(
            content_type_counter=content_type_counter,
            qa_logs=qa_logs,
            concept_count=len(concept_items),
        )

        best_hour = max(hour_counter, key=hour_counter.get) if hour_counter else None
        best_time_range = f"{best_hour:02d}:00-{(best_hour + 2) % 24:02d}:00" if best_hour is not None else ""

        top_interests = sorted(interest_counter.items(), key=lambda x: x[1], reverse=True)[:5]
        interests = [k for k, _ in top_interests] if top_interests else []

        profile.update({
            "user_id": user_id,
            "updated_at": datetime.now().isoformat(),
            "learning_style": learning_style,
            "style_scores": style_scores,
            "style_method": profile_method,
            "style_features": {
                "image_count": int(feature_vector[0]),
                "link_count": int(feature_vector[1]),
                "qa_content_count": int(feature_vector[2]),
                "note_count": int(feature_vector[3]),
                "other_count": int(feature_vector[4]),
                "qa_log_count": int(feature_vector[5]),
                "concept_count": int(feature_vector[6]),
            },
            "interests": interests,
            "best_time_range": best_time_range,
            "focus_minutes": 45 if learning_style == "visual" else (35 if learning_style == "auditory" else 50),
            "content_type_counter": content_type_counter,
        })
        set_user_profile(user_id, profile)
        return profile


_default_service = LearningProfileService()


def build_learning_profile(
    user_id,
    get_user_profile,
    set_user_profile,
    load_user_event_list,
    get_user_knowledge,
    normalize_user_knowledge=None,
):
    """统一画像构建入口，供 app.server 等调用。"""
    return _default_service.build_profile(
        user_id=user_id,
        get_user_profile=get_user_profile,
        set_user_profile=set_user_profile,
        load_user_event_list=load_user_event_list,
        get_user_knowledge=get_user_knowledge,
        normalize_user_knowledge=normalize_user_knowledge,
    )


def build_recommendation_context(profile, diagnosis_recent_count):
    """构建推荐接口上下文，统一由画像模块产出。"""
    profile_obj = profile if isinstance(profile, dict) else {}
    return {
        "learning_style": profile_obj.get("learning_style", "visual"),
        "style_method": profile_obj.get("style_method", "rule"),
        "diagnosis_recent_count": int(diagnosis_recent_count or 0),
        "generated_at": datetime.now().isoformat(),
    }


def build_recommendation_runtime(profile):
    """从画像提取推荐运行时参数。"""
    profile_obj = profile if isinstance(profile, dict) else {}
    style = profile_obj.get("learning_style", "visual")
    style_scores = profile_obj.get("style_scores", {}) or {}
    style_method = profile_obj.get("style_method", "rule")
    style_features = profile_obj.get("style_features", {}) or {}

    style_method_weight = 1.08 if style_method == "kmeans" else 1.0
    image_count = float(style_features.get("image_count", 0) or 0)
    link_count = float(style_features.get("link_count", 0) or 0)
    qa_count = float(style_features.get("qa_content_count", 0) or 0)
    note_count = float(style_features.get("note_count", 0) or 0)

    channel_scores = {
        "visual": image_count + link_count * 0.8,
        "auditory": qa_count * 0.7,
        "kinesthetic": qa_count * 0.8 + note_count * 0.9,
    }
    behavior_channel = max(channel_scores, key=channel_scores.get) if sum(channel_scores.values()) > 0 else style

    resource_matrix = {
        ("visual", "visual"): "知识导图+图解微课",
        ("visual", "auditory"): "讲解音频+图文摘要",
        ("visual", "kinesthetic"): "图解示例+互动练习",
        ("auditory", "visual"): "图文摘要+讲解音频",
        ("auditory", "auditory"): "音频讲解",
        ("auditory", "kinesthetic"): "口述讲解+随堂练习",
        ("kinesthetic", "visual"): "示例拆解+图文步骤卡",
        ("kinesthetic", "auditory"): "语音引导+步骤演练",
        ("kinesthetic", "kinesthetic"): "互动练习",
    }

    style_label = {
        "visual": "视觉型",
        "auditory": "听觉型",
        "kinesthetic": "动觉型",
    }

    style_conf = float(style_scores.get(style, 0.6) or 0.6)
    best_time_range = profile_obj.get("best_time_range", "15:00-17:00")

    return {
        "style": style,
        "style_scores": style_scores,
        "style_method": style_method,
        "style_conf": style_conf,
        "style_method_weight": style_method_weight,
        "behavior_channel": behavior_channel,
        "resource_matrix": resource_matrix,
        "style_label": style_label,
        "best_time_range": best_time_range,
    }


def collect_concept_diagnosis_evidence(concept_name, recent_diagnosis, max_examples=2):
    """从最近诊断中提取与概念命中的证据样本。"""
    concept = (concept_name or "").strip().lower()
    if not concept:
        return []

    source = recent_diagnosis if isinstance(recent_diagnosis, list) else []
    matched = []
    for d_item in reversed(source):
        q = str(d_item.get("question") or "")
        ua = str(d_item.get("user_answer") or "")
        ca = str(d_item.get("correct_answer") or "")
        merged = f"{q} {ua} {ca}".lower()
        if concept not in merged:
            continue

        d = d_item.get("diagnosis", {}) or {}
        matched.append({
            "timestamp": d_item.get("timestamp", ""),
            "category": d.get("category", "unknown"),
            "error_type": d.get("error_type", ""),
            "confidence": float(d.get("confidence", 0.0) or 0.0),
            "signals": d.get("signals", [])[:3] if isinstance(d.get("signals"), list) else [],
        })
        if len(matched) >= int(max_examples):
            break

    return matched


def _dominant_recent_category(recent_category_count):
    counts = recent_category_count if isinstance(recent_category_count, dict) else {}
    keys = ["knowledge", "skill", "habit"]
    best_key = "unknown"
    best_count = 0
    for key in keys:
        value = int(counts.get(key, 0) or 0)
        if value > best_count:
            best_key = key
            best_count = value
    return best_key, best_count


def _pick_phrase(options, seed_text):
    if not isinstance(options, list) or not options:
        return ""
    seed = sum(ord(ch) for ch in str(seed_text or ""))
    return options[seed % len(options)]


def build_weak_recommendation_item(concept_name, mastery, runtime, diagnosis_examples, recent_category_count):
    """构建薄弱知识点推荐项。"""
    style = runtime["style"]
    style_label = runtime["style_label"]
    style_method = runtime["style_method"]
    style_conf = runtime["style_conf"]
    style_method_weight = runtime["style_method_weight"]
    behavior_channel = runtime["behavior_channel"]
    resource_matrix = runtime["resource_matrix"]
    best_time_range = runtime["best_time_range"]

    matched_count = len(diagnosis_examples)
    dominant_category, dominant_count = _dominant_recent_category(recent_category_count)
    category_label = {
        "knowledge": "知识建模",
        "skill": "解题步骤",
        "habit": "审题与复核",
        "unknown": "综合巩固",
    }.get(dominant_category, "综合巩固")

    if mastery < 0.35:
        action_mode = "基础回补"
        action_target = "先补概念后做题"
    elif mastery < 0.5:
        action_mode = "结构修复"
        action_target = "分层练习+错因复盘"
    else:
        action_mode = "稳定强化"
        action_target = "变式迁移训练"
    diagnosis_weight = 1.0 + min(0.25, matched_count * 0.08)
    base_priority = (1.0 - mastery) * 100
    personalized_priority = base_priority * (0.65 + style_conf * 0.35) * style_method_weight * diagnosis_weight
    personalized_priority = round(personalized_priority, 2)
    resource_type = resource_matrix.get((style, behavior_channel), "图解微课")
    if dominant_category == "skill":
        resource_type = f"{resource_type}+步骤清单"
    elif dominant_category == "habit":
        resource_type = f"{resource_type}+审题核对卡"

    evidence_brief_parts = [
        f"画像:{style_label.get(style, '综合')}({style_method})",
        f"图谱:掌握度{int(mastery * 100)}%",
    ]
    if matched_count > 0:
        evidence_brief_parts.append(f"诊断:命中{matched_count}条")

    personalized_reason_templates = [
        f"{concept_name} 当前掌握度 {int(mastery * 100)}%，建议采用{style_label.get(style, '综合')}路径做{action_mode}，重点放在{action_target}。",
        f"结合你在{category_label}维度的近期表现，{concept_name} 需要优先安排一轮{action_mode}，先做小步快跑练习再回看概念。",
        f"基于{style_label.get(style, '综合')}偏好与最近诊断信号，建议把 {concept_name} 放到今日高效时段做{action_mode}，目标是{action_target}。",
    ]
    reason = _pick_phrase(
        personalized_reason_templates,
        f"{concept_name}|{style}|{behavior_channel}|{dominant_category}|{matched_count}|{int(mastery*100)}",
    )

    return {
        "concept": concept_name,
        "mastery": mastery,
        "resource_type": resource_type,
        "title": f"{concept_name} - {action_mode}({resource_type})",
        "reason": reason,
        "priority": personalized_priority,
        "recommend_time": best_time_range,
        "strategy_tags": [
            f"style:{style}",
            f"channel:{behavior_channel}",
            f"method:{style_method}",
            f"focus:{dominant_category}",
            f"mode:{action_mode}",
        ],
        "evidence_brief": " | ".join(evidence_brief_parts),
        "source_evidence": {
            "profile": {
                "learning_style": style,
                "style_method": style_method,
                "style_confidence": round(style_conf, 3),
                "behavior_channel": behavior_channel,
            },
            "knowledge_graph": {
                "concept": concept_name,
                "mastery": round(mastery, 3),
                "weak_threshold": 0.6,
            },
            "diagnosis": {
                "matched_count": matched_count,
                "recent_category_count": recent_category_count,
                "dominant_category": dominant_category,
                "dominant_count": dominant_count,
                "examples": diagnosis_examples,
            },
        },
    }


def build_interest_recommendation_item(topic, runtime, recent_category_count):
    """构建兴趣拓展推荐项（无薄弱点时）。"""
    style = runtime["style"]
    style_label = runtime["style_label"]
    style_method = runtime["style_method"]
    style_conf = runtime["style_conf"]
    style_method_weight = runtime["style_method_weight"]
    behavior_channel = runtime["behavior_channel"]
    resource_matrix = runtime["resource_matrix"]
    best_time_range = runtime["best_time_range"]

    resource_type = resource_matrix.get((style, behavior_channel), "图解微课")
    dominant_category, _ = _dominant_recent_category(recent_category_count)
    if dominant_category == "knowledge":
        interest_mode = "概念拓展"
    elif dominant_category == "skill":
        interest_mode = "题型迁移"
    elif dominant_category == "habit":
        interest_mode = "策略优化"
    else:
        interest_mode = "综合提升"

    interest_reason_templates = [
        f"你在该阶段暂无明显薄弱点，建议围绕 {topic} 做{interest_mode}，保持知识网络的广度与连通性。",
        f"按{style_label.get(style, '综合')}学习风格，把 {topic} 作为本周进阶主题，采用“输入+输出”双环节巩固。",
        f"结合近期学习节奏，{topic} 适合用于{interest_mode}训练，帮助你把已有优势迁移到新场景。",
    ]
    reason = _pick_phrase(
        interest_reason_templates,
        f"{topic}|{style}|{behavior_channel}|{dominant_category}|interest",
    )

    return {
        "concept": topic,
        "mastery": 0.75,
        "resource_type": resource_type,
        "title": f"{topic} - {interest_mode}学习包",
        "reason": reason,
        "priority": round(20 * style_method_weight, 2),
        "recommend_time": best_time_range,
        "strategy_tags": [
            f"style:{style}",
            f"channel:{behavior_channel}",
            f"method:{style_method}",
            f"mode:{interest_mode}",
        ],
        "evidence_brief": f"画像:{style_label.get(style, '综合')}({style_method}) | 图谱:暂无薄弱点",
        "source_evidence": {
            "profile": {
                "learning_style": style,
                "style_method": style_method,
                "style_confidence": round(style_conf, 3),
                "behavior_channel": behavior_channel,
            },
            "knowledge_graph": {
                "concept": topic,
                "mastery": None,
                "weak_threshold": 0.6,
            },
            "diagnosis": {
                "matched_count": 0,
                "recent_category_count": recent_category_count,
                "examples": [],
            },
        },
    }


def build_recommendations(
    user_id,
    limit,
    build_learning_profile_fn,
    get_user_knowledge,
    normalize_user_knowledge,
    load_user_event_list,
):
    """推荐主流程单一实现：画像+知识+诊断融合生成推荐。"""
    safe_limit = max(1, min(int(limit or 6), 12))

    profile = build_learning_profile_fn(user_id)
    knowledge = normalize_user_knowledge(get_user_knowledge(user_id))
    diagnosis_logs = load_user_event_list(user_id, "diagnosis")

    recent_diagnosis = diagnosis_logs[-20:] if isinstance(diagnosis_logs, list) else []
    recent_category_count = {"knowledge": 0, "skill": 0, "habit": 0, "unknown": 0}
    for d_item in recent_diagnosis:
        category = (d_item.get("diagnosis", {}).get("category") or "unknown").strip()
        if category not in recent_category_count:
            category = "unknown"
        recent_category_count[category] += 1

    blocked_topics = {
        str(item or "").strip()
        for item in (knowledge.get("deleted_concepts", []) if isinstance(knowledge, dict) else [])
        if str(item or "").strip()
    }
    weak_concepts = sorted(
        [
            c for c in knowledge.get("concepts", [])
            if float(c.get("mastery", 0)) < 0.6
            and str(c.get("concept") or "").strip() not in blocked_topics
            and is_learning_topic(str(c.get("concept") or "").strip())
        ],
        key=lambda x: float(x.get("mastery", 0)),
    )

    runtime = build_recommendation_runtime(profile)
    items = []
    for concept in weak_concepts[:safe_limit]:
        concept_name = concept.get("concept", "未知知识点")
        mastery = float(concept.get("mastery", 0.0))
        diagnosis_examples = collect_concept_diagnosis_evidence(concept_name, recent_diagnosis)
        items.append(
            build_weak_recommendation_item(
                concept_name=concept_name,
                mastery=mastery,
                runtime=runtime,
                diagnosis_examples=diagnosis_examples,
                recent_category_count=recent_category_count,
            )
        )

    if not items:
        interests = profile.get("interests", []) if isinstance(profile, dict) else []
        interests = filter_learning_topics(interests, blocked_topics=blocked_topics, limit=safe_limit)
        for topic in interests[:safe_limit]:
            items.append(
                build_interest_recommendation_item(
                    topic=topic,
                    runtime=runtime,
                    recent_category_count=recent_category_count,
                )
            )

    items.sort(key=lambda x: float(x.get("priority", 0.0)), reverse=True)
    return items[:safe_limit]
