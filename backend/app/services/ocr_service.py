import base64
import os

import requests

from .document_ingest import extract_text_from_learning_asset


def _get_ocr_config():
    return {
        "provider": os.getenv("OCR_PROVIDER", "mock").lower(),
        "api_key": os.getenv("QWEN_API_KEY", ""),
        "api_url": os.getenv(
            "QWEN_API_URL",
            "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
        ),
        "model_name": os.getenv("QWEN_VL_MODEL_NAME", "qwen-vl-plus"),
        "local_fallback_enabled": str(os.getenv("OCR_LOCAL_FALLBACK_ENABLED", "true")).strip().lower() == "true",
    }


def _build_local_ocr_fallback(file_storage, provider: str, reason_code: str, reason_message: str):
    file_storage.stream.seek(0)
    raw = file_storage.read()
    file_storage.stream.seek(0)

    name = str(getattr(file_storage, "filename", "") or "学习图片").strip() or "学习图片"
    extracted = extract_text_from_learning_asset(
        name=name,
        mime=str(getattr(file_storage, "mimetype", "") or ""),
        content="",
        summary="",
        file_bytes=raw,
    )
    text = str(extracted.get("text") or "").strip()
    if not text:
        stem = os.path.splitext(name)[0].replace("_", " ").replace("-", " ").strip()
        if stem:
            text = f"离线OCR兜底：已接收图片《{name}》。可识别关键词：{stem}。"
        else:
            text = f"离线OCR兜底：已接收图片《{name}》，请在提问框补充题干文本。"

    return {
        "success": True,
        "text": text,
        "ai_used": False,
        "provider": f"{provider}_local_fallback",
        "error_code": reason_code,
        "error_message": reason_message,
        "fallback_used": True,
    }


def extract_text_from_image(file_storage):
    """OCR：从图片中提取文本。支持 mock 与 qwen_vl。"""
    cfg = _get_ocr_config()

    if not file_storage:
        return {
            "success": False,
            "text": "",
            "ai_used": False,
            "provider": cfg["provider"],
            "error_code": "OCR_EMPTY_FILE",
            "error_message": "未提供图片文件",
        }

    if cfg["provider"] != "qwen_vl":
        if cfg["local_fallback_enabled"]:
            return _build_local_ocr_fallback(
                file_storage,
                provider=cfg["provider"],
                reason_code="OCR_PROVIDER_DISABLED",
                reason_message="OCR_PROVIDER 不是 qwen_vl，已回退到本地离线OCR兜底",
            )
        return {
            "success": False,
            "text": "",
            "ai_used": False,
            "provider": cfg["provider"],
            "error_code": "OCR_PROVIDER_DISABLED",
            "error_message": "OCR_PROVIDER 不是 qwen_vl，已禁用真实OCR",
        }

    if not cfg["api_key"]:
        if cfg["local_fallback_enabled"]:
            return _build_local_ocr_fallback(
                file_storage,
                provider="qwen_vl",
                reason_code="OCR_KEY_MISSING",
                reason_message="未配置 QWEN_API_KEY，已回退到本地离线OCR兜底",
            )
        return {
            "success": False,
            "text": "",
            "ai_used": False,
            "provider": "qwen_vl",
            "error_code": "OCR_KEY_MISSING",
            "error_message": "未配置 QWEN_API_KEY",
        }

    file_storage.stream.seek(0)
    raw = file_storage.read()
    file_storage.stream.seek(0)

    try:
        ext = os.path.splitext(file_storage.filename or "")[1].lower()
        mime = "image/png" if ext == ".png" else "image/jpeg"
        b64 = base64.b64encode(raw).decode("utf-8")
        data_url = f"data:{mime};base64,{b64}"

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {cfg['api_key']}",
        }
        payload = {
            "model": cfg["model_name"],
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "请提取图片中的学习相关文字，只返回纯文本。"},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                }
            ],
            "temperature": 0.2,
            "max_tokens": 800,
        }
        resp = requests.post(cfg["api_url"], headers=headers, json=payload, timeout=45)
        resp.raise_for_status()
        data = resp.json()
        text = (data.get("choices", [{}])[0].get("message", {}).get("content", "") or "").strip()
        if not text:
            return {
                "success": False,
                "text": "",
                "ai_used": False,
            "provider": "qwen_vl",
            "error_code": "OCR_EMPTY_RESPONSE",
            "error_message": "OCR返回内容为空",
        }

        return {
            "success": True,
            "text": text,
            "ai_used": True,
            "provider": "qwen_vl",
            "error_code": "",
            "error_message": "",
        }
    except Exception as e:
        if cfg["local_fallback_enabled"]:
            return _build_local_ocr_fallback(
                file_storage,
                provider="qwen_vl",
                reason_code="OCR_UPSTREAM_ERROR",
                reason_message=str(e),
            )
        return {
            "success": False,
            "text": "",
            "ai_used": False,
            "provider": "qwen_vl",
            "error_code": "OCR_UPSTREAM_ERROR",
            "error_message": str(e),
        }
