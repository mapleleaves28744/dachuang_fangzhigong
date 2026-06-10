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
      AUTH_REQUIRED: '登录状态已失效，请重新登录',
      AUTH_INVALID_CREDENTIALS: '账号或密码错误，请重新输入',
      AUTH_USER_EXISTS: '该账号已存在，请直接登录',
      AUTH_DISPLAY_NAME_EXISTS: '该昵称已被使用，请更换一个昵称',
      AUTH_DELETE_FAILED: '删除账户失败，请稍后重试',
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

    if (message) {
      return message;
    }
    if (errorCode && codeMap[errorCode]) {
      return codeMap[errorCode];
    }
    if (errorCode) {
      return `请求失败：${errorCode} (${status})`;
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
      err.status = response.status;
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

  function hasAudioInputDevice() {
    if (
      !navigator.mediaDevices ||
      typeof navigator.mediaDevices.enumerateDevices !== 'function'
    ) {
      return Promise.resolve(null);
    }

    return navigator.mediaDevices.enumerateDevices()
      .then(function (devices) {
        if (!Array.isArray(devices) || devices.length === 0) {
          return null;
        }
        return devices.some(function (device) {
          return device && device.kind === 'audioinput';
        });
      })
      .catch(function () {
        return null;
      });
  }

  function withRecorderSuggestion(prefix, error, suggestion) {
    const fallbackSuggestion = suggestion || '请稍后重试';
    const errorName = String((error && error.name) || '').trim().toLowerCase();
    const rawMessage = String((error && error.message) || '').trim();
    const lowerMessage = rawMessage.toLowerCase();
    let reason = '录音初始化失败';
    let next = fallbackSuggestion;

    if (
      errorName === 'notallowederror' ||
      errorName === 'permissiondeniederror' ||
      errorName === 'securityerror'
    ) {
      reason = '麦克风权限未开启';
      next = '请在浏览器地址栏允许麦克风访问后重试';
    } else if (
      errorName === 'notfounderror' ||
      errorName === 'devicesnotfounderror' ||
      lowerMessage.indexOf('requested device not found') >= 0 ||
      lowerMessage.indexOf('device not found') >= 0 ||
      lowerMessage.indexOf('no audio input device') >= 0
    ) {
      reason = '未检测到可用麦克风设备';
      next = '请连接麦克风，或改用文字记录/上传音频文件';
    } else if (
      errorName === 'notreadableerror' ||
      errorName === 'trackstarterror' ||
      lowerMessage.indexOf('could not start audio source') >= 0 ||
      lowerMessage.indexOf('device in use') >= 0
    ) {
      reason = '麦克风当前不可用，可能被其他应用占用';
      next = '请关闭占用麦克风的应用后重试';
    } else if (
      errorName === 'overconstrainederror' ||
      errorName === 'constraintnotsatisfiederror'
    ) {
      reason = '当前麦克风不满足录音条件';
      next = '请切换默认输入设备或刷新页面后重试';
    } else if (errorName === 'aborterror') {
      reason = '录音被浏览器中断';
      next = '请重新点击开始录音，或刷新页面后再试';
    } else if (/[\u3400-\u9fff]/.test(rawMessage)) {
      reason = rawMessage;
    }

    return `${prefix}：${reason}。建议：${next}`;
  }

  function requestToUrl(resource) {
    if (resource instanceof Request) return resource.url || '';
    return String(resource || '');
  }

  function normalizeRecommendationResourceType(resource) {
    const raw = String(resource || '').trim();
    if (!raw) return '概念梳理';

    const compact = raw.replace(/\s+/g, '');
    if (
      compact.indexOf('复盘') >= 0 ||
      compact.indexOf('巩固') >= 0 ||
      compact.indexOf('审题') >= 0 ||
      compact.indexOf('核对') >= 0
    ) {
      return '复盘巩固';
    }
    if (
      compact.indexOf('流程') >= 0 ||
      compact.indexOf('步骤') >= 0 ||
      compact.indexOf('练习') >= 0 ||
      compact.indexOf('演练') >= 0 ||
      compact.indexOf('工艺') >= 0 ||
      compact.indexOf('修复') >= 0 ||
      compact.indexOf('迁移') >= 0
    ) {
      return '流程拆解';
    }
    if (
      compact.indexOf('拓展') >= 0 ||
      compact.indexOf('专题') >= 0 ||
      compact.indexOf('应用') >= 0 ||
      compact.indexOf('功能性') >= 0 ||
      compact.indexOf('综合提升') >= 0 ||
      compact.indexOf('策略优化') >= 0
    ) {
      return '拓展应用';
    }
    return '概念梳理';
  }

  function isApiRequest(resource) {
    const raw = requestToUrl(resource);
    if (!raw) return false;
    try {
      const parsed = new URL(raw, window.location.origin);
      return parsed.pathname.startsWith('/api/');
    } catch (error) {
      return raw.indexOf('/api/') >= 0;
    }
  }

  function installAuthFetch() {
    if (window.__fangzhigongAuthFetchInstalled || typeof window.fetch !== 'function') return;

    const nativeFetch = window.fetch.bind(window);
    window.__fangzhigongNativeFetch = nativeFetch;

    window.fetch = async function (resource, init) {
      const apiRequest = isApiRequest(resource);
      const authHeader = (window.UserContext && typeof window.UserContext.getAuthHeaderValue === 'function')
        ? window.UserContext.getAuthHeaderValue()
        : '';

      let nextResource = resource;
      let nextInit = init;

      if (apiRequest && authHeader) {
        if (resource instanceof Request) {
          const headers = new Headers(resource.headers || {});
          if (!headers.has('Authorization')) {
            headers.set('Authorization', authHeader);
          }
          nextResource = new Request(resource, {
            headers,
            credentials: (init && init.credentials) || resource.credentials || 'include'
          });
        } else {
          const headers = new Headers((init && init.headers) || {});
          if (!headers.has('Authorization')) {
            headers.set('Authorization', authHeader);
          }
          nextInit = { ...(init || {}), headers, credentials: (init && init.credentials) || 'include' };
        }
      } else if (apiRequest) {
        if (resource instanceof Request) {
          nextResource = new Request(resource, {
            credentials: (init && init.credentials) || resource.credentials || 'include'
          });
        } else {
          nextInit = { ...(init || {}), credentials: (init && init.credentials) || 'include' };
        }
      }

      const response = await nativeFetch(nextResource, nextInit);

      if (
        apiRequest &&
        response &&
        response.status === 401 &&
        window.UserContext &&
        typeof window.UserContext.isAuthenticated === 'function' &&
        window.UserContext.isAuthenticated() &&
        typeof window.UserContext.clearAuth === 'function'
      ) {
        window.UserContext.clearAuth({ reason: 'unauthorized' });
      }

      return response;
    };

    window.__fangzhigongAuthFetchInstalled = true;
  }

  installAuthFetch();

  window.ApiUtils = {
    getApiBase,
    setApiBase,
    defaultApiBaseCandidates,
    mapApiErrorMessage,
    parseApiResponse,
    withSuggestion,
    normalizeRecommendationResourceType,
    hasAudioInputDevice,
    withRecorderSuggestion,
    installAuthFetch
  };
})();
