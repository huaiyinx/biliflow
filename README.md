# 🎬 BiliFlow — B站视频笔记全自动化工坊

> 输入一个 B站 UP主 空间链接，全自动产出高质量 Obsidian 学习笔记 + AI 动画分镜。

**在线体验**：[https://bill.19991023.xyz](https://bill.19991023.xyz)

---

## 🧠 项目概述

BiliFlow 是一个**全自动化视频知识管理系统**。解决的核心痛点：**B站有大量优质知识视频，但看视频效率低、笔记难整理、知识难沉淀**。

系统自动完成：拉取 UP主全部视频 → 提取字幕（官方/ASR）→ LLM 重构为结构化笔记 → AI 动画分镜 → Obsidian LiveSync 全设备同步。

## 📝 笔记案例

输入一篇 B站影评视频，Gemini 3.5 Flash 自动重构为：

> **视频**：[最近我疯狂在看的 女性主义逃杀电影！！](https://www.bilibili.com/video/BV1CKV86oE4B)
> **UP主**：我是达芙耶

### ⏱️ 30秒速通
> **核心奥义**：打破"被动受虐"的传统弱者叙事，通过"极速启动"、"拒绝降智"与"特质迁移"，构建掌控全场的反杀爽感。
- **适用场景**：职场逆风局破局、个人品牌定位、高爆发力项目管理、内容创作
- **核心策略**：缩短痛苦铺垫期，用智商与强执行力双核驱动，将自身独特的"无害特质"转化为逆袭的"硬核武器"

### 🧠 核心思维/架构剖析
- **洞察 A：节奏即正义** — 在注意力碎片化时代，漫长的受害者铺垫会迅速消耗受众耐心。顶尖爽感来自**极限压缩受苦时间**，迅速完成"猎物→猎手"的身份转换
- **洞察 B：降维打击源于"技能的跨界迁移"** — 最顶级的反击不是硬碰硬，而是将本不属于战场的技能符号化（如芭蕾舞力量融入格斗），产生极具差异化的核心竞争力
- **洞察 C：生存困境下的"权力关系重组"** — 当环境剧变，原有社会层级瞬间失效，决定新秩序的是生存技能与情绪韧性

### 🎯 实战方法
- **策略一：极限压缩"受害期"** — 跳过心理建设阶段，直接进入解决问题的行动链条
- **策略二：智商与执行力双在线** — 用无可辩驳的数据、完美的交付质量和雷厉风行的执行力堵死对手
- **策略三：构建个人特质的"暴力美学"** — 将"高共情力"转化为"精准洞察对手心理痛点"的谈判利器

### 🎮 场景映射 (Game Dev)
- **现实场景**：职场"空降领导"无理压榨 → 在新项目中利用对方对业务细节的不熟悉，以卓越交付能力夺回话语权
- **跨界灵感**：*《芭蕾猎杀者》关卡设计* — 将芭蕾舞步（Plie、Pirouette、Grand Jeté）设计为 QTE 闪避与致命格斗技，旋转=蓄力，大跳=位移斩杀，实现视觉"暴力美学"

### 🎬 AI 动画生成提示词
- **Scene 1**: `A fierce female ballet dancer in a torn muddy white tutu, performing a flawless high-speed pirouette that transitions into a lethal sweep kick. Set in a dimly lit gothic mansion hallway with shattered glass reflecting moonlight. Dynamic orbiting camera, high contrast cinematic lighting, ultra-detailed 8k.`
- **Scene 2**: `A determined young female corporate employee in a ripped blazer, standing on a rainy wind-swept cliff of a deserted tropical island, looking down with cold confidence at a defeated antagonist. Cinematic low-angle slow pan, photorealistic, gritty survival movie style.`

### 💬 金句摘录
> "可怕的是人心，而最爽的是脑子永远在线、体能爆表，没有任何降智的绝地反杀。"

---

## 🏗️ 系统架构

```
浏览器 → https://bill.19991023.xyz (NPM SSL)
  ├── FastAPI (Python 3.12)
  │   ├── Web 面板 (Jinja2)
  │   ├── REST API (9路由)
  │   ├── Pipeline 引擎
  │   └── APScheduler (6h定时)
  ├── bili CLI (字幕/音频)
  ├── yt-dlp (下载备选)
  ├── SenseVoice (ASR兜底)
  └── Gemini 3.5 Flash (笔记重构)
       ↓
  Obsidian vault → LiveSync → 全设备
```

## 🔧 技术栈

| 层次 | 技术 |
|------|------|
| **前端** | Jinja2 + 原生 JS（自动刷新看板） |
| **后端** | FastAPI (Python 3.12) |
| **数据库** | SQLite + WAL 模式 |
| **容器化** | Docker Compose（单容器） |
| **反代** | Nginx Proxy Manager + Let's Encrypt |
| **B站数据** | bilibili-cli v0.6.2（扫码登录） |
| **语音识别** | SenseVoice (SiliconFlow) |
| **LLM** | Gemini 3.5 Flash (Vertex AI) |
| **调度** | APScheduler |
| **同步** | Obsidian LiveSync (CouchDB) |

## ✨ 核心功能

- **🔐 扫码登录** — Web 界面生成二维码，B站 App 扫码认证，凭据持久化
- **📹 UP主 订阅管理** — 粘贴空间链接一键添加，支持 1000+ 视频，多 UP主 并行
- **🤖 三级字幕降级** — B站官方字幕 → bili CLI 音频下载 → SenseVoice ASR
- **🧠 8模块笔记重构** — 30秒速通 / 核心思维 / 实战方法 / 场景映射 / AI分镜提示词 / 金句摘录 / 原始讲稿 / 元数据
- **📊 实时看板** — 每2秒刷新进度，速度/ETA/最近处理列表，移动端适配
- **♻️ 增量更新+查重** — 6h自动扫描新视频，已完成笔记永不覆盖
- **📱 多设备同步** — Obsidian LiveSync → 手机/笔记本

## 🚀 快速部署

```bash
git clone https://github.com/huaiyinx/biliflow.git /opt/bili-flow
cd /opt/bili-flow
cp .env.example .env && vim .env  # 填入 API Keys
docker compose up -d --build
# 配置 NPM 反代 → bili-flow:8866
# 打开浏览器，扫码登录，添加 UP主
```

## 🛡️ 关键设计决策

| 决策 | 原因 |
|------|------|
| **bili CLI 而非直接调 API** | 手写 Wbi 签名成功率 <30%，CLI 内置扫码+签名 >99% |
| **SQLite 而非 PostgreSQL** | 单用户够用，零配置，备份仅一个文件 |
| **RLock 而非 Lock** | `update()→write()` 嵌套锁在不可重入 Lock 下必死锁 |
| **查重：检查 `## ⏱️ 30秒速通`** | 已完成笔记永不覆盖（踩坑后的保护） |

## 📊 性能

| 指标 | 数值 |
|------|------|
| 单视频处理 | 20-25 秒 |
| 处理速度 | ~3 篇/分钟 |
| 150篇全量 | ~50 分钟 |
| 字幕提取(CLI) | ~2 秒 |
| LLM 重构 | ~16 秒/篇 |

## 🔮 后续

- [ ] 多用户（B站 UID 数据隔离）
- [ ] YouTube 支持
- [ ] Webhook 通知（Telegram/微信）

## 📝 License

MIT

---

**Built by huaiyinx** — 2026
