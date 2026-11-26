# Azur Promilia 接入 LoyalTools 的计划

2026-11-26。以下是 `E:\loyal tools` 的接入计划，基于 APMI Core 0.2.2 和独立工具。

## 已具备的独立基础

- 从指定 dump 提取 AP 的计算蒙皮输入、组件骨骼索引、IB、原始属性流及 DDS 绑定证据。
- Blender 4.5.7 导入、保存、重新打开并导出后，未改动的 61 份缓冲逐字节一致。
- 修改顶点、UV、顶点色、权重及拓扑；共享属性展开、UV 拆点、镜像绕序和法线/切线生成已有测试。
- 导出沿用 EFMI 合并骨骼模板的 `TextureOverride_EntryPoint_ComponentN`、`CommandList_Component_DrawInstances` 和 `CommandList_Draw_ComponentN`。资源名和缓冲文件名按 LoyalTools 的组件标识生成。AP Core 负责蒙皮并沿用当前组件的原生骨骼调色板。
- 当前角色的 `d9cf7935` 已从 MCP 帧提取并经 Blender 往返。Core 0.2.2 在实机验证了该组件的蒙皮和五次替换绘制。见 [验证记录](../.ai-memory/SESSION_LOG.md)。

其他组件、移动时的视觉效果和 LOD 转换继续按实机证据验收。整帧可以包含多个模型或 LOD，提取时由用户选择组件。

## 接入步骤

1. **增加 AP 游戏预设。** 在 `tools/LoyalTools/common/logic_name.py`、`global_properties.py` 及相关路由中增加 `APMI (Azur Promilia)`。AP 选择独立提取/导出分支。
2. **接入 dump 提取。** 增加 `extract/apmi_dump_extractor.py`，移植已验证的解析和计算调用匹配逻辑。在现有 `ui/ui_panel_extract.py` 中提供 IB 列表、组件预览与一键提取。先明确选择组件，后续再依据 AP 采样数据实现角色和 LOD 分组。
3. **接入 Blender 工作空间。** 将独立 `project.json` 映射到插件的集合、工作空间和蓝图节点，保留组件标识、原始流布局、源顶点引用与骨骼索引。首版保持组件独立的骨骼索引，提供 UV、颜色、权重与几何编辑。
4. **接入 Generate Mod。** 增加 `ui/universal/apmi.py`，沿用 EFMI 合并骨骼模板的组件入口、绘制回调和资源命名。根据 AP 采样选择 `drawindexed` 或 `drawindexedinstanced`。Core 管理蒙皮所需的着色器槽位。确认 AP 材质槽位后再接入贴图替换。
5. **将回归测试带入插件。** 从实际面板完成提取、保存重开、编辑和 Generate Mod，核对未改动字节、UV 拆点、修改拓扑、1/2/4 权重、共享顶点色和拒绝非法权重。随后验证游戏中的静止、移动、阴影、远近 LOD、F11 切换及不同实例，并运行 EFMI/ZZMI 现有相关回归。

## 首版边界

提供 AP 组件提取、导入、编辑和原生管线导出。合并骨骼作为后续的导出模式，沿用项目保存的组件编号和原始骨骼索引。先采集同一角色各组件在同帧的 `cs-t2`，验证它们之间的索引对应关系，再决定映射和着色器。材质自动识别、角色分组、LOD 关联和形态键也需要各自的 AP 采样。槽位缓存继续暂缓，当前只做本地交付。

## 开始接入前

已向用户说明接入计划。独立实现是 LoyalTools 接入时的验证基线。
