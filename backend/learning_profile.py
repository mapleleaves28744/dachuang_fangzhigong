from datetime import datetime

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

        content_type_counter = {"note": 0, "link": 0, "image": 0, "qa": 0, "other": 0}
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

            for topic in item.get("topics", []):
                interest_counter[topic] = interest_counter.get(topic, 0) + 1

        concept_items = knowledge.get("concepts", []) if isinstance(knowledge, dict) else []
        for item in concept_items:
            concept = item.get("concept")
            if concept:
                interest_counter[concept] = interest_counter.get(concept, 0) + 1

        learning_style, style_scores, profile_method, feature_vector = self._infer_learning_style(
            content_type_counter=content_type_counter,
            qa_logs=qa_logs,
            concept_count=len(concept_items),
        )

        best_hour = max(hour_counter, key=hour_counter.get) if hour_counter else 15
        best_time_range = f"{best_hour:02d}:00-{(best_hour + 2) % 24:02d}:00"

        top_interests = sorted(interest_counter.items(), key=lambda x: x[1], reverse=True)[:5]
        interests = [k for k, _ in top_interests] if top_interests else ["综合学习"]

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
    """统一画像构建入口，供 app.py 等调用。"""
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
    diagnosis_weight = 1.0 + min(0.25, matched_count * 0.08)
    base_priority = (1.0 - mastery) * 100
    personalized_priority = base_priority * (0.65 + style_conf * 0.35) * style_method_weight * diagnosis_weight
    personalized_priority = round(personalized_priority, 2)
    resource_type = resource_matrix.get((style, behavior_channel), "图解微课")

    evidence_brief_parts = [
        f"画像:{style_label.get(style, '综合')}({style_method})",
        f"图谱:掌握度{int(mastery * 100)}%",
    ]
    if matched_count > 0:
        evidence_brief_parts.append(f"诊断:命中{matched_count}条")

    return {
        "concept": concept_name,
        "mastery": mastery,
        "resource_type": resource_type,
        "title": f"{concept_name} - {resource_type}",
        "reason": f"掌握度仅 {int(mastery * 100)}%，结合{style_label.get(style, '综合')}学习偏好优先巩固",
        "priority": personalized_priority,
        "recommend_time": best_time_range,
        "strategy_tags": [
            f"style:{style}",
            f"channel:{behavior_channel}",
            f"method:{style_method}",
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
    return {
        "concept": topic,
        "mastery": 0.75,
        "resource_type": resource_type,
        "title": f"{topic} - 进阶学习包",
        "reason": f"保持优势，按{style_label.get(style, '综合')}风格进行拓展学习",
        "priority": round(20 * style_method_weight, 2),
        "recommend_time": best_time_range,
        "strategy_tags": [
            f"style:{style}",
            f"channel:{behavior_channel}",
            f"method:{style_method}",
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

    weak_concepts = sorted(
        [c for c in knowledge.get("concepts", []) if float(c.get("mastery", 0)) < 0.6],
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
        interests = profile.get("interests", ["综合学习"]) if isinstance(profile, dict) else ["综合学习"]
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