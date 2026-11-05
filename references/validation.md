# 状态与预算机械校验

适用技能包0.3.0起采用的状态1.9、`SINGLE_TEXT_CONFIRMED_ASSET_STAGES_V4`。程序只用Python 3.10+标准库，入口是[storyboard_checks.py](../scripts/storyboard_checks.py)。无Python时仍按[状态规则](state-and-revision.md)和[时间规则](timing.md)人工核对，记录程序检查未执行。

## 使用范围

程序检查明确提供的结构、区间、版本引用、连续有效前缀、取消候选及时间算术。`ok=true`只表示当前输入在已检查机械范围内通过，不能用它直接填写整个TEXT／INPUT／CAPABILITY／MEDIA为PASS。

- `delivery_ref`、`budget_ref`和检查证据必须有值且映射一致。程序不读取这些位置的正文，不验证来源或用户决定真实，不保证外部路径仍可访问。
- 资产设定、摄影、因果、表演、观看信息、失效依赖的语义和前驱内容仍须阅读核对。尤其是F3是否确实不受F2返修影响，由语义审查决定后再标有效。
- `derive`计算覆盖前缀及其末态来源，不自动选择资产、集规划或场前置。它返回的`frontier`是首个未完成段号候选，不能绕过锁、阻断和必做前驱直接开始创作。
- 单源版本、完整保留的有序链和计划是当前机械格式的边界。跨源版本先按实际证据归一化；稀疏归档、未明确映射的旧版本和嵌套返回上下文不由工具猜测。
- 默认REVIEW／STRICT／ONE_AT_A_TIME。用户另行改变执行策略的项目需要人工处理，当前工具不自动解释新的策略。

## 命令

从技能根运行，项目参数使用实际绝对路径。以下是调用格式，不是已有项目位置：

```bash
python -I scripts/storyboard_checks.py check --state /absolute/project/run-state.json
python -I scripts/storyboard_checks.py check --state /absolute/project/run-state.json --budget /absolute/project/segment-budget.json
python -I scripts/storyboard_checks.py derive --state /absolute/project/run-state.json
python -I scripts/storyboard_checks.py cancel --state /absolute/project/run-state.json --request-id REQ-1 --decision-ref user-message:cancel-1 --output /absolute/project/candidate.json
python -I scripts/storyboard_checks.py commit --state /absolute/project/run-state.json --candidate /absolute/project/candidate.json --expected-state-seq 12 --budget /absolute/project/segment-budget.json
```

| 命令 | 作用与副作用 |
|---|---|
| `check` | 检查快照；提供`--budget`时检查对应预算。仅输出JSON结果，不改输入 |
| `derive` | 从覆盖计算连续前缀、下一源内锚点、兼容链ID、候选段号和有效末态来源；允许旧派生值尚未刷新，不写回、不自动推进 |
| `cancel` | 根据唯一ACTIVE请求和明确返回上下文生成候选；默认输出完整候选JSON。`--output`只创建新文件，已有文件拒绝覆盖；不提交权威状态 |
| `commit` | 校验独立候选、项目与序号、版本历史保留和可选预算后，显式替换权威状态文件 |

`--budget`可重复提供，每个文件须是单个预算对象；测试夹具中的`budgets.json`是数组，不能整体作为一个预算输入。未提供预算时结果中的`budgets_checked`为空，不能声称已检查预算内容。命令退出码0表示本次机械操作成功，1表示规则／数据检查失败，2表示读写或数据深度错误；规则失败包含问题代码及位置，读写或深度错误保留实际错误信息。

## 标准JSON快照

沿用[75个顶层字段](state-and-revision.md#s7-3)。机器格式使用JSON对象、数组、字符串、数字、布尔值和`null`，禁止注释、尾随逗号、重复键、NaN和Infinity。不用`eval`或宽松规则解析旧`key=value`文本。完整合成示例见[base-state.json](../evals/fixtures/state-budget/base-state.json)，它只供机械测试，不能当成真实制作成果。

- `state_version`是字符串`"1.9"`；`state_seq`和`last_completed_formal`是非负整数，布尔值不是整数。
- 三项`production_settings`各有`recommended`、`selected`、`status`和`decision_ref`。已确认项与有效画幅、风格和上限一致；`segment_max_s`可使用`{"value":15,"decision_ref":"实际依据"}`。
- 无返修、无返回事项等用`null`；`blocking_items`、`coverage_ledger`、`prompt_versions`、`segment_plan`和`step_ledger`使用数组，不能用`"NONE"`代替空数组。
- 未由工具解释的创作记录继续保留完整嵌套内容，不因机器格式缩减正文、资产档案、观看状态或历史证据。

### 链、锚点和覆盖

`source_script_ref.version`与当前链、覆盖使用的源版本一致。`chain_registry`按原文顺序记录：

```json
{
  "id": "EP01-SC01-C01",
  "source_version": "SRC-1",
  "episode_id": "EP01",
  "scene_id": "SC01",
  "anchors": [
    {"id":"START","source_anchor":"原文L01起点","action_phase":"右掌抵门，尚未推动"},
    {"id":"A01","source_anchor":"原文L01门半开处","action_phase":"门半开，右掌持续推动"},
    {"id":"END","source_anchor":"原文L01终点","action_phase":"门全开，右掌仍接触"}
  ]
}
```

游标为`{"source_version":"SRC-1","chain_id":"EP01-SC01-C01","anchor_id":"A01"}`或全局`"END"`。同链END保存前归一化为下一链START，最后一链END归一化为全局END。链内锚点需要源定位与动作相位，纯“10秒”不算源定位。程序只能拒绝明显纯秒数，仍需人工验证其他描述真实可定位。

`next_chain_unstarted`保留兼容字段名，其值是游标的chain_id或END；它可以是已经开始但未完成的链。段范围统一半开`[start_cursor,end_cursor)`。

`segment_plan`每项至少保存`formal_id`、`episode_id`、`scene_id`、`source_script_version`、`start_cursor`、`end_cursor`。保留从FORMAL_1开始的顺序计划，可只规划已准备的范围，不要求为了检查提前规划整部作品。计划存在不等于覆盖已交付。

当前`coverage_ledger`每个formal_id最多一条；至少保存上述范围字段，加`prompt_version`、`budget_version`、`delivery_ref`、`checks`、`status`和首尾状态。DONE需要匹配的有效正文与预算版本、交付引用、TEXT PASS证据及对应完成的step_ledger。`checks.TEXT.evidence`使用非空引用字符串，例如`"reviews/F1-P1.md#text"`；布尔、数字、数组、对象、纯空白和NONE／UNKNOWN／UNSET占位符均不接受。其他详细检查内容可保存在同一checks记录或所引用文件中。INVALID条目保留范围，不计入有效前缀。

`prompt_versions`按`formal_id + prompt_version`唯一，可保留历史版本。机器检查字段包括`budget_version`、`budget_status`、`budget_ref`、`status=DRAFT/DONE/INVALID`、`delivery_ref`和可选`adapters`。正文版本号与预算版本号不必相同。其他完整母稿、适配映射等仍按原规则保留。

每次提交先重算前缀。F1 DONE、F2 INVALID、F3 DONE时前缀为1；修好F2且F3依赖仍有效后前缀为3，末态来源为F3，不再次提交F3覆盖。`derive`返回`end_state_source`，调用方须据此同步人物、环境、观看状态等内容；程序不自动改写这些创作记录。

### 取消与阻断

适配记录位于所属`prompt_versions[].adapters[]`。`request_id`在快照内唯一，`base_prompt_version`匹配所属正文。`lifecycle=ACTIVE/CLOSED/CANCELLED`与`text_status=DRAFT/CHECKED/BLOCKED/INVALID`分别记录；CANCELLED需有`decision_ref`。

独立补适配的`return_to`保存`request_id`及原`phase`、`next_required`、`awaiting_continue`、`episode_id`、`scene_id`。当前取消工具不接受嵌套`previous_return_to`或无法唯一定位的上下文。

每个`blocking_items`记录`step_id`、`phase`、`gap`和有关联时的`request_id`。机器格式增加`blocks`数组明确阻断哪些具体目标，例如`["FORMAL_2"]`、`["COMPLETE"]`；`["*"]`表示确实阻断所有目标，不能为了方便扩大范围。其他阻断是否影响返回目标无法判断时，取消工具拒绝推测。

取消只关闭对应请求及其独立步骤记录，清理同request_id阻断；保留覆盖、预算、正文、原质量状态和实际媒体任务记录。仍有返修时phase=EDIT_LOCK优先；仍有其他实际阻断时next_required=WAIT_USER并保留返回上下文。无剩余事项后恢复原目标。重复取消安全拒绝，不创建第二次覆盖或取消记录。

### 预算

正式段预算对象包含`formal_id`、`prompt_version`、`budget_version`、`time_basis="SEGMENT"`、`duration_s`、`target_max_s`和非空`shots`。

每镜记录`id`、`start_s`、`end_s`、`duration_s`；所有绝对时间相对本段0秒。首镜从0开始，镜头连续无重叠，镜长为正，末镜终点等于总长。可选`phases`记录段时码`start_s/end_s`，若提供，须完整、连续覆盖所在镜头。第二镜从6秒开始时，其阶段也从6秒开始，不能重新填0。

阶段或镜头可附`timing`进行递归计算：

```json
{
  "parallel": {
    "basis": "两轨确实可并行，第二轨在1.5秒后启动；依据仍需人工核对",
    "tracks": [
      {"offset_s":0,"timing":{"seconds":2}},
      {"offset_s":1.5,"timing":{"sequence":[{"seconds":1},{"seconds":3}]}}
    ]
  }
}
```

计算结果为5.5秒。一个timing只选seconds、sequence、parallel之一；偏移相对并行组起点，不是另一套段时码；无真实并行依据不能只因算式通过就采用。

可选`speech_checks`是显式逐字对照数组，每项含`speech_id/source_text/rendered_text`。仅检查提供的成对文本完全相同，不扫描母稿、不证明所有原台词都有映射、不判断朗读语速。没有提供时返回`MANUAL_SCOPE_ONLY`，有提供时也只标`PROVIDED_PAIRS_ONLY`。

## 保存与失败边界

`commit`只负责单个权威JSON快照。调用前先保存可追溯的正文／预算版本，完成语义和交付证据检查，再生成独立候选文件。候选必须属于同一project_id，序号严格增加1，使用新transaction_id，`state_storage=FILE`且绝对`state_ref`指向本次权威文件。原有覆盖ID、历史正文版本映射、所属适配请求和每个已开始步骤都必须保留；步骤按已有的step_id及request_id／prompt_version／adapter_version关联，已有版本不可用新版本冒名替换。进行中步骤可以补齐版本并显式转为DONE或INVALID等状态。已取消请求和步骤保留CANCELLED及原decision_ref、已登记的cancelled_at_state_seq；重开使用新request_id。这里检查记录身份与取消证据，其他正文、检查、媒体任务历史内容仍须人工核对，不能以通过为由删减。

工具创建同目录排他`.lock`文件，检查旧序号，写临时文件、flush/fsync并读回字节，确认旧文件未被改变后`os.replace`。临时写入、校验或替换失败会保留旧文件；正常返回及异常路径都会尝试清理本次临时文件与自己的锁。锁关闭失败时保留锁文件，避免掩盖未完成的清理。

提交回执使用`committed`区分状态是否已替换：替换成功返回`ok=true`、`committed=true`、当前state_seq；清理正常时`cleanup_complete=true`、`warnings=[]`。替换后若关闭或删除锁失败，仍退出0并报告已提交，同时返回`cleanup_complete=false`及`CLEANUP_FAILED`告警，不能因清理告警重复提交或声称旧状态仍有效。替换前失败返回`ok=false`、`committed=false`及原始错误；同时发生的清理故障作为warnings附带，不覆盖原始原因。进程被强行结束也可能留下锁：先核实没有写入进程，人工处理后再重试，不自动抢锁。

原子替换不是正文＋预算＋状态的多文件事务，不防范不遵守锁约定的外部写入，也不保证突然断电后的目录持久性。当前工具不提供完整事件日志重放；完整快照与历史版本仍是恢复依据。

## 验证与复跑

```bash
python -I scripts/check_package.py
python -I -m unittest discover -s tests -v
python -I scripts/run_checks.py --output evals/runs/local-check.json
```

最后一条命令写入新运行记录，含受测文件哈希、实际stdout/stderr、退出码、测试数量及运行中输入是否变化；已有文件拒绝覆写。仓库中已保存的版本运行见[实施与验收记录](../docs/技能包实施与验收记录.md)。

可移植数据见[夹具说明](../evals/fixtures/state-budget/README.md)，对应[新增G12规格](../evals/scenarios.md#state-regression)。单元回归只算D方法，人工H、客户端发现F和真实媒体M仍独立验收。
