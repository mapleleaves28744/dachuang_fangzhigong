import base64
import os

import requests


def _get_ocr_config():
    return {
        "provider": os.getenv("OCR_PROVIDER", "mock").lower(),
        "api_key": os.getenv("QWEN_API_KEY", ""),
        "api_url": os.getenv(
            "QWEN_API_URL",
            "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
        ),
        "model_name": os.getenv("QWEN_VL_MODEL_NAME", "qwen-vl-plus"),
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
        return {
            "success": False,
            "text": "",
            "ai_used": False,
            "provider": cfg["provider"],
            "error_code": "OCR_PROVIDER_DISABLED",
            "error_message": "OCR_PROVIDER 不是 qwen_vl，已禁用真实OCR",
        }

    if not cfg["api_key"]:
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
        return {
            "success": False,
            "text": "",
            "ai_used": False,
            "provider": "qwen_vl",
            "error_code": "OCR_UPSTREAM_ERROR",
            "error_message": str(e),
        }
