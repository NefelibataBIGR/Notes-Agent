from __future__ import annotations

## 这是Python的一个特殊导入，用于启用延迟类型注解：
# 允许在类型提示中使用尚未定义的类名
# 将类型注解作为字符串处理，而不是立即求值
# 解决循环导入问题
# Python 3.7+ 默认行为，但显式导入可确保向后兼容

from app.ui import run_ui


if __name__ == "__main__":
    raise SystemExit(run_ui())

## raise SystemExit(run_ui())：
# 调用 run_ui()函数（启动用户界面）
# 将其返回值作为退出码
# 引发 SystemExit异常来结束程序

## 当用户运行此脚本时：
# 初始化UI系统
# 显示用户界面
# 用户与UI交互
# 关闭UI时返回退出码
# 程序以该退出码结束

## 这是一个标准的GUI应用程序入口模式，适用于PyQt、Tkinter等UI框架。