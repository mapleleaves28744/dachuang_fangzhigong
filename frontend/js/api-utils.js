(function () {
  function mapApiErrorMessage(code, rawMessage, status) {
    const errorCode = String(code || '').trim();
    const message = String(rawMessage || '').trim();
    const codeMap = {
      INVALID_INPUT: '请求参数有误，请检查输入后重试',
      AI_DISABLED: '智能问答未启用，请联系管理员开启 USE_REAL_AI',
      AI_KEY_MISSING: 'AI服务未配置密钥，请联系管理员',
      AI_UPSTREAM_ERROR: 'AI服务暂时不可用，请稍后重试',
      AI_BAD_RESPONSE: 'AI返回格式异常，请稍后重试',
      AI_EMPTY_RESPONSE: 'AI返回为空，请稍后重试',
      OCR_PROVIDER_DISABLED: '图像识别功能未启用，请联系管理员配置 OCR_PROVIDER=qwen_vl',
      OCR_KEY_MISSING: '图像识别未配置密钥，请联系管理员',
      OCR_UPSTREAM_ERROR: '图像识别服务暂时不可用，请稍后重试',
      OCR_EMPTY_RESPONSE: '图像识别未返回内容，请更换图片重试'
    };

    if (errorCode && codeMap[errorCode]) {
      return `${codeMap[errorCode]} (${errorCode})`;
    }
    if (message) {
      return errorCode ? `${message} (${errorCode})` : message;
    }
    return `请求失败(${status})`;
  }

  async function parseApiResponse(response) {
    let data = {};
    try {
      data = await response.json();
    } catch (error) {
      data = {};
    }

    if (!response.ok || data.success === false) {
      const code = data.error_code || '';
      const rawMessage = data.error_message || data.message || '';
      const message = mapApiErrorMessage(code, rawMessage, response.status);
      const err = new Error(message);
      err.code = code;
      err.rawMessage = rawMessage;
      err.payload = data;
      throw err;
    }
    return data;
  }

  function withSuggestion(prefix, error, suggestion) {
    const reason = (error && error.message) ? error.message : '未知错误';
    const next = suggestion || '请稍后重试';
    return `${prefix}：${reason}。建议：${next}`;
  }

  window.ApiUtils = {
    mapApiErrorMessage,
    parseApiResponse,
    withSuggestion
  };
})();
