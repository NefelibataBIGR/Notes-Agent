# Notes Agent（Windows）

本项目是一个本地笔记助手桌面应用，支持：
- 问答：基于本地笔记内容检索并回答（支持 LLM + RAG）
- 修改：自然语言下达修改指令，先预览 diff，再确认写入
- 更新：全量重建、增量同步、文件监听自动更新索引

## 1. 本地开发运行（非用户）

### 环境要求
- Windows 10/11
- Python 3.12+
- PowerShell

### 一键启动
在仓库根目录执行：

```powershell
.\run.ps1
```

脚本会自动：
- 创建并激活 `.venv`
- 安装 `requirements.txt`
- 启动 `python -m app.main`

## 2. 用户使用（安装包 / 便携版）

### 安装包（推荐）
1. 双击 `NotesAgentApp-Setup.exe`
2. 按向导完成安装
3. 可选创建桌面快捷方式

### 便携版（免安装）
1. 解压 `NotesAgentApp-win64.zip`
2. 双击 `Run NotesAgentApp.bat` 或 `NotesAgentApp.exe`
3. 可执行 `create_shortcut.ps1` 创建桌面快捷方式

## 3. 首次使用

1. 打开“设置”页
2. 设置“笔记目录路径”（只索引该目录及其子目录）
3. 设置“索引存放目录”（可自定义，建议选择默认路径）
4. 如需大模型问答：
   - 选择提供商预设
   - 填写 API Key / Chat Model / Embedding Model
5. 保存设置
6. 到“更新”页执行一次“全量重建索引”

## 4. 打包发布

### 构建便携版 zip
```powershell
.\scripts\build_release.ps1 -Version 1.2
```

### 构建安装包 Setup.exe（会先构建便携版）
```powershell
.\scripts\build_setup.ps1 -Version 1.2
```

输出目录：
- 便携版目录：`release\NotesAgentApp\`
- 便携版压缩包：`release\NotesAgentApp-v1.2-win64.zip`
- 安装包：`release\installer\NotesAgentApp-v1.2-Setup.exe`

## 5. 常见问题

### 每次启动都要重建索引吗？
不需要。索引会持久化保存。只有笔记范围或模型配置变化较大时，建议重建。

### 索引文件存在哪里？
在“设置 -> 索引存放目录”指定的目录中，主文件是 `notes_index.json`。

### 修改笔记会自动更新索引吗？
会。通过 App 执行修改后会自动更新对应文件索引。