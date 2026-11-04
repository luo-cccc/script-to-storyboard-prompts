# 七、完整运行状态 覆盖账本 返修与恢复机制

本文件保存本技能包的状态、覆盖与返修规则，与[技能入口及七步流程](../SKILL.md)和本轮适用参考文件配合使用。技能目录保存规则和模板，剧本项目保存自己的材料与当前状态；预算规则见[时长计算与分段](timing.md)。

<a id="s7-1"></a>
## 7.1 核心原则与唯一目标

next_required是唯一可推进的目标，不能写多个候选。每轮开始锁定target，在本轮更新next_required后也不得继续执行新目标。

只读咨询和技能维护不启动生产状态机；明确原文逐字复送不更新生产状态。新项目没有历史状态是正常初始条件，不要求先提供旧回执。

项目分析、资产、集规划、场次分析、预算分段都不消费剧情；只有新正式段实际交付且相应文字检查完成才提交有效覆盖。正文草稿、计划表、内部思考、READY或DONE标签均不构成交付证据。母稿、适配稿和媒体任务属于同一段的不同产物，只提交一次文字覆盖。

本状态机的DONE、有效前缀和COMPLETE描述文字制作范围，不代表图片、视频或声音已经生成、验收或成片。母稿预期呈现的末态与已观察媒体的实际末态分别保存；生成偏差按[7.9](state-and-revision.md#s7-9)记录和返修，不能悄悄改写已确认剧情去迁就错误视频。

固定逐步等待。awaiting_continue=true意味着等待下一条指令，不是自动继续。WAIT_USER意味着存在具体未解决事项，普通“继续”不能替代缺失素材或实质决定。日常选镜按用户授权由模型自主完成，不因存在多个拍法增加阻断。

<a id="s7-2"></a>
## 7.2 持久保存与正文分离

状态必须可核验、可恢复，不能只存在于模型隐藏记忆。可靠项目文件能力下，先按用户指定位置或已明确的当前项目定位项目根目录，核对project_id、state_ref与source_script_ref的归属，再复用当前项目目录：保存一份完整run-state.txt、一份当前场次预算与分段记录、原剧本及各已交付Prompt有效版本；已有文件继续沿用，不另建重复报告。保存或移交恢复材料时，确保本技能包的[技能入口及读取路由](../SKILL.md)、本轮适用参考文件与上述项目数据一并可读取。技能目录保存规则和模板，项目根目录保存材料与当前权威状态；运行数据文件不属于技能参考库。已有项目沿用实际文件位置，不强制搬迁，不能把技能目录或规范文件所在位置当成剧本项目目录。规则链接按所在文件解析，项目材料路径按已定位的项目根目录或既有可定位引用解析。每个项目只维护一份当前权威状态；历史快照可以归档，但不得与当前状态混用。

保存时使用同一state_seq／transaction_id关联状态、预算、正文和覆盖版本；临时写入、读回关键字段核验后提交，避免半写状态。单文件替换可用原子方式；多个文件仍须核对版本匹配。失败则保留上一个有效状态，记录未提交结果，转会话交付完整必要状态，不声称保存成功或自动推进。

FILE模式的母稿正文文件只含[5.1](video-template.md#s5-1)内容；存在适配稿时另存干净提交文本及必要参数／输入说明，版本映射、能力证据、预算和媒体观察仍保存在运行记录中。给出各份用途与最短状态回执，避免把母稿与适配稿连续当作一份提交。CHAT模式分别标明可复制范围，在其后另起【运行状态 不属于视频提示词】，提供完整必要状态及当前覆盖、预算、首尾记录。纯正文展示不等于删除状态。

FILE短回执至少包括：本轮目标与完成状态、state_seq、episode_id／scene_id、last_output、last_completed_formal、next_required、awaiting_continue、script_cursor、存在时的blocking_items／edit_lock／invalidated_from、state_ref／plan_ref及版本。本轮COMPLETE时明确next_required=COMPLETE。

会话模式若累计内容过长，可把同一状态快照单独作为可复制文本块或附件，仍属于同一次交付；没有真实可访问归档时不得将完整账本压成无效路径或“此前同上”。已归档前场可留索引，当前场和受返修影响的历史段保留完整有效记录。

<a id="s7-3"></a>
## 7.3 RUN_STATE固定字段

以下是状态结构，初始化时填真实值，不把斜线枚举原样当成运行值。NONE表示确无该项；UNKNOWN表示未知；不适用用NOT_APPLICABLE并保留原因。运行状态与视频Prompt严格分开。

```text
【RUN_STATE 不属于视频Prompt】
state_seq=[每次状态实际更新递增]
state_version=1.8
workflow_schema=SINGLE_TEXT_CONFIRMED_ASSET_STAGES_V3
transaction_id=[本次关联正文、预算与状态的版本标识]
phase=[PROJECT_SETUP／ASSET_RUNNING／EPISODE_PLANNING／SCENE_PREP／FORMAL_RUNNING／EDIT_LOCK／COMPLETE]
project_id=[项目唯一名称或ID]
project_status=[UNSET／IN_PROGRESS／DONE；分析与三项制作条件确认均完成才DONE]
project_analysis_status=[UNSET／IN_PROGRESS／DONE；与用户确认状态分开]
production_settings_status=[UNSET／WAIT_CONFIRM／CONFIRMED]
production_settings=[video_aspect_ratio、visual_style、segment_max_s逐项记录recommended、selected、status=PENDING／CONFIRMED、decision_ref；未选selected=UNSET]
video_aspect_ratio=[用户确认的视频画幅，未确认UNSET]
visual_style=[用户确认的全片风格正文全文、媒介及色光／成像／材质／观看原则、条件变化与适用范围、版本及decision_ref；不只存方案名称，未确认UNSET]
source_script_ref=[原剧本可定位位置与版本，无文件时会话位置及实际原文范围]
visual_reference_status=[UNSET／IMAGE_READY／TEXT_READY]
visual_reference=[真实图像来源与版本、已读取解析位置、职责、允许继承与禁止继承、用途、平台实际可用状态；无图时NONE]
visual_baseline=[与visual_style对应的完整文字视觉依据及版本；有真实图片时附来源、已读解析和指定用途，不将分析图片等同于平台绑定]
project_decisions=[用户决定或AI获授权自行选定的事项、适用范围、版本与真实依据，待决建议另列；平台／模型能力、模式、核验日期和适配结论只在有依据时记录]
asset_status=[UNSET／RUNNING／DONE；人物与场景道具两步均完成才DONE]
asset_substage=[CHARACTER／SCENE／PROP／COMPLETE]
character_asset_status=[UNSET／RUNNING／DONE]
scene_asset_status=[UNSET／RUNNING／DONE]
prop_asset_status=[UNSET／RUNNING／DONE]
scene_prop_asset_status=[UNSET／RUNNING／DONE]
asset_queue=[按[第二步](../SKILL.md)CHARACTER与[第三步](../SKILL.md)SCENE、PROP分队列记录实际单元、版本、顺序及完成情况；人物每单元含母图和四视图两份必要交付证据，素材职责与状态引用所属资产记录]
character_assets=[逐人物ID母图与对应四视图的成套交付证据、各LOOK／STATE版本、适用集场时点、完整提示词位置、确认情况、实际图片和平台提供状态；首次只有母图不能标该人物DONE]
character_profiles=[逐角色身份与年龄、height_cm、体型比例、height_basis=用户设定／剧本事实／已采用的设计补充、来源与版本；母图、四视图、视频锚定共用，不从图片反推实测值]
scene_assets=[场景母图MASTER的版本、适用范围、交付或复用依据、实际图片与平台提供状态；场景变化继续由environment_state记录，不建立其他场景图种的生成任务]
prop_assets=[核心道具及持有图／设定板实际版本、归属、适用范围、交付依据与媒体状态]
episode_id=[当前集号]
episode_status=[UNSET／IN_PROGRESS／DONE]
scene_id=[当前场号]
scene_wide_status=[UNSET／ESTABLISHED／REBUILD_REQUIRED]
prep_scene=[当前前置所属集场]
prep_step=[0／ANALYSIS／ANALYSIS_DONE／BUDGET_SEGMENT／DONE]
prep_batch=[当前单元分批号]
prep_status=[UNSET／IN_PROGRESS／DONE]
last_completed_formal=[从起点连续有效且已交付的最大正式段号，初始化0]
last_output=[最近实际交付目标或STATE_RECOVERY／REVISION_FORMAL_n／REISSUE_FORMAL_n]
next_required=[PROJECT_BASELINE／具体资产ID／CHARACTER_ASSET_REVIEW／SCENE_PROP_ASSET_REVIEW／EPxx_PLAN／SCxx_ANALYSIS／SCxx_BUDGET_SEGMENT／FORMAL_n／WAIT_USER／COMPLETE中的唯一实际目标]
script_cursor=[下一条未消费链ID及其START锚点，全部结束为END]
next_chain_unstarted=[与script_cursor一致的下一链或END]
chain_registry=[稳定链ID、源版本、原文起止锚点、所属集场；已经消费的ID不改号]
coverage_ledger=[各正式段的完整覆盖记录，格式见[7.4](state-and-revision.md#s7-4)]
prompt_versions=[各正式段母稿与可选模型提交适配稿的版本、可定位正文、有效性、交付证据及关联预算／能力核验版本；适配稿与母稿共用formal_id，不重复覆盖]
segment_max_s=[[第一步](../SKILL.md)用户确认的单段时长上限及decision_ref，未确认UNSET；与production_settings对应值一致]
segment_delivery=ONE_AT_A_TIME
segment_plan=[每个计划段的链ID、原文起止、预算、首尾状态、计划版本与依据]
budget_status=[UNSET／DRAFT／CHECKED／FROZEN／INVALID]
budget_ref=[当前完整预算与语速卡的实际位置和版本]
plan_ref=[当前场次分析、预算、分段记录的实际位置与版本；不指向已删除的分镜设计表]
transition_plan=[逐对相邻段的类型载体、落位、完整首尾状态、尚未开始的动作、计划版本与PLANNED／DONE／INVALID]
transition_review=[每段正文版本、段内切点、前后边界及check_scope=TEXT的PENDING／PASS／FAIL／INVALID、问题与修正；媒体观察引用[7.9](state-and-revision.md#s7-9)记录，不由文字PASS推断成片通过]
characters_state=[有效文字正文的逐角色位置、朝向、姿态、衣装、伤污、形态、意图与持续表演，关联character_profiles身份和身高版本；媒体偏差另记观察，不自动覆盖]
viewing_state=[从有效文字正文预期提供给观众的明确信息、可能推测但未证实事项、待解问题及角色各自已知／误解；关联段号、镜号、原文证据及版本。文字呈现不等于观众实际反应或已生成媒体，未交付计划不能记为已呈现；真实媒体漏呈现或提前揭示时引用[7.9](state-and-revision.md#s7-9)观察并评估后续影响]
weapons_props_state=[物件唯一名称、数量、持有人、左／右手、位置、离手、损坏及归属变化]
environment_state=[空间锚点、出入口、设施、光向、天气、破坏、残留及持续运动]
ongoing_effects_state=[技能、束缚、变身阶段、持续声源及相位，确无则NONE]
voice_profile=[各角色实际声线依据、已提供声音素材及版本，不虚构试听或绑定]
prop_ledger=[既有、新增、转交、遗失、损坏与移除道具及事件时点]
last_frame_snapshot=[最近有效文字段的预期末态及版本；有实际媒体时另附media_ref、实际时码／帧及是否验收通过，二者不混写，文字记录不冒称真实生成帧]
execution_mode=REVIEW
step_policy=STRICT
performance_mode=[沿用用户NORMAL／PRECISE设置，无要求时NORMAL]
awaiting_continue=[true／false]
step_ledger=[每个已开始单元的status=IN_PROGRESS／DONE／REUSED／INVALID，交付位置与版本、决定依据；checks分别记录TEXT、INPUT、CAPABILITY、MEDIA的实际结论、范围与证据，不以一个PASS代替四类检查。按[7.9](state-and-revision.md#s7-9)在所属单元内保存media_observations和实际generation记录；未执行媒体检查记NOT_RUN，未开始单元不得预填DONE]
blocking_items=[NONE或原未完成step_id、具体缺口及阻断范围；依赖范围按[5.2](model-adaptation.md#s5-2)区分通用母稿、特定提交稿或媒体任务]
edit_lock=[NONE或当前返修目标ID]
edit_context=[返修前phase、next_required、last_completed_formal、script_cursor、旧版本、修改范围；源于媒体反馈时附观察记录、时码证据、归责判断及本次主要改动，检查后恢复原目标]
invalidated_from=[NONE或第一个失效目标]
return_to=[增量资产、补材料、预览确认等待或恢复后返回的原phase和唯一目标；无则NONE]
delivery_mode=[PROMPT_CLEAN，预算与状态另存／另区；用户主动展开时记录AUDIT]
delivery_channel=[FILE／CHAT]
state_storage=[FILE／CONVERSATION]
state_ref=[真实状态位置与版本；会话模式写本快照位置，不造文件路径]
recovery_evidence=[恢复或迁移依据；可包括真实任务ID、任务审计结果、输入快照、媒体版本、时码／帧证据及文本状态；没有则NONE，不以文字承诺代替]
```

<a id="s7-4"></a>
## 7.4 覆盖账本与链ID

稳定编号格式EP01-SC01-C01，旧项目已有SC01-C01等可无损沿用并补集号归属，不为美观重号。链对应完整因果事件，不等同于镜头。原文有改版时建立新源版本和映射，已交付历史保留原对应关系。

每个正式段完整记录：

```text
F_n={formal_id;episode_id;scene_id;segment_id;prompt_version;budget_version;source_script_version;chains;start_anchor;end_anchor;start_state;end_state;delivery_ref;checks;status=DONE／INVALID}。
```

计划覆盖只存在segment_plan；正式交付成功后才进入有效coverage_ledger，不能把计划段记为DONE。覆盖起点必须等于当前script_cursor，和有效前段无重叠、无缺口，原台词与必要事件全部有去向。

段内衔接不另加链，不再消费一次原文。纯镜头变化不改变覆盖。历史重发读取该段自己的固定范围和历史首尾，不按当前剩余剧情重新生成。

last_completed_formal表示连续有效前缀，不取历史最大标题编号。后续已有文件但被标INVALID时不算已完成，也不能作为续写开场依据。

<a id="s7-5"></a>
## 7.5 状态转换与继续

新项目：phase=PROJECT_SETUP、project_status=IN_PROGRESS、project_analysis_status=IN_PROGRESS、production_settings_status=UNSET、next_required=PROJECT_BASELINE、last_completed_formal=0、awaiting_continue=false。分析交付后project_analysis_status=DONE；只要三项条件仍有PENDING，就置production_settings_status=WAIT_CONFIRM、next_required=WAIT_USER、blocking_items.step_id=PROJECT_BASELINE并列未确认项，project_status保持IN_PROGRESS，不进入资产。

用户确认：逐项保存selected和decision_ref；部分回答只清除相应缺口，继续询问剩余。三项CONFIRMED且依据可用后project_status=DONE、production_settings_status=CONFIRMED，PROJECT_BASELINE记录DONE或有证据的REUSED，清空已解决的blocking_items；phase=ASSET_RUNNING、asset_status=RUNNING、asset_substage=CHARACTER、character_asset_status=RUNNING，只设置[第二步](../SKILL.md)首个人物单元或CHARACTER_ASSET_REVIEW，awaiting_continue=true并停止，不在同轮夹带母图。

[第二步](../SKILL.md)人物单元：核验三项已确认与项目前驱→同轮交付母图和四视图及本次必要版本→按两份实际交付证据记录character_assets和step_ledger→仅设置下一人物。人物全部完成或范围核对有据后character_asset_status=DONE、scene_prop_asset_status=RUNNING，next_required指向[第三步](../SKILL.md)首个待交付场景；无场景缺项时按实际证据转首个道具，全部复用或无新增时指向SCENE_PROP_ASSET_REVIEW，asset_substage随实际目标设SCENE或PROP；不在最后一个人物轮附场景或道具。

[第三步](../SKILL.md)场景道具：先SCENE队列再PROP队列，每轮一个实际单元。场景全部完成后scene_asset_status=DONE、asset_substage=PROP；道具全部完成后prop_asset_status=DONE、scene_prop_asset_status=DONE。没有某类需求时保留实际范围核对证据，不伪造资产。全部复用或无新增时在本步交付SCENE_PROP_ASSET_REVIEW。只有人物与场景道具两步均完成才asset_status=DONE、asset_substage=COMPLETE、phase=EPISODE_PLANNING、next_required=当前EPxx_PLAN，等待继续。

按集规划：记录场序、链与造型需求。缺增量资产则保存return_to（原phase、目标及资产子阶段），设置phase=ASSET_RUNNING并进入实际缺项所属CHARACTER／SCENE／PROP队列；人物新身份需完整母图加四视图，既有身份只缺新造型则补对应完整四视图。补完恢复原未完成目标和有效其他队列状态，不重新混排初始第二、第三步，不重做无关母图。无缺项则phase=SCENE_PREP、next_required=该集第一未完成场次SCxx_ANALYSIS。

场次分析完成：scene_wide_status=ESTABLISHED、prep_step=ANALYSIS_DONE，next_required=同场SCxx_BUDGET_SEGMENT。

预算分段完成：预算、分段和首尾记录均有可定位证据，且无阻断本轮预算／分段目标的未决事项，prep_step=DONE、prep_status=DONE、phase=FORMAL_RUNNING、next_required=FORMAL_(last_completed_formal+1)。平台适配或媒体任务的独立缺口按[5.2](model-adaptation.md#s5-2)、[7.9](state-and-revision.md#s7-9)记录，不自动阻断已满足条件的文字预算。

所有以上完成转换都设置awaiting_continue=true并结束本轮，不推进script_cursor或正式段号。

新正式段交付前核验：target=next_required；n=last_completed_formal+1；覆盖起点=script_cursor；项目分析、三项制作条件确认、人物资产、场景道具资产、本集规划、本场分析与预算前驱有DONE／REUSED证据；无未完成返修锁，且blocking_items中没有阻断本轮交付及其实际前驱的缺口；有效段界、当前目标所需素材和文字起态可恢复。只检查本轮依赖范围：通用母稿不以已出图、已上传或媒体PASS为前驱；指定模型提交稿的必要输入和能力按[5.2](model-adaptation.md#s5-2)核验，不越过其真实阻断。

正文、预算、衔接检查和交付完成后提交F_n：追加有效覆盖、登记正文版本、last_completed_formal=n、last_output=FORMAL_n、script_cursor移到覆盖终点之后的下一链、next_chain_unstarted同步、更新人物／道具／环境／持续效果与末态，并按实际呈现更新viewing_state；后台剧本事实和计划镜头不记作观众已知。

随后只设置下一目标并同步phase：同场未完→phase=FORMAL_RUNNING、next_required=FORMAL_n+1；同集下一场→phase=SCENE_PREP、next_required=其SCxx_ANALYSIS并重置当前场prep字段；下一集→phase=EPISODE_PLANNING、next_required=其EPxx_PLAN；全部结束→phase=COMPLETE、next_required=COMPLETE、script_cursor=END、next_chain_unstarted=END、awaiting_continue=false。未全部结束则awaiting_continue=true。

用户说“继续”：读最新状态及前驱证据→检查返修锁与阻断→锁定本轮唯一target→awaiting_continue=false→完成当前单元或记录真实缺口→保存与交付更新状态→停止，不在本轮循环执行新next_required。

WAIT_USER时补材料或决定仅闭合原步骤。仍缺内容保持IN_PROGRESS；齐备后清空阻断并设置下一目标和等待状态。“确认并继续”不自动同轮追加下一个生产单元。已确认同项不再次请求确认。

指定未来目标晚于next_required属于跳段，只说明当前实际缺口并停在正确目标；指定已存在的历史段按重发／返修分支，不用新段n+1闸门拒绝历史操作。

<a id="s7-6"></a>
## 7.6 返修锁 局部修改与后续失效

用户要求修改、调整、删增动作／镜头／台词／声音／约束或明确否定当前段，即进入EDIT_LOCK。记录edit_context，冻结原游标、段号和下一目标；本轮只处理指定返修，即使同时说继续也不追加新段。

局部修改不改变覆盖及段尾：输出目标完整修订正文，其他未受影响内容逐字或等义保留，不以“其余不变”代替整段；重算受影响时长与检查，更新本段版本。覆盖、script_cursor、last_completed_formal和原next_required保持。修订交付成功后 `last_output=REVISION_FORMAL_n`；非正式段返修保留原 last_output 并在 edit_context 记录，不虚报新段。完成后解锁并恢复原phase和下一目标，等待继续。

修改段尾状态、原文覆盖或已确认段界：先保留历史版本，从首个实际受影响边界标记后续正文、预算、`transition_plan`／`transition_review`与相关step_ledger为INVALID。无关资产与前置继续有效，不因局部返修重启项目。

回退到最后连续有效正式段，script_cursor回到其后的第一未覆盖链。被修目标如已完整修订、检查并交付且仍紧接有效前缀，可以作为新有效版本提交；受影响后续仍保持INVALID，不自动重发。目标本身未完成时不得算有效前缀。

覆盖边界变化需重排分段时，next_required指向最早受影响的SCxx_BUDGET_SEGMENT；事实或空间分析也失效时先回对应SCxx_ANALYSIS。上游仍有效且仅需重做后续正文时指向第一个失效FORMAL_n。这只是设置目标，不在本轮执行它。

修改取景、切点或声音即使未改人物物理末态，也要核对是否改变观众实际看见的证据与揭示时机；若后续依赖该信息，按实际依赖更新viewing_state并使受影响后续失效，不让漏看或提前看见的信息仍冒充原版本。

局部改动对白说法、语言、揭示、焦点或剪取时，在当前场同一时钟上对照“关键语义到达→证据首次清楚→人物实际获知→反应开始→动作结果→切点”，区分观众和角色各自的信息来源。换语种／译稿按最终已授权词句重新定位语义到达，不照搬旧语言词序的反应点，也不因此取得翻译权限；正文原台词仍受保护。只复算与本次改动相连的预算、话轮和边界，并沿真实依赖追踪后续；无关镜头、资产和已确认事实继续有效。必要的语义与阅读窗口不能为了保住旧累计时长而压缩，若改变固定时长或已确认段界则按既有授权分支处理。

修改衔接只影响摄影表达且不改变状态与覆盖时按局部修；改变位置、持物、动势、声源或状态时按上述后续失效处理。删除衔接也要复核实际首尾，而不是额外减少一段覆盖。

修改资产、声线或质感依据时也建立目标单元返修锁，记录新版本及受影响集场。仅改变视觉表达而不改变剧情覆盖和连续末态时，保留有效覆盖与游标，只把需同步的相关视觉正文或资产版本标为待修；改变身份事实、服装状态、道具归属、空间结构或末态时按实际依赖使后续对应项失效。不要因更换质感图删除未变化的剧情覆盖，也不要让旧视觉版本冒充已同步完成。

返修完成且相关检查通过后edit_lock=NONE，根据保留或重算的next_required恢复phase。返修未完成则保留EDIT_LOCK及具体缺口，不保留虚假DONE。state_seq递增、版本与证据同步。不得将已失效后续Prompt当作续写事实。

<a id="s7-7"></a>
## 7.7 重发 原样复送与恢复

明确“原样／逐字／一字不改”：定位完整原文并原样复制，不重新编译、不重算、不新增RUN_STATE、不推进游标、不将旧原文重新标成有效版本；找不到原文则请求该原文，不用记忆重写冒充复送。

普通“完整重发第X段”且无内容修改：读取历史覆盖、起止锚点、有效版本和历史邻段，按请求的产物类型重发；未指定类型时默认[5.1](video-template.md#s5-1)完整母稿。明确要求已交付的模型适配稿时，沿用其目标模型、既有格式和有效版本，并附该版本必要的参数／输入说明，不恢复母稿栏目或擅自重新编译。找不到对应有效产物时说明缺项，不用新写内容冒充重发。last_output=REISSUE_FORMAL_X，正式段号、游标和原下一目标均保持；包含修改则转返修。

恢复来源：用户当前明确修正→最新完整RUN_STATE→有效覆盖账本与版本→最近有效正文及前置交付→原剧本。来源有冲突时交叉核验，不只相信较大的state_seq或最近标题数字。

恢复必须确认：最后连续有效段、下一原文起点、当前唯一next_required、前驱交付证据、分段及预算版本、实际末态、未完成返修与后续失效范围。缺任一项且可能跳段、漏段或复位时，只请求最少材料，不猜测完成。

恢复轮记录recovery_evidence、last_output=STATE_RECOVERY并递增state_seq，不消费剧情、不夹带新正式段。仍有未完成返修保留原锁；完全恢复后设置正确下一目标和等待状态。

跨模型迁移必须带本技能包的[技能入口及读取路由](../SKILL.md)、[状态与返修规则](state-and-revision.md)及恢复与续作所需的其他适用参考文件、当前剧本、完整最新状态、当前场预算分段、有效Prompt、覆盖及返修相关历史、真实素材或可读取文字依据。技能文件提供规则；项目材料从已明确的项目根目录或既有可定位引用收集，迁移时须提供可实际读取的内容或附件。短回执和单独文件路径不足以恢复，不能声称另一模型能读取当前本地磁盘。

<a id="s7-8"></a>
## 7.8 旧版迁移与一致性闸门

本版v1.8加入[5.2](model-adaptation.md#s5-2)模型适配、[第四部分](asset-templates.md)素材职责与可用状态、同句同语言同表演的实测依据、空间与声音衔接，以及[7.9](state-and-revision.md#s7-9)实际媒体观察和任务恢复。沿用[七步制作流程](../SKILL.md)与原有RUN_STATE顶层字段：能力资料放project_decisions，素材职责放所属资产／visual_reference，派生关系放prompt_versions，实测放语速卡，媒体观察与真实任务放所属step_ledger，返修与恢复仍用edit_context和recovery_evidence。workflow_schema保持SINGLE_TEXT_CONFIRMED_ASSET_STAGES_V3，state_version更新为1.8。

旧项目的有效正文按其实际职责映射为母稿，不因升级改写、重发或撤销覆盖；旧稿缺必要事实时只处理实际依赖。模型未指定不建适配记录，未执行的媒体观察记NOT_RUN，历史媒体是否检查无法确认时记UNKNOWN，不把旧DONE迁成媒体PASS。只按实际来源补素材状态，缺历史生成记录不否定已经可读的图片。三项确认、人物首次成套、整场预算和连续有效前缀继续有效；新规则改变实际内容时按[7.6](state-and-revision.md#s7-6)局部返修，不重启项目。

v1.7曾校订摄影术语、资产光照、剧情画内文字与phase同步，并把构图方法论改为按观看任务选用。继续保留该版成果；术语名称或状态标签纠正不自动使历史正文失效。需要改变光照、文字可见范围或揭示时点时，核对实际依赖并返修，不能把规范更新当成历史正文已同步。

v1.6更新影像风格与光影的写法及对应模板，沿用现有三项制作条件确认、人物／场景／道具步骤、镜头设计、完整预算和状态转换。旧项目已有确认风格正文时直接复用并补入visual_style全文；只有方案名称时，从已确认可见特征整理成连贯文字，不擅自补新审美。确有会改变风格的未决选择时在原确认或返修节点处理。历史提示词不因改栏目自动作废或重发，新稿与用户要求返修的稿使用【全片风格】和“本段光线、色彩与环境基调”。风格实质改变按既有依赖返修，未更新的旧正文或视频不称已同步。

本版v1.5沿用既有阶段、完整模板、预算与状态转换，加入观众视角的观看与衔接要求。viewing_state只从有效已交付正文及已有场次分析补录；历史证据不足时标未核实，不将完整剧本知识回填为观众已知，不清空旧覆盖或仅因升级要求重新制作。只有待生成／返修片段实际依赖未核实的信息时，才核对相应历史片段。此字段和checks用于衔接，不增加独立镜头设计表、审批或输出阶段。

本版v1.4沿用v1.3流程与确认关卡，补充character_profiles的具体身高、来源及版本。恢复旧项目先查已有文字人物设定；无数值时按[角色设计规则](../SKILL.md)补充，不伪称已实测。仅补档案或改变表述不消费剧情；若与已确定身高冲突、实际影响人物比例或动作承接，按既有返修机制处理受影响资产与正文。运镜和构图检查写入原有checks，不另建分镜设计步骤。

本版v1.3迁移：将旧混合资产队列按人物、场景、道具重新归类，保留已交付全文和有效版本；人物只有母图但缺四视图时标该单元IN_PROGRESS并补齐，不重做人脸。已有场景道具成果可保留，但后续运行仍核验[第二步](../SKILL.md)人物成套完成。已确认的画幅、质感和段长有明确用户决定时直接复用，不重复问；旧默认30秒、AI自动质感或推定画幅不算用户确认。缺确认时保存return_to及原有效覆盖、锁和下一目标，只回到PROJECT_BASELINE的制作条件确认缺口，next_required=WAIT_USER，不清空历史剧情。确认轮完成后恢复可执行的原目标；若新选择影响已有视觉或预算，只把相关版本交给返修机制处理，不静默称已同步。workflow_schema更新为SINGLE_TEXT_CONFIRMED_ASSET_STAGES_V3，不按新步骤编号改动正式段号。

从旧单文本规范v1.0恢复时，其“会话最少记忆”不是完整状态。只从实际交付、剧本和用户决定回填有证据的字段；未核验的前置、预算和覆盖不置DONE，保留已经真实完成的成果，补缺而不重启。

从详细模块版迁移时，保留原项目、资产、集场ID、动作链、coverage_ledger、last_completed_formal、script_cursor、edit_lock、invalidated_from和有效版本。原场戏Step1／Step2的剧情、空间、人物事实映射至SCxx_ANALYSIS；旧独立摄影方案及Step3分镜设计不再是必做前驱；已有分镜可作为历史正文与预算证据，不恢复设计库或强制流程。原Step4实算预算与分段映射SCxx_BUDGET_SEGMENT；原Step5段号保持，不能因流程换名重编号。

只依据实际内容记DONE／REUSED，不按旧步骤数字机械加减。旧CAMERA_PLAN／COMBAT_BRIEF等设计审批状态可归历史，实际动作、角色状态、道具与持续机制仍必须映射保存；没有独立设计表不阻止新流程，缺必要预算或起态仍阻止相关交付。

旧TRANSITION独立单元迁移为相应正式段首／尾的transition_plan，不增加段号和覆盖。原锁指向该衔接时映射到所属正文或尚未执行的边界记录，保留返修范围。CONTINUOUS迁为REVIEW／STRICT，未获新的明确执行规则修改不批量输出。

每次提交核对：next_required唯一且phase与实际目标一致（项目确认PROJECT_SETUP、资产ASSET_RUNNING、集规划EPISODE_PLANNING、场次分析／预算SCENE_PREP、正式段FORMAL_RUNNING、全部完成COMPLETE；WAIT_USER按blocking_items所属步骤核对，未完成返修保持EDIT_LOCK，增量资产保留return_to）；新段号与有效前缀一致；script_cursor与next_chain_unstarted一致；预算、母稿和边界版本对应，适配稿指向有效母稿且映射无事实遗漏；三项制作条件确认有据且与正文一致；人物首次母图与四视图成套，[第二步](../SKILL.md)完成才进入[第三步](../SKILL.md)；有效覆盖无重无漏；所有DONE／REUSED有证据；INVALID不作起点；未完成返修不越过；素材职责、实际输入和能力依据有据，测量与媒体结论未超出证据范围；状态和交付记录真实可恢复。只检查本轮适用职责，未指定模型或未生成媒体不形成额外失败条件；失败时修实际缺口，不强行继续。

<a id="s7-9"></a>
## 7.9 已有媒体的观察、定点返修与任务恢复

本节只在用户提供真实媒体、要求检查，或另行授权媒体生产并已有结果时使用。没有媒体不生成空验收报告，也不把试听、动态预演或成片验收列为文字制作的必做前驱。按已有工具实际读取；工具不能播放声音或只能看抽帧时，记录未检查范围，不声称听过、看过全片或已验证口型。

先观察实际结果，再对照母稿、适配稿、原剧本和任务输入定位问题，避免只看清单而漏掉明显异常。所属step_ledger.checks区分四类：TEXT为原文、时间与连续性文字检查；INPUT为素材及参数准备；CAPABILITY为目标模式的已核实能力；MEDIA为实际结果观察。各类保存status、scope与evidence；可用PENDING／PASS／FAIL／UNKNOWN／NOT_RUN／NOT_APPLICABLE表达实际情况，无适用任务时注明原因。局部通过只适用于已检查版本和范围。

有观察结果时在所属单元的media_observations记录：

```text
observation_id=[本单元内唯一记录号]
media_ref=[真实文件或可访问结果、版本及来源；有任务时关联task_id]
related_versions=[formal_id、母稿版本、适配稿版本、输入快照和预算版本；未知项明确UNKNOWN]
inspection_scope=[实际看／听的时间范围、画面或音频、播放／抽帧／元数据等方法及未覆盖内容]
time_basis=[媒体自身时码；如需映射全片时间另写偏移，帧号同时记录实际帧率或时间基准，不猜测]
issue_at=[实际起止时间或可定位帧证据；音频问题用可听区间，无法确认精确时点时如实保留范围]
expected_and_observed=[该时点应有事实、实际可见可听偏差和证据位置；无问题时写检查范围及证据，不制造缺陷]
impact=[阻碍理解／破坏身份或连续性／对白或节奏问题／局部质量问题，以及影响镜头和边界]
attribution=[剧本或母稿／适配遗漏／输入或参数／模型生成／后期剪辑／UNKNOWN；区分已证实原因与待验证假设]
next_fix=[本次最主要的可验证改动、应保留的有效部分与成功判据；无须返修则NONE]
verdict=[PASS／REPAIR／REJECT／INCONCLUSIVE，注明仅适用于当前版本与观察范围]
```

例如实际视频4.2秒出现钥匙从右手跳到左手，先核对母稿、提交稿、首帧及真实输入是否均要求右手，再判断来源；未看任务输入就只能提出归因假设。地标被特写裁掉、人物被遮挡或对象暂在画外，不能据此断言物件消失。视频总长符合预算也不证明台词没漏、口型同步或接触过程成立。

返修优先修复证据指向的主要原因，一次改变一个主要变量便于比较；确有依赖的变化可以成组，记录缘由。保留有效身份、光照、动作和镜头，不用“更电影化”替代明确修复指令。重试次数不是根因证据，不设固定失败次数就必须简化的规则；需要简化时仍保护原文、结果、边界和已确认条件。只请求审查时交付问题和建议，不自行改来源或发起付费重投；用户要求修正时按[7.6](state-and-revision.md#s7-6)执行。

只改适配文字、错误输入、生成参数或后期处理而母稿事实与末态不变时，保持母稿覆盖与游标，将原phase和唯一续作目标保存在edit_context或return_to；当前事项受阻时可按[5.2](model-adaptation.md#s5-2)设next_required=WAIT_USER，未完成返修仍保留EDIT_LOCK。完成该事项后恢复保存的续作目标并停止，不重复覆盖。记录新的派生或媒体版本。母稿本身需改时重算受影响内容；改变剧情覆盖、物理末态或观看信息则按[7.6](state-and-revision.md#s7-6)使实际依赖失效。旧媒体保留其原任务关联，不能因提示词已修就标为已修复。必须检查新结果才能更新相应媒体验收；文字返修可以先完成，不因此伪造媒体PASS。

用户已授权且工具实际发起生成时，在所属step_ledger保存以下generation记录：

```text
generation={task_id;provider;model_and_mode;submitted_at;input_snapshot;provider_status;result_refs;collected_at}
```

input_snapshot至少关联实际提交文本、参数、引用素材及其职责与版本；工具能提供摘要或哈希时可附，不假装已保存二进制。任务ID只抄真实返回值，上传、排队、生成成功、收集结果与检查通过分项记录，生成成功不等于验收通过。

恢复先核对真实任务状态和既有结果：已完成未取回时收集原结果，运行中保留任务关联，失败或未知时保存实际返回和缺口。没有可用接口或权限时说明不能核验，不虚构audit、collect命令或平台工具。会话中断、没有本地文件或旧链接失效都不足以证明任务从未提交，不能据此盲目重新收费投递。重投需要已有明确授权覆盖该任务与费用，或由用户作出新决定。任务恢复不新增剧情覆盖，不改变未受影响的文字游标，也不自动取消未完成返修锁。
