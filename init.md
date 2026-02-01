# Agent2Sandbox

# 项目目标
构建一个轻量级的通用Agent和OpenSandbox（开源包python库）交互的框架，其核心理念是：环境即工具（Environment as Tools）。Agent 不需要理解环境的底层实现，只需要通过统一的工具调用协议与之交互。框架遵循一个连续的循环逻辑，Agent（即llm）给出指令/工具执行，环境返回反馈结果，直到任务完成。

# 项目依赖
**使用uv**：请基于uv构建的虚拟环境来实现项目，确保可迁移和复现。
**系统**： 我当前的系统是windows11专业版系统。
**opensandbox库**： 使用该库时请使用uv pip安装的环境；同时如果想要了解该库的使用，可以阅读./OpenSandbox，是这个库的具体实现。
**./test**： test1-sandbox-interaction.py是我随手写的一个测试脚本，可能存在问题，测试运行的时候可以修改。
**OpenAI**：Agent的核心架构目前考虑使用OpenAI的交互格式。

# 项目实现（在Agent2Sandbox目录下实现）
步骤1：完善设计思路，写一个architecture.md，给出项目的整体设计。
步骤2：制定整体项目实现计划，包括完善测试用例test1-sandbox-interaction.py，以测试用例为完成目标，写一个todo list到plan.md中，完成每一项都进行勾选。
步骤3：实现项目的初步架构，以及测试通过时，再由我制定下个阶段更完善的Agent与环境交互的测试用例。