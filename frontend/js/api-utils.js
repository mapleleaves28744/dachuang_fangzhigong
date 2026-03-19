(function () {
  const API_BASE_STORAGE_KEY = 'fangzhigong_api_base';

  function normalizeApiBase(base) {
    const value = String(base || '').trim();
    if (!value) return '';
    return value.replace(/\/+$/, '');
  }

  function getApiBaseFromQuery() {
    try {
      const url = new URL(window.location.href);
      return normalizeApiBase(url.searchParams.get('api_base'));
    } catch (error) {
      return '';
    }
  }

  function isLoopbackHost(hostname) {
    const h = String(hostname || '').toLowerCase();
    return h === '127.0.0.1' || h === 'localhost' || h === '::1';
  }

  function inferApiBaseFromLocation() {
    const protocol = window.location.protocol || 'http:';
    const hostname = window.location.hostname || '127.0.0.1';
    const port = window.location.port || '';
    const origin = window.location.origin || `${protocol}//${hostname}`;

    // 若页面本身就由后端(5000)提供，直接同源访问，避免跨域和地址错配。
    if (port === '5000') return normalizeApiBase(origin);

    // 本地静态服务(5501)场景，自动映射到同主机 5000。
    if (port === '5501') return normalizeApiBase(`${protocol}//${hostname}:5000`);

    // 常见远程转发域名模式：5501-xxx => 5000-xxx
    const prefixMatch = hostname.match(/^(\d+)-(.*)$/);
    if (prefixMatch && prefixMatch[2]) {
      return normalizeApiBase(`${protocol}//5000-${prefixMatch[2]}`);
    }

    // 另一种模式：xxx-5501.xxx => xxx-5000.xxx
    const middleMatch = hostname.match(/^(.*?)-(\d+)(\..*)$/);
    if (middleMatch && middleMatch[1] && middleMatch[3]) {
      return normalizeApiBase(`${protocol}//${middleMatch[1]}-5000${middleMatch[3]}`);
    }

    // 默认同源，适用于反向代理把前后端统一到同一域名/端口的部署。
    return normalizeApiBase(origin);
  }

  function defaultApiBaseCandidates() {
    const protocol = window.location.protocol || 'http:';
    const hostname = window.location.hostname || '127.0.0.1';
    const inferred = inferApiBaseFromLocation();
    const list = [inferred];

    // 本地回退。
    if (!isLoopbackHost(hostname)) {
      list.push('http://127.0.0.1:5000');
      list.push('http://localhost:5000');
    }

    // 去重，保持顺序。
    return Array.from(new Set(list.map(normalizeApiBase).filter(Boolean)));
  }

  function getApiBase() {
    const fromQuery = getApiBaseFromQuery();
    if (fromQuery) {
      localStorage.setItem(API_BASE_STORAGE_KEY, fromQuery);
      return fromQuery;
    }

    // 优先使用当前页面推断结果，避免历史 localStorage 污染导致持续“后端离线”。
    const inferred = inferApiBaseFromLocation();
    if (inferred) return inferred;

    const stored = normalizeApiBase(localStorage.getItem(API_BASE_STORAGE_KEY));
    if (stored) return stored;

    const defaults = defaultApiBaseCandidates();
    return defaults[0] || 'http://127.0.0.1:5000';
  }

  function setApiBase(newBase) {
    const normalized = normalizeApiBase(newBase);
    if (!normalized) return '';
    localStorage.setItem(API_BASE_STORAGE_KEY, normalized);
    return normalized;
  }

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
    getApiBase,
    setApiBase,
    defaultApiBaseCandidates,
    mapApiErrorMessage,
    parseApiResponse,
    withSuggestion
  };
})();
