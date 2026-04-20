# Notes Agent（Windows 用户版）

这是一个本地笔记助手 App，支持：
- 问答：基于你的笔记内容检索并回答（支持 LLM + RAG）
- 修改：自然语言下达修改指令，先预览 diff，再确认写入
- 更新：全量重建、增量同步、文件监听自动更新索引

## 1. 推荐安装方式（Setup.exe）

### 安装
1. 双击 `NotesAgentApp-Setup.exe`
2. 按安装向导点击“下一步”完成安装
3. 可选勾选桌面快捷方式

### 启动
- 开始菜单：`NotesAgentApp`
- 或桌面快捷方式启动

### 卸载
- Windows 设置 -> 应用 -> 已安装应用 -> `NotesAgentApp` -> 卸载

## 2. 便携版（免安装）

如果你用的是 zip 版：
1. 解压 `NotesAgentApp-win64.zip`
2. 双击 `Run NotesAgentApp.bat` 或 `NotesAgentApp.exe`
3. 可执行 `create_shortcut.ps1` 创建桌面快捷方式

## 3. 首次使用（很重要）

1. 打开“设置”页
2. 设置“笔记目录路径”（只索引该目录及其子目录）
3. 设置“索引存放目录”（默认在 `data` 文件夹，可自定义）
4. 如需大模型问答：
   - 选择提供商预设
   - 填写 API Key / Chat Model / Embedding Model
5. 保存设置
6. 到“更新”页执行一次“全量重建索引”

## 4. 常见问题

### 问：每次启动都要重建索引吗？
答：不需要。索引会持久化保存。只有笔记范围/模型配置变化较大时，建议重建。

### 问：索引文件存在哪里？
答：在“设置 -> 索引存放目录”指定的目录中，主文件是 `notes_index.json`。

### 问：修改笔记会自动更新索引吗？
答：会。通过 App 执行修改后会自动更新对应文件索引。

## 5. 功能提示

- 修改支持自然语言，会先给“修改意图确认 + Diff 预览”
- 备份策略支持三态：总是备份 / 每次询问 / 从不备份
- 回答支持 Markdown 渲染与来源片段展示

## 6. 开发者构建（可选）

### 构建便携版 zip
```powershell
cd e:\my_notes\notes_agent_app
.\scripts\build_release.ps1
```

### 构建安装包 Setup.exe
```powershell
cd e:\my_notes\notes_agent_app
.\scripts\build_setup.ps1
```

输出目录：
- 便携版：`release\NotesAgentApp\` 与 `release\NotesAgentApp-win64.zip`
- 安装包：`release\installer\NotesAgentApp-Setup.exe`
