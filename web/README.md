# `web/` —— 演示界面（React ＋ Tailwind CSS ＋ shadcn/ui）

> **谁管这儿**：**前端 / 界面侧**。契约与纪律在 **`docs/local/roles/ui-agent.md`**，
> 需求在 **`docs/local/交流区/前端ui设计.md`**。
> ⚠️ 本文件只写**怎么跑**与**东西在哪**；⛔ 不抄接口清单 / 字段表 / 端口号（那些**去取**）。

---

## 跑起来（两步）

```bash
# ① 后端（项目根；python 用本项目的 conda 环境，具体路径见项目本地说明）
python scripts/start_demo.py --no-browser

# ② 前端（本目录）
npm install
npm run dev          # → http://127.0.0.1:<dev 端口>
```

⭐ **端口不在这儿写死** —— `vite.config.ts` **运行时去读** `scripts/demo_ports.py`（单一来源）。
改端口改那个文件，不用动本目录。

**首次用要先填 Token**：打开右上角「连接设置」→ Token。
（本地想免手输：把 `.env.example` 复制成 `.env.local` 并填 `VITE_DEMO_TOKEN`。）

---

## 布局与两个页签

⭐ **左右分栏**（照 `参考资料/RAG 项目前端 UIUX 重构指南_20261010.md` §二-1）：
**左 60% 对话区 · 右 40% 洞察面板（可折叠）**。

| 页签 | 内容 | 数据从哪来 |
|---|---|---|
| **问答 ＋ 链路透视** | 左：对话气泡（Markdown）｜ 右：耗时**环形图** · 判定三态 · 候选池 vs 精排（含提权/下移）· 引用校验 | `POST /demo/ask` **一次请求同时喂两边** |
| **评测看板** | 主指标 `AllHit@3` ＋ 告警位 ｜ `R@K` **对照矩阵**（每格一条进度条）｜ `per_kind` 明细 ｜ 原始产物 | `logs/*.json`（由 dev server 只读暴露成 `/api/eval/*`） |

深链：`http://127.0.0.1:5173/#eval` 直接开看板。

---

## ⚠️ 四条「跟直觉不一样」的地方

1. **后端没开 CORS** ⇒ 前端一律调**同源** `/api/*`，由 `vite.config.ts` 的 `server.proxy` 转发。
   ⛔ 别去关浏览器安全策略。
2. **后端没有 SSE**（`2.0-56` 未开工）⇒ 请求期间只显示**「进行中 ＋ 已等待」**，
   ⛔ **不演**「正在检索 → 正在精排」那种逐阶段动画 —— 那些话目前**没有真实来源**。
   日后 SSE 到位 → **换 `src/lib/trace-stream.ts` 的实现，组件一行不改**。
3. **评测看板的数据是 dev server 给的** ⇒ 只在 `npm run dev` 下有效。
   `npm run build` 的静态产物里没有这层；要它就得**后端开一个只读端点**（归开发侧，另议）。
4. **得分条的配色没照 UIUX 指南的阈值来** —— 指南写「`>0.8` 绿 / `0.5~0.8` 黄 / `<0.5` 灰」，
   那套假设分数是 0~1 的相似度。**实测不是**：粗排（RRF）分在 **0.01~0.03** 量级，
   精排分是 cross-encoder 的 **0.46~0.61** 那种区间。
   照搬阈值 → **满屏都是灰的**，等于用颜色撒了个谎。
   ⇒ 改成：**条长 = 本次结果内相对位置 ＋ 颜色 = 名次**，**原始分照原样显示**
   （见 `src/components/ScoreBar.tsx` 顶部）。

---

## 目录

```
src/
  lib/            取数层（⛔ 不在这里做解释，只做取数）
    api.ts            HTTP 客户端（只读）
    config.ts         后端地址 ＋ token（token ⛔ 不进源码）
    ask-config.ts     知识库 ＋ 混合/精排开关
    eval.ts           评测产物取数（含 AllHit@3 的口径镜像）
    theme.ts          深/浅色
    trace-stream.ts   ⭐「阶段事件」可订阅事件源（非流式替身）
    use-ask-session.ts 一次问答的会话状态
  components/     界面
    ui/               shadcn 组件（生成物，按需改）
    ChatWindow.tsx · InspectorPanel.tsx · EvalDashboard.tsx
    SettingsPanel.tsx · MarkdownBody.tsx · BriefCard.tsx · ScoreBar.tsx
  App.tsx         外壳（顶栏 ＋ 设置 ＋ 两个页签）
```

---

## 依赖

**跑起来需要**（`dependencies`，9 个）：
`react` · `react-dom` · `radix-ui` · `lucide-react` · `cn` · `class-variance-authority` ·
`react-markdown` · `remark-gfm` · `@fontsource-variable/inter`

**只在构建期用**（`devDependencies`）：`vite` · `typescript` · `tailwindcss` ·
`@tailwindcss/vite` · `tw-animate-css` · `shadcn`(CLI/CSS) · `oxlint` 等

<details>
<summary>当初是怎么装出来的（照着跑能复现）</summary>

```bash
npm create vite@latest web -- --template react-ts
npm install tailwindcss @tailwindcss/vite
npx shadcn@latest init -b radix --no-monorepo
npx shadcn@latest add card input label badge separator tabs scroll-area progress \
  tooltip collapsible select table switch alert -y
npm install react-markdown remark-gfm @fontsource-variable/inter
```
</details>

⚠️ `node_modules` 落盘约 **237 MB / 369 个包**（主要是 radix）。
⭐ 图表是**手写 SVG ＋ 进度条**，⛔ 没引图表库 ——
`参考资料/…UIUX 重构指南` §三-4 要的就是"分数列加一个进度条"，
为此拉一个几百 kB 的 `recharts` 不划算（本项目有「依赖先量」的规矩）。
看板仍**懒加载**（它是另一个页签）。

---

## 已知问题

- `npm audit` 报 **7 个 high**，全在 `shadcn` CLI 的**传递依赖**里（`fast-glob` / `ts-morph`
  的版本区间）—— ⛔ **不进浏览器产物**，是构建工具链的事。已核过，`npm audit fix`
  （非 `--force`）解不掉。要不要 `--force`（有破坏性）**没动，等定**。
