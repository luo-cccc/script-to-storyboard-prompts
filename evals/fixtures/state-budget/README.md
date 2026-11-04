# 状态与预算回归夹具

本目录提供技能包0.3.0、状态1.9的合成机械输入。所有人物、用户决定、交付引用和TEXT证据都是测试数据；没有真实媒体、供应商能力或用户项目。简化正文不满足完整母稿模板，不能用作H方法的完整创作前驱。

| 文件 | 用途 |
|---|---|
| [source.md](source.md) | 两条连续事件链、源定位与动作相位；第一条链在门半开处跨正式段 |
| [base-state.json](base-state.json) | 75字段初始快照、三段计划、待交付母稿版本及合成前驱 |
| [prompts.md](prompts.md) | 三段简化文字，用于范围、末态和交付引用测试 |
| [budgets.json](budgets.json) | 三个预算对象组成的数组，测试逐个调用预算检查 |
| [expected.json](expected.json) | 初始、逐段交付、返修补洞、取消和偏移并行的预期值 |

第一条链由FORMAL_1覆盖START→A01、FORMAL_2覆盖A01→下一链START；FORMAL_3覆盖第二条链至全局END。计划已存在时，初始覆盖仍为空，已完成前缀仍为0。测试构造交付及返修记录后再计算覆盖，不把计划当成已完成。

## 运行

在完整仓库根目录执行：

```bash
python -I -B -X utf8 -m unittest discover -s tests -v
python -I scripts/run_checks.py --output evals/runs/local-check.json
```

结果文件必须使用新文件名。要单独观察初始快照，可执行：

```bash
python -I scripts/storyboard_checks.py check --state evals/fixtures/state-budget/base-state.json
python -I scripts/storyboard_checks.py derive --state evals/fixtures/state-budget/base-state.json
```

这些只读命令不会改写夹具。实际项目使用项目文件的绝对路径。`base-state.json`中的`state_storage=CONVERSATION`是合成输入；它不能直接充当`commit`的FILE候选。

`budgets.json`是测试用数组，不能直接作为CLI的单个`--budget`输入。CLI要求每个预算文件是一个对象；需要命令行复核时，将数组中的某个完整对象另存为项目外的新JSON文件，再传入`--budget`。多个对象分别保存，可重复提供`--budget`。未提供预算时，状态检查成功不表示已检查预算正文。

## 验证范围

[测试代码](../../../tests/test_state_budget.py)覆盖[新增G12规格](../../scenarios.md#state-regression)的机械部分：

| 规格 | 程序验证范围 |
|---|---|
| G12-01 | 链内部分覆盖、快照读回、连续承接 |
| G12-02 | 中间段失效及修复后吸收有效后缀、末态来源 |
| G12-03／04 | 独立适配取消、请求所属阻断、其他阻断和返修锁、返回上下文及媒体任务保留 |
| G12-05 | 重复覆盖、过期序号、锁冲突、历史记录保留、同步与替换失败时保留旧状态字节、替换后清理故障回执 |
| G12-06 | 不同集的同名场次目标归属 |
| G12-07 | 段时间码、版本映射、严格数字、偏移并行、显式对白对照 |

测试还检查严格JSON解析、制作条件确认和check／derive只读性。输入中留存的证据只做结构及关联核对，不证明真实交付、F3语义依赖有效、并行安排可执行或对白映射完整。

本目录及单元测试只对应D方法。模型文字行为H、客户端发现与触发F、真实媒体M仍须分别执行和记录，不因机械回归通过而把60个人工用例改成PASS。完整字段和提交边界见[机械校验说明](../../../references/validation.md)。
