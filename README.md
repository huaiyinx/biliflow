# 🎬 BiliFlow — B站视频笔记全自动化工坊

> 输入一个 B站 UP主 空间链接，全自动产出高质量 Obsidian 学习笔记 + AI 动画分镜。

**在线体验**：[https://bill.19991023.xyz](https://bill.19991023.xyz)

---

## 🧠 项目概述

BiliFlow 是一个**全自动化视频知识管理系统**，专门为深度学习者设计。它解决了一个核心痛点：**B站有大量优质知识视频，但看视频效率低、笔记难整理、知识难沉淀**。

系统会自动完成：
1. 拉取 UP主全部视频列表
2. 提取视频字幕（B站官方字幕 / AI 语音转写）
3. 用 LLM 重构为结构化 Obsidian 笔记
4. 为每个核心场景设计 AI 视频分镜提示词
5. 通过 Obsidian LiveSync 同步到全设备

## 📝 笔记案例

下面是一篇真实输出——输入 B站影评视频，Gemini 3.5 Flash 自动重构为 6 模块结构化笔记：

> **视频**：[最近我疯狂在看的 女性主义逃杀电影！！](https://www.bilibili.com/video/BV1CKV86oE4B)
> **UP主**：我是达芙耶

### ⏱️ 30秒速通 (TL;DR)
> **核心奥义**：打破"被动受虐"的传统弱者叙事，通过"极速启动"、"拒绝降智"与"特质迁移"，构建掌控全场的反杀爽感。
- **适用场景**：职场逆风局破局、个人品牌定位、高爆发力项目管理、内容创作（叙事节奏重塑）。
- **核心策略**：缩短痛苦铺垫期，用智商与强执行力双核驱动，将自身独特的"无害特质"转化为逆袭的"硬核武器"。

### 🧠 核心思维/架构剖析
- **洞察 A：节奏即正义，延迟满足正在失效** — 在注意力碎片化时代，漫长的受害者铺垫会迅速消耗受众耐心。顶尖的爽感来自于**极限压缩受苦时间（10分钟法则）**，迅速完成从"猎物"到"猎手"的身份转换。
- **洞察 B：降维打击源于"技能的跨界迁移"** — 最顶级的反击不是硬碰硬，而是将本不属于战场的技能符号化（如《芭蕾杀鸡》中将芭蕾舞的力量、体态融入格斗）。这种"风马牛不相及"的融合，能产生极具差异化的核心竞争力。
- **洞察 C：生存困境下的"权力关系重组"** — 当环境发生剧变（如荒岛求生、项目暴雷），原有的社会层级（如CEO与基层员工）会瞬间失效。决定新秩序的是生存技能与情绪韧性，这是弱者实现结构性反杀的最佳时机。

### 🎯 实战方法 (或关键逻辑还原)
- **策略一：极限压缩"受害期"，快速切入反击态势** — 在面临职场打压或项目危机时，不抱怨、不等待。立即启动"反杀"预案，跳过"凭什么是我受苦"的心理建设阶段，直接进入解决问题的行动链条。
- **策略二：智商与执行力双在线（拒绝"降智"行为）** — 绝不寄希望于对手的失误。反击方案必须逻辑自洽，行动方案必须敏捷高效。用无可辩驳的数据、完美的交付质量和雷厉风行的执行力，堵死对方所有设局的可能。
- **策略三：构建个人特质的"暴力美学"** — 盘点你身上那些看似温和、与竞争无关的特质（如：极度细心、高共情力、艺术审美），将其重构为竞争武器。例如，将"高共情力"转化为"精准洞察对手心理痛点"的谈判利器。

### 🎮 场景映射 (Game Dev & Real Life Bridge)
- **现实场景**：在职场中遭遇"空降领导"或"强势甲方"的无理压榨（进入"逃杀"困境）。破解打法：模仿荒岛反转——在新项目或陌生领域（即"荒岛"）中，利用对方对业务细节的不熟悉，以卓越的专业技能和生存（交付）能力夺回话语权，实现职场权力关系的悄然逆转。
- **跨界灵感（游戏开发映射）**：*《芭蕾猎杀者 (Ballet Carnage)》关卡与战斗系统设计*：打破《逃生》等传统恐怖游戏"只能躲避"的憋屈感。将芭蕾舞步（Plie折叠、Pirouette旋转、Grand Jeté大跳）设计为QTE闪避与致命格斗技。旋转代表蓄力，大跳代表位移斩杀，将优雅的艺术姿态转化为高额伤害的判定区，实现视觉上的"暴力美学"。

### 🎬 AI 动画生成提示词 (Prompt for Sora/Runway/Kling)
- **Scene 1**: `A fierce female ballet dancer in a torn and muddy white tutu, performing a flawless, high-speed pirouette that transitions into a lethal sweep kick against a shadowed attacker. Set in a dimly lit, gothic mansion hallway with shattered glass reflecting moonlight. Dynamic orbiting camera movement, high contrast cinematic lighting, action movie aesthetic, ultra-detailed 8k.`
- **Scene 2**: `A determined young female corporate employee in a ripped blazer, standing on a rainy, wind-swept cliff of a deserted tropical island, looking down with cold confidence at a defeated antagonist. Cinematic low-angle slow pan, intense rain effects, photorealistic, gritty survival movie style, dramatic volumetric lighting.`
- **Scene 3**: `An athletic and highly alert woman sprinting through a neon-lit narrow alleyway, fluidly sliding under an obstacle and throwing an improvised glass bottle weapon with precision. Handheld tracking shot closely following her movements, motion blur, cyberpunk thriller aesthetic, moody blue and magenta color grading.`

### 💬 金句摘录
- "可怕的是人心，而最爽的是脑子永远在线、体能爆表，没有任何降智的绝地反杀。"

---

## 🏗️ 系统架构

```
┌─────────────────────────────────────────────────────┐
│                    浏览器                            │
│           https://bill.19991023.xyz                  │
└─────────────────┬───────────────────────────────────┘
                  │ HTTPS (Nginx Proxy Manager)
┌─────────────────▼───────────────────────────────────┐
│              FastAPI (Python 3.12)                   │
│  ┌──────────┬──────────┬──────────┬──────────────┐  │
│  │ Web 面板 │ REST API │Pipeline  │ APScheduler  │  │
│  │(Jinja2)  │(9路由)   │  引擎    │  (6h定时)    │  │
│  └──────────┴──────────┴──────────┴──────────────┘  │
└────┬──────────┬──────────┬──────────────────────────┘
     │          │          │
     ▼          ▼          ▼
┌─────────┐ ┌───────┐ ┌──────────────┐
│bili CLI │ │yt-dlp │ │Gemini 3.5    │
│(字幕/音频)│ │(下载) │ │Flash (重构)  │
└─────────┘ └───┬───┘ └──────┬───────┘
                │             │
                ▼             │
         ┌──────────┐        │
         │SenseVoice│        │
         │(ASR备选) │        │
         └──────────┘        │
                             ▼
              ┌──────────────────────────┐
              │  /data/obsidian-vault/   │
              │     10-B站笔记/           │
              └──────────┬───────────────┘
                         │ LiveSync
                         ▼
              ┌──────────────────────┐
              │  Obsidian (全设备)    │
              └──────────────────────┘
```

## 🔧 技术栈

| 层次 | 技术 | 用途 |
|------|------|------|
| **前端** | Jinja2 + 原生 JS | 管理面板、实时看板 |
| **后端** | FastAPI (Python 3.12) | REST API、路由、模板 |
| **数据库** | SQLite + WAL 模式 | UP主/视频/日志持久化 |
| **容器化** | Docker Compose | 单容器部署 |
| **反向代理** | Nginx Proxy Manager | SSL、域名管理 |
| **B站数据** | bilibili-cli v0.6.2 | 扫码登录、字幕提取、音频下载 |
| **语音识别** | SenseVoice (SiliconFlow) | 无字幕视频的 ASR 备选 |
| **LLM** | Gemini 3.5 Flash (Vertex AI) | 笔记内容重构 |
| **调度** | APScheduler | 每6小时自动检查 UP主更新 |
| **同步** | Obsidian LiveSync (CouchDB) | 全设备笔记同步 |

## ✨ 核心功能

### 1. 🔐 扫码登录
- Web 界面生成 B站 登录二维码
- B站 App 扫码完成认证
- 凭据持久化，重启不丢失
- 右上角显示用户头像、昵称、等级

### 2. 📹 UP主 订阅管理
- 粘贴空间链接，一键添加
- 自动拉取全部视频列表（支持1000+视频）
- 批量生成 Dataview 兼容的壳笔记
- 支持多个 UP主 同时管理

### 3. 🤖 智能字幕提取（三级降级）
```
B站官方字幕 ──→ bili CLI 音频下载 ──→ SenseVoice ASR
   (优先)          (备选)              (兜底)
```

### 4. 🧠 LLM 笔记重构
每篇视频笔记包含 **8 个模块**：

| 模块 | 内容 |
|------|------|
| ⏱️ 30秒速通 | 一句话概括 + 适用场景 + 核心策略 |
| 🧠 核心思维/架构剖析 | 底层逻辑拆解 |
| 🎯 实战方法 | 可操作的具体策略 |
| 🎮 场景映射 | 现实 + 游戏开发跨界脑洞 |
| 🎬 AI 动画生成提示词 | 2-3个纯英文 Sora/Runway 分镜 |
| 💬 金句摘录 | 原文最精辟的话 |
| 📜 原始讲稿 | 完整时间戳备份 |
| 🏷️ 元数据 | Dataview 兼容的 frontmatter |

### 5. 📊 实时看板
- 每 2 秒自动刷新进度
- 成功/失败/SenseVoice备选 分类统计
- 处理速度、预计剩余时间
- 最近处理列表
- 移动端响应式适配

### 6. ♻️ 增量更新 & 查重
- 每 6 小时自动扫描新视频
- 已完成笔记（8模块齐全）永不覆盖
- 失败视频单独管理，一键重试

### 7. 📱 多设备同步
- 笔记输出到 Obsidian vault
- LiveSync 自动同步到手机/笔记本
- Dataview 插件可直接查询、筛选

## 📁 项目结构

```
/opt/bili-flow/
├── docker-compose.yml        # Docker 编排
├── Dockerfile                # 镜像构建
├── .env.example              # 环境变量模板
├── requirements.txt          # Python 依赖
├── README.md
├── app/
│   ├── main.py               # FastAPI 主应用 (9 API路由 + 4页面)
│   ├── pipeline.py           # 核心流水线引擎
│   ├── bili_api.py           # B站 CLI 封装
│   ├── scheduler.py          # 定时任务 & MOC管理
│   ├── db.py                 # SQLite 操作
│   ├── config.py             # 配置管理
│   └── templates/
│       ├── base.html          # 基础布局 + 用户信息
│       ├── index.html         # 总控面板 (自动刷新)
│       ├── add.html           # 添加 UP主
│       ├── login.html         # 扫码登录
│       ├── project.html       # UP主详情
│       └── dashboard.html     # 实时进度看板
├── data/                     # SQLite 数据库 (gitignore)
└── projects/                 # 临时工作目录 (gitignore)
```

## 🚀 快速部署

### 前置条件
- Docker + Docker Compose
- 域名 + Nginx Proxy Manager（或其他反代）
- B站账号
- SiliconFlow API Key（SenseVoice）
- Gemini API Key（或 NewAPI 代理）

### 部署步骤

```bash
# 1. 克隆项目
git clone https://github.com/huaiyinx/biliflow.git /opt/bili-flow
cd /opt/bili-flow

# 2. 配置环境变量
cp .env.example .env
vim .env  # 填入 API Keys

# 3. 启动
docker compose up -d --build

# 4. 配置 NPM 反代: bill.yourdomain.com → bili-flow:8866

# 5. 打开浏览器，扫码登录 B站
# 6. 添加 UP主，开始自动处理
```

## 🛡️ 关键设计决策

### 为什么用 bili CLI 而不是直接调 B站 API？
B站 Web API 有严格的 Wbi 签名和风控机制。bili CLI 内置扫码登录和签名处理，稳定性远高于手写 API 调用。实测手写 Wbi 签名的请求成功率不到 30%，换 CLI 后接近 100%。

### 为什么是 SQLite 而不是 PostgreSQL？
单用户场景下，SQLite 的 WAL 模式完全够用，且零配置、零维护。数据库文件包含在 Docker volume 中，备份只需复制一个文件。

### 查重保护机制
`create_shell_notes_batch` 写入前会检查文件是否已包含 `## ⏱️ 30秒速通` 标记。已完成的笔记永远不被覆盖——这是踩过坑后加的保护。

### RLock 死锁修复
初期版本使用 `threading.Lock()` 导致 ProgressTracker 在批量处理时死锁。`update()` → `write()` 的嵌套锁在不可重入 Lock 下必然卡死，改为 `RLock()` 解决。

## 📊 性能指标

| 指标 | 数值 |
|------|------|
| 单视频处理时间 | 20-25 秒 |
| 处理速度 | ~3 篇/分钟 |
| 150篇 UP主 全量处理 | ~50 分钟 |
| 视频拉取（1000篇） | ~15 秒 |
| LLM 响应时间 | ~16 秒/篇 |
| 字幕提取（CLI） | ~2 秒 |
| 音频+ASR（备选） | ~30-60 秒 |

## 🔮 后续规划

- [ ] 多用户支持（基于 B站 UID 数据隔离）
- [ ] YouTube 视频支持
- [ ] 自定义笔记模板
- [ ] Webhook 通知（Telegram/微信）
- [ ] 全文搜索
- [ ] 笔记导出（PDF/Markdown 打包）

## 📝 License

MIT

---

**Built with ❤️ by huaiyinx** — 2026
