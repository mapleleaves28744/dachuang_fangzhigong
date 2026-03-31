# Frontend Structure

前端目前按“共享能力”和“页面逻辑”分层，入口页面仍保留在 `frontend/` 根目录，方便继续直接用静态服务器或后端托管访问。

目录约定：

- `frontend/*.html`：页面入口，只放页面结构和少量页面级内联代码
- `frontend/assets/css/shared/`：跨页面复用的样式
- `frontend/assets/css/pages/`：页面私有样式
- `frontend/assets/js/shared/`：用户上下文、API 工具、登录 UI、页面外壳等共享脚本
- `frontend/assets/js/pages/`：具体页面逻辑

维护建议：

- 新增页面时，优先新增 `frontend/<page>.html`，并把脚本放到 `assets/js/pages/`
- 只要是多个页面都会用到的能力，都优先收进 `assets/js/shared/`
- 避免继续新增 `style.css`、`main.js` 这类泛名文件，尽量按页面或能力命名
