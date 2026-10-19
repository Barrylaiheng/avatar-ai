# 一次性架构分析 Summary

## 文件与子包统计
- .py 文件总数：66
- 顶级子包数：9（root, ui, bridges, engine, rag, database, config, security, utils）
- 内部 import 语句数：125
- 子包间依赖边数：17

## 信号统计
- pyqtSignal 定义：102 个
- emit 调用：80 处
- connect 调用：150 处

## 架构健康度
- 子包级循环依赖：✅ 0
- 跨层异味：✅ 0

详细产物：见同目录 01~07 .md 文件。