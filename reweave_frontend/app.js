(function () {
  "use strict";

  var data = null;
  var selectedCapsuleId = null;
  var usedCapsuleIds = [];
  var appState = "idle";
  var isGenerating = false;
  var mainEventsBound = false;
  var locale = localStorage.getItem("reweave_locale") || "zh";
  var lastPreviewAcceptance = null;
  var ingestionManagement = {
    available: false,
    loaded: false,
    loading: false,
    refreshPending: false,
    projects: [],
    discovery: null,
    models: [],
    selectedModel: null,
    reviewItems: [],
    capabilityGroups: [],
    backups: [],
    recoverableProducts: [],
    historicalProducts: [],
    legacy: null,
    adapterOffers: {},
    captureResume: {},
    captureReviewContext: {},
    developerMode: false,
    sourceRoots: [],
    selectedSourceRootId: "",
    sourceRootSelectionStale: false,
    runs: {},
    errorKey: "",
  };
  var ingestionNavigation = {
    returnScene: "product",
    station: "source",
    focusId: "",
    specimen: null,
    productReview: null,
    sourceHandoffReview: null,
  };

  var STR = {
    zh: {
      privacy: "本地运行，数据不会离开此设备。",
      history: "本次会话",
      artifacts: "构建资料",
      welcomeKicker: "本地初始化 · 来源项目",
      welcomeTagline: "选择一个本地项目文件夹，完成只读来源绑定。",
      welcomePhilosophy: "这里只建立来源，不会发布或晋升胶囊。",
      sourceBox: "本地来源",
      bindSourceBox: "选择项目文件夹",
      sourceBoxNote: "扫描只读，不写入所选项目。",
      sourceBoxReadOnlyNote: "本地绑定、只读扫描，不写入源项目。",
      sourceBoxBindingDisabled: "来源箱绑定尚未开放。",
      viewCurrentRuntime: "查看当前运行状态",
      cleaningRuntime: "正在进行受控本地初始化",
      compatibilityTools: "兼容工具",
      quickCompose: "快速组合",
      compatibilityDisclaimer: "不经过正式计划确认，不构成独立产品交付。",
      compatibilityTitle: "兼容工具 / 快速组合",
      capsules: "胶囊",
      taskPlaceholder: "描述你想从旧项目重新织出的页面或工具…",
      taskPackPlaceholder: "描述你想生成的小项目包…",
      runtimePlaceholder: "源项目只读，本地预览可写",
      buildSmallProjectPack: "生成小项目包",
      generationInput: "生成输入",
      usedPlaceholder: "选中的胶囊会出现在这里",
      generationAuto: "请先选择至少一个可生成的正式胶囊。",
      generationManual: "已选择 {count} 个胶囊；本次生成只使用这些胶囊。",
      generationResolved: "系统已匹配 {count} 个胶囊。",
      draftsReadyStore: "胶囊草稿已就绪，请在来源箱中确认入仓。",
      selecting: "正在选择胶囊…",
      readyResponse: "已使用 {count} 个胶囊生成本地项目预览。",
      acceptanceUsable: "可用 · 交互行为已验证",
      acceptanceRealBootstrap: "真实 QWebEngine 已完成产品启动；完整交互仍需验收。",
      acceptanceNeedsBehavior: "需复核 · 未找到完整行为模块",
      acceptanceNeedsQuality: "需复核 · 质量检查结果缺失",
      acceptanceNeedsRuntime: "需复核 · 等待运行验证",
      acceptanceRejected: "已拒绝 · 质量检查未通过",
      acceptanceRejectedRuntime: "已拒绝 · 交互行为验证失败",
      generationFailed: "生成失败，请检查任务和胶囊状态。",
      taskPackUnavailable: "小项目包预览当前不可用。",
      localPreview: "本地预览",
      newTask: "新任务",
      docked: "已加入本次任务。",
      removeCapsule: "移除 {name}",
      formalSelectionInvalid: "所选正式胶囊无法组成同一项能力。",
      formalSelectionNeedsDomRole: "正式胶囊组合至少需要一个展示或交互角色。",
      useInTask: "用于任务",
      readOnly: "只读",
      sourceReadOnly: "源项目只读",
      capsulesUsed: "个胶囊已使用",
      readerLabel: "胶囊详情",
      fromSource: "来源",
      tagsPrefix: "标签",
      rolePrefix: "选用原因",
      preview: "预览",
      previewStatus: "预览状态",
      status: "状态",
      currentRuntime: "当前运行状态",
      runtime: "运行状态",
      smallProjectPack: "小项目包",
      runtimeArtifacts: "运行资料",
      runtimeTraceFiles: "胶囊使用记录 / 追溯凭证",
      workflow: "工作流",
      traceAvailable: "追溯可用",
      traceUnavailable: "追溯不可用",
      previewReady: "预览已就绪",
      previewNotReady: "预览未就绪",
      smallProjectPackReady: "小项目包已就绪",
      reactRuntimeVerified: "React 应用 · 运行已验证",
      reactPreviewAlt: "React 应用预览",
      capsulesLinked: "当前运行状态关联了 {count} 个胶囊",
      noCapsuleUsage: "当前运行状态未报告胶囊使用记录",
      productSummary: "产品能力：{capability} · 源项目写入：{writes} · 追溯：{trace}",
      capabilityReady: "就绪",
      capabilityReview: "需复核",
      capabilityUnavailable: "不可用",
      previewReadyNoAcceptance: "可生成小项目包预览 · 尚无历史验收 · 源项目写入：0",
      sourceWrites: "源项目写入",
      trace: "追溯",
      ready: "就绪",
      unavailable: "不可用",
      notReady: "未就绪",
      unknown: "未知",
      workflowViewProvenance: "查看来源记录",
      workflowBindSource: "绑定来源箱",
      workflowScanSource: "扫描来源箱",
      workflowStoreCapsules: "胶囊入仓",
      workflowBuildPack: "选择胶囊，然后生成小项目包",
      workflowIntentReady: "任务意图就绪 · 计划就绪 · 质量门通过 · 源项目写入 0",
      workflowIntentReview: "任务意图就绪 · 计划就绪 · 质量报告可查看 · 源项目写入 0",
      workflowQualityFailed: "任务意图就绪 · 计划就绪 · 质量门未通过 · 源项目写入 0",
      workflowPackReady: "小项目包就绪 · 源项目写入 0",
      viewPackage: "查看项目包",
      compareLast: "对比上次结果",
      sources: "来源箱",
      bound: "已绑定",
      addSource: "添加来源箱",
      lastUsed: "最近使用：2 天前",
      previewPackage: "预览项目包",
      close: "关闭",
      switchLanguage: "切换语言",
      noHistoryReadOnly: "暂无本地预览历史",
      noHistory: "暂无历史",
      historyMeta: "使用了 {count} 个胶囊 · {note}",
      scan: "扫描",
      refresh: "刷新",
      store: "入仓",
      prepare: "准备",
      sourcePreparing: "准备中…",
      sourceScanning: "扫描中…",
      sourceReady: "就绪",
      sourceScanned: "已扫描",
      sourceFailed: "失败",
      sourceNotScanned: "未扫描",
      artifactCopied: "构建资料路径已复制。",
      runtimeReadOnlyMessage: "源项目只读；本地预览写入已启用。",
      capsuleReadOnlyMessage: "该胶囊为只读状态。",
      loadFailed: "加载本地演示数据失败，请通过桌面程序或本地服务运行。",
      noPreviewPackage: "暂无预览项目包。",
      noPreviousPackage: "暂无可对比的历史项目包。",
      lunaPackIndexed: "Luna 索引已就绪",
      contentAwarePreview: "内容感知预览",
      snippets: "摘录",
      viewContent: "查看内容",
      enrichContent: "补充内容",
      copied: "已复制",
      enrichedContentPreview: "使用补充内容预览",
      capsuleWarehouse: "胶囊仓库",
      warehouseReadOnly: "只读正式来源",
      back: "返回",
      backToContext: "返回原位置",
      searchWarehouse: "搜索来源项目或胶囊",
      codeZoom: "代码字号",
      zoomOut: "缩小",
      zoomIn: "放大",
      resetCodeSize: "复位代码字号",
      sourceProjectOverview: "来源项目总览",
      formalSourceCount: "{count} 个正式来源",
      warehouseRackHelp: "胶囊仓库来源项目列表。使用 Tab 浏览，回车打开当前项目或胶囊。",
      warehouseEvidenceRail: "正式来源证据路径",
      exactVersion: "精确版本",
      noFormalCapsules: "暂无可浏览的正式胶囊。",
      warehouseLoadingRelations: "正在读取正式胶囊的来源关系……",
      noFormalSourceIdentity: "正式胶囊尚未提供可展示的来源项目身份。",
      insufficientSourceEvidence: "来源证据不足",
      sourceEvidenceShelf: "来源证据不足",
      unwovenSources: "未织入",
      sourceEvidenceShelfCopy: "这些正式胶囊尚不能唯一归入一个精确来源项目。",
      noVerifiedCoreCode: "暂无经验证的核心代码",
      warehouseManagement: "入库管理",
      warehouseLegend: "胶囊库能力图例",
      sourceProject: "来源项目",
      presentationCapability: "展示",
      interactionCapability: "交互",
      computationCapability: "计算",
      formalCapsuleCount: "{count} 个正式胶囊",
      sourceVerifiedShort: "来源已证明",
      searchResultCount: "{count} 个结果",
      searchNoResults: "没有结果；当前来源项目和焦点保持不变。",
      sourceFactVerified: "正式版本 · active · 精确来源已证明 · 验证通过",
      sourceFactInsufficient: "正式版本 · 来源证据不足",
      multipleExactSources: "存在多个精确项目来源，无法唯一归入一个来源项目。",
      missingExactSource: "缺少当前精确版本的项目来源关系。",
      missingFormalSource: "缺少可验证的正式项目来源身份。",
      planContextResolved: "已按计划中的精确胶囊、版本与摘要定位。",
      planContextMissing: "计划绑定无法唯一解析到正式来源；未选择近似版本。",
      validationPassedShort: "验证通过",
      validationIncompleteShort: "验证不足",
      emptyCapabilityLane: "暂无正式{kind}胶囊",
      formalContract: "正式契约",
      contractStatus: "契约状态",
      contractUnavailable: "当前精确版本的契约不可用。",
      contractEntrypoint: "入口",
      contractReceives: "接收",
      contractProduces: "产生",
      contractNoInput: "无输入",
      contractNoOutput: "无输出",
      viewVerifiedCodePath: "查看经验证代码：{path}",
      focusSpoolForEvidence: "聚焦线轴以抽取证据",
      showValidationEvidence: "显示验证证据",
      validationEvidence: "验证证据",
      rawEvidence: "原始证据 JSON",
      evidenceIdentity: "正式身份与能力",
      evidenceSource: "精确项目来源",
      evidenceContracts: "输入、输出、错误与运行契约",
      evidenceValidation: "验证与验收范围",
      evidenceEntry: "入口模块",
      evidenceAvailable: "验证通过",
      evidenceUnavailable: "证据不可用",
      warehousePurpose: "管理只读来源、提取候选、人工复核并发布正式胶囊。",
      developerMode: "开发者模式",
      developerModeHelp: "显示输入类型、枚举、复核 ID、备份和任务等开发信息。",
      formalSourceIntake: "来源入库",
      sourceIntakeReview: "来源入库与复核",
      intakeSourceContextLabel: "来源上下文",
      intakeSpecimenLabel: "当前检验标本",
      intakeSpecimenEmpty: "选择一个来源项目开始检验",
      intakeSpecimenSelected: "已选择检验对象；尚未改变正式状态",
      productReviewContext: "产品能力待复核",
      productReviewExact: "仅显示从当前产品任务接纳的指定待复核项",
      inspectSource: "检验此来源",
      showManagementAdvanced: "显示管理高级选项",
      intakeWorkstations: "来源入库工作站",
      sourceStation: "来源",
      supervisionStation: "监督",
      reviewStation: "待复核",
      formalStation: "正式能力",
      currentWorkstation: "当前工作站",
      supervisionRoleBoundary: "胶囊监督模型与产品规划模型是两个独立角色；这里不会自动选择模型。",
      managementAdvanced: "管理高级选项",
      deliveryMode: "交付模式",
      buildProduct: "构建产品",
      standaloneProduct: "独立产品",
      targetIntegration: "目标接入",
      targetReadOnly: "目标只读 · 仅审阅改动",
      targetKicker: "静态站点 · 只读改动审阅",
      targetTitle: "把正式胶囊接入现有站点",
      targetSubtitle: "分析一个明确的 HTML 入口，逐文件审查改动，再确认结果。Reweave 不写入目标项目。",
      zeroTargetWrites: "目标写入：0",
      chooseTarget: "选择目标",
      selectTargetFolder: "选择静态站点文件夹",
      noTargetSelected: "尚未选择目标",
      targetSelected: "已选择：{name}",
      targetEntry: "HTML 入口",
      analyzeTarget: "只读分析目标",
      targetAnalyzing: "正在只读分析目标……",
      targetProfileReady: "目标画像已就绪，来源快照未变化。",
      targetProfileRejected: "目标分析被拒绝：{code}",
      targetAnalysisError_entry_not_found: "找不到所选 HTML 入口。",
      targetAnalysisRecovery_entry_not_found: "请确认相对路径存在于目标文件夹内，然后再次只读分析。",
      targetAnalysisError_frontend_contract_rejected: "目标画像未通过前端契约校验。",
      targetAnalysisRecovery_frontend_contract_rejected: "请重新选择目标文件夹或检查 HTML 入口后重试。",
      targetAnalysisError_invalid_response: "目标分析返回了无效响应。",
      targetAnalysisRecovery_invalid_response: "请重新选择目标并再次只读分析。",
      targetAnalysisRecoveryGeneric: "请修正目标选择或 HTML 入口后重试只读分析。",
      targetPatchError_frontend_contract_rejected: "改动结果未通过前端契约校验。",
      targetPatchRecovery_frontend_contract_rejected: "请调整任务或正式胶囊选择后重新生成审阅改动。",
      targetPatchError_invalid_response: "改动生成返回了无效响应。",
      targetPatchRecovery_invalid_response: "请检查任务与胶囊选择后重新生成。",
      targetPatchRecoveryGeneric: "请调整任务或正式胶囊后重新生成审阅改动。",
      targetEntryRequired: "请填写目标根内的 HTML 相对路径。",
      targetSelectSummary: "入口 {entry} · 已完成只读分析",
      targetEntryPendingSummary: "入口 {entry} · 等待只读分析",
      composePatch: "组合改动",
      targetStageSelect: "选择目标",
      targetStageCompose: "组合审阅改动",
      targetStageReview: "审阅改动",
      targetStageConfirmed: "确认回执",
      targetComposeSummary: "{count} 个正式胶囊 · {task}",
      targetComposeSummaryOne: "1 个正式胶囊 · {task}",
      targetConfirmedTitle: "已确认审阅回执",
      showTechnicalEvidence: "显示技术证据",
      developerEvidence: "技术证据",
      targetTask: "希望加入什么？",
      targetTaskPlaceholder: "例如：加入报价计算器",
      chooseCapsules: "选择正式胶囊",
      targetNoCapsules: "暂无可生成的正式胶囊。",
      targetCapsuleRequired: "请选择 1–3 个同一能力的正式胶囊，并包含展示或交互角色。",
      targetTaskRequired: "请描述本次目标接入任务。",
      generateReviewPatch: "生成审阅改动",
      targetPatchGenerating: "正在生成只读审阅改动……",
      targetPatchReady: "改动已就绪；请审查全部文件和验证证据。",
      targetPatchRejected: "改动生成被拒绝：{code}",
      reviewPatch: "审查改动",
      confirmPatchBoundary: "确认只记录你已审查此结果，不会 apply、写入或 commit。",
      confirmPatch: "确认已审阅改动",
      targetConfirmed: "已确认 {plan}；目标写入仍为 0。",
      targetFileCount: "文件：{count}",
      targetResourceCount: "资源：{count}",
      targetChecksPassed: "验证：{passed}/{count}",
      targetSourceUnchanged: "目标快照未变化",
      targetTextDiff: "文本 Diff",
      targetBinaryDiff: "二进制文件仅显示元数据，不生成文本 Diff。",
      targetWriteZero: "review-only · apply 0 · commit 0 · target write 0",
      sourceProjects: "来源项目",
      discoverSource: "发现来源",
      discoverSourceHelp: "选择一个来源目录并只读发现其中的项目。",
      refreshAll: "全部刷新",
      refreshAllHelp: "重新扫描全部已登记来源；仅开发者模式显示。",
      supervisionModel: "监督模型",
      supervisionModelHelp: "选择本机 Ollama 模型；模型只做监督和命名，不决定代码边界。",
      refreshModelsHelp: "重新读取本机可用的监督模型。",
      saveModelHelp: "保存本次胶囊监督使用的模型和精确摘要。",
      saveBrandHelp: "保存当前项目的品牌继承、清除或替换设置。",
      selectModel: "选择模型",
      modelTimeoutNote: "已安装不等于已通过监督验证；冷启动或较大模型可能在固定超时后进入等待模型状态。",
      save: "保存",
      reviewItems: "待复核项",
      capabilityGroups: "能力分组",
      backupRestore: "备份与恢复",
      createBackup: "创建备份",
      importLegacy: "导入旧仓",
      intakeRuns: "入库任务",
      managementLoading: "正在载入胶囊仓库…",
      managementUnavailable: "胶囊仓库管理当前不可用。",
      managementReady: "胶囊仓库管理已就绪。",
      noItems: "暂无项目。",
      noReviews: "暂无待复核项。",
      noCapabilities: "暂无正式能力。",
      noBackups: "暂无备份。",
      noRuns: "暂无入库任务。",
      confirmProjects: "确认所选项目",
      brandMode: "品牌范围",
      brandInherit: "继承来源根配置",
      brandClear: "清除品牌",
      brandReplace: "替换品牌配置",
      brandProfile: "品牌配置 JSON",
      brandProfileInvalid: "品牌配置必须是 JSON 对象。",
      projectConfirmationPartial: "部分项目未能确认，请查看项目状态。",
      refreshProject: "刷新项目",
      authorizeSourceAgent: "授权 Agent 入库",
      authorizeSourceAgentHelp: "复制一次性绑定请求。只写 Reweave Intake 与 Review 状态，不写来源项目；关闭桌面后再启动梭子。",
      sourceAgentBindingCopied: "绑定请求已复制。请勿粘贴到聊天 Prompt；关闭桌面后写入梭子 stdin。",
      sourceAgentActive: "Agent 入库已授权；必须先关闭 Reweave Desktop，再启动梭子。",
      sourceAgentRevoked: "Agent 入库授权已撤销。",
      sourceAgentStale: "来源或正式状态已变化；旧授权不可继续使用。",
      sourceAgentConflict: "发现冲突的来源授权；已失败关闭。",
      revokeSourceAgent: "撤销 Agent 入库授权",
      reviewSourceAgent: "查看本次 Agent Review",
      sourceAgentReviewMissing: "未找到与本次 Agent 入库精确绑定的 Review；不会显示其他 Review。",
      source_handoff_request_invalid: "来源 Agent 授权请求无效。",
      source_handoff_clipboard_failed: "剪贴板写入失败，来源 Agent 授权已撤销。",
      source_handoff_clipboard_revoke_failed: "剪贴板写入失败，且授权撤销未能确认。请关闭梭子并刷新状态。",
      sourceDerivedAgentTitle: "交给 Agent 准备单文件计算提案",
      sourceDerivedAgentAuthorize: "授权 Agent 准备计算提案",
      sourceDerivedAgentActive: "授权已复制。请关闭 Reweave Desktop 后再启动梭子。",
      sourceDerivedAgentCopiedClose: "绑定已复制，请关闭 Reweave Desktop。",
      sourceDerivedAgentWaiting: "等待 Agent 准备提案。",
      sourceDerivedAgentApprove: "批准提案",
      sourceDerivedAgentReject: "拒绝提案",
      sourceDerivedAgentApproved: "提案已批准；请关闭 Desktop 后由 Agent 启动隔离运行。",
      sourceDerivedAgentRejected: "提案已拒绝，未调用模型。",
      sourceDerivedAgentRevoke: "撤销 Agent 授权",
      sourceDerivedAgentRevokeConfirm: "确认撤销本次 Agent 计算提案授权？",
      sourceDerivedAgentRevoked: "Agent 授权已撤销。",
      sourceDerivedAgentStale: "来源、模型或正式仓库已漂移；只能撤销。",
      sourceDerivedAgentConflict: "Agent 授权状态冲突；只能安全撤销。",
      sourceDerivedAgentModelNotice: "批准后仍不会调用模型；Agent 启动时才会各调用一次源码模型和监督模型。",
      source_derived_handoff_clipboard_failed: "剪贴板写入失败，授权已撤销。",
      source_derived_handoff_clipboard_revoke_failed: "剪贴板写入失败且撤销未确认。请保持梭子关闭并刷新。",
      sourceDerivedTitle: "从单一证据文件生成隔离计算提案",
      sourceDerivedNotice: "将分别调用一次冻结源码提案模型和监督模型；失败后不会自动重试。本次只生成隔离 Review，不写正式能力仓库。",
      sourceDerivedRelpath: "JS/TS 证据文件相对路径",
      sourceDerivedBehavior: "行为说明",
      sourceDerivedInputField: "输入字段",
      sourceDerivedInputMin: "输入最短长度",
      sourceDerivedInputMax: "输入最长长度",
      sourceDerivedResultField: "输出字段",
      sourceDerivedEnum: "输出枚举（每行一个）",
      sourceDerivedCases: "业务验收例",
      sourceDerivedCaseInput: "输入文本",
      sourceDerivedCaseExpected: "期望枚举结果",
      sourceDerivedAddCase: "增加验收例",
      sourceDerivedRemoveCase: "移除此验收例",
      sourceDerivedStart: "授权并生成隔离能力提案",
      sourceDerivedReviewReady: "隔离验证已通过并到达 review_required；尚未正式接纳或发布。",
      source_derivation_request_invalid: "单文件来源授权信息无效。",
      source_derivation_evidence_invalid: "证据文件不安全、不可读取、超限或包含疑似秘密。",
      source_derivation_run_stale: "来源、模型或正式 catalog 已变化；运行已失败关闭。",
      registerJavascriptSource: "登记 JavaScript 计算来源",
      registerJavascriptSourceHelp: "把所选来源根或子目录登记为只读 JavaScript 计算来源。",
      javascriptSourceRoot: "来源根",
      javascriptSourceRootHelp: "选择已经绑定的只读来源目录。",
      sourceRootSelectionRequired: "请选择来源根。",
      sourceRootSelectionStale: "先前选择的来源根已不可用，请重新选择；未改用其他来源。",
      javascriptProjectRelpath: "项目或子目录（. 表示整个来源根）",
      javascriptProjectRelpathHelp: "限定计算函数扫描范围；不会修改该目录。",
      javascriptDisplayName: "计算来源名称",
      javascriptDisplayNameHelp: "给此计算来源一个便于识别的本地名称；留空时使用目录名。",
      javascriptSourceType: "JavaScript 计算来源",
      staticWebSourceType: "静态网页来源",
      unknownSourceType: "未知来源类型",
      refreshProjectHelp: "重新只读扫描这个来源项目。",
      scanJavascriptComputations: "查找可复用的计算功能",
      scanJavascriptComputationsHelp: "只读检查这个项目中的 JavaScript 函数。不会运行、修改或构建来源项目，也不会立即发布胶囊。",
      scanJavascriptRunning: "正在只读分析 JavaScript 函数……",
      scanJavascriptFound: "找到 {count} 个可进一步验证的计算功能。",
      noJavascriptComputations: "没有找到符合当前安全范围的纯计算函数。来源项目没有被修改。",
      projectScanReady: "已准备好，可以只读查找计算功能。",
      projectScanPending: "项目尚未确认，请先确认来源项目。",
      projectScanSourceMissing: "来源目录当前不可访问，请重新选择原目录。",
      projectScanStaticUnsupported: "不能作为 Static Web 提取，但可以尝试查找纯计算函数。",
      projectScanPlatformUnsupported: "当前平台不支持旧 JavaScript 计算抓取；没有读取来源。",
      projectScanIncomplete: "项目记录不完整，请重新发现或登记该项目。",
      projectScanUnknownType: "来源类型无法识别，请重新发现或登记该项目。",
      projectScanUnknownState: "项目状态未知，请刷新项目列表后重试。",
      adapterInputKind: "输入类型",
      adapterInputKindHelp: "简单模式固定为整数；布尔、枚举和有界字符串只在开发者模式配置。",
      adapterEnumValues: "枚举值（每行一个）",
      adapterEnumValuesHelp: "列出允许的精确字符串值，每行一个。",
      captureNeedsDecision: "等待你的安全确认；模型监督和运行验证尚未执行。",
      captureResubmitRequired: "决定已保存。返回原函数并点击“继续验证”，系统会从当前来源重新构建。",
      captureResumeReview: "恢复待确认项（可选）",
      captureResumeReviewHelp: "开发者恢复入口；普通流程会自动关联当前待确认项。",
      adapterCreationPathRetired: "旧版计算入口已退役，请重新扫描计算功能。",
      adapterContractVersionExpired: "旧版候选已过期，请重新扫描。不能继续处理或发布这个旧候选。",
      adapterInputField: "输入字段",
      adapterInputFieldHelp: "产品使用的字段名；例如旧参数 x 可以映射为 quantity。",
      adapterInputSourceLabel: "输入 {index}（源码参数：{parameter}）",
      adapterInputFieldVisibleHelp: "这是该输入在新产品中的名称。例如 quantity 可以表示数量。",
      adapterMinimum: "最小值",
      adapterMinimumHelp: "该输入允许的最小安全整数。必须依据实际业务填写。",
      adapterMaximum: "最大值",
      adapterMaximumHelp: "该输入允许的最大安全整数。必须依据实际业务填写。",
      adapterMinimumLength: "最短长度",
      adapterMaximumLength: "最长长度",
      adapterResultEnum: "输出枚举（每行一个）",
      adapterResultEnumHelp: "列出计算函数允许返回的全部精确字符串值，每行一个。",
      adapterWitness: "{value} 的验收输入",
      adapterWitnessHelp: "该输入必须让旧函数精确返回对应枚举值，并满足声明的 UTF-16 长度边界。",
      adapterResultField: "输出字段",
      adapterResultFieldHelp: "产品接收计算结果时使用的字段名，例如 total。",
      adapterResultFieldVisibleHelp: "这是计算结果在新产品中的名称。例如 total 可以表示总价。",
      adapterExample: "业务样例",
      adapterExampleHelp: "填写一组你知道正确的输入，值必须位于声明范围内。",
      adapterExpected: "期望结果",
      adapterExpectedHelp: "旧函数处理上方业务样例时应得到的真实整数结果。",
      adapterSimpleHelp: "旧参数映射为产品字段；范围是允许输入；业务样例和期望结果用于核对真实函数。",
      adapterMappingPreview: "将提交：{mapping}",
      adapterMappingConfirmation: "我确认这里只证明参数映射与指定样例，不代表完全等价。",
      adapterMappingConfirmShort: "我确认",
      createComputationAdapter: "创建计算胶囊候选",
      continueCaptureValidation: "继续验证",
      adapterMappingInvalid: "请填写合法、唯一的字段、边界、枚举与逐枚举验收输入。",
      adapterInspectionComplete: "计算函数检查完成。",
      adapterCandidateCreated: "计算胶囊候选已创建，请继续复核。",
      captureWaitingModel: "等待本地监督模型；尚未完成验证。",
      captureWaitingValidation: "等待 Node 运行验证；尚未入仓。",
      captureRejected: "候选已拒绝，没有写入正式胶囊仓库。",
      captureReviewRequired: "安全、模型和运行验证已通过，等待发布复核。",
      captureDuplicate: "已确认与当前正式版本精确重复，并关联来源。",
      captureOutcomeUnknown: "候选返回了无法识别的状态，已停止。",
      captureOfferStale: "来源或函数列表已变化，请重新扫描后再提交。",
      captureExampleMismatch: "业务样例与旧函数的真实结果不一致，请核对输入和期望结果。",
      captureSourceChanged: "扫描期间来源发生变化；未保存候选，请重新扫描。",
      captureWorkerTimeout: "计算验证超时；未保存候选，请检查函数范围后重试。",
      captureSecurityRejected: "函数未通过安全边界，未保存候选。开发者模式可查看诊断。",
      captureRequestInvalid: "提交信息不完整或已过期，请重新扫描并填写。",
      managementOperationFailed: "操作未完成；没有写入正式胶囊。请重试或在开发者模式查看诊断。",
      reviewStatusWaitingUser: "等待用户确认",
      reviewStatusWaitingModel: "等待模型",
      reviewStatusWaitingValidation: "等待运行验证",
      reviewStatusReviewRequired: "等待发布复核",
      reviewStatusDuplicate: "精确重复",
      reviewStatusRejected: "已拒绝",
      captureReview: "计算函数安全确认",
      captureSafetySummary: "安全扫描：模糊项 {ambiguous}，品牌项 {brand}，枚举参数 {enums}。",
      capabilityKeyLabel: "能力标识",
      capabilityKeyHelp: "同一完整能力共享的稳定 snake_case 标识，例如 quote_calculation。",
      roleKeyLabel: "角色标识",
      roleKeyHelp: "该原子胶囊在能力中的稳定角色标识，例如 total_price。",
      variantKeyLabel: "变体标识",
      variantKeyHelp: "同一角色不同实现的稳定标识；首个通常为 default。",
      displayNameLabel: "展示名称",
      displayNameHelp: "仅用于界面展示，可在发布后修改。",
      retainedVersionLabel: "保留的正式版本",
      retainedVersionHelp: "选择人工确认后继续保留的现有正式版本。",
      targetCapsuleLabel: "目标胶囊",
      targetCapsuleHelp: "选择要替换或作为语义拆分来源的现有胶囊。",
      decisionConfirmFictional: "虚构样例",
      decisionConfirmFictionalHelp: "仅在你确认命中内容不是客户或其他真实记录时使用。",
      decisionRejectRealRecord: "真实记录：拒绝",
      decisionRejectRealRecordHelp: "确认包含真实记录并终止此候选，不会写入正式仓库。",
      decisionConfirmSafeRedaction: "确认脱敏",
      decisionConfirmSafeRedactionHelp: "确认清洗后的候选不再包含真实记录。",
      decisionRetainBrand: "品牌限定",
      decisionRetainBrandHelp: "仅允许当前品牌配置使用此胶囊。",
      decisionRemoveBrand: "移除品牌",
      decisionRemoveBrandHelp: "按当前清洗规则移除品牌内容后重新处理。",
      decisionConfirmEnum: "确认枚举",
      decisionConfirmEnumHelp: "确认这些字符串是业务枚举，不是真实记录。",
      decisionConfirmAssets: "确认图片",
      decisionConfirmAssetsHelp: "人工确认图片像素中不含客户截图或其他真实记录。",
      decisionPublishGeneral: "发布（通用）",
      decisionPublishGeneralHelp: "以当前身份发布，可用于符合契约的产品。",
      decisionPublishBrand: "发布（品牌）",
      decisionPublishBrandHelp: "以当前身份发布，仅供当前品牌范围使用。",
      decisionCreateVariant: "新建变体",
      decisionCreateVariantHelp: "保留现有实现，并把当前实现发布为另一个变体。",
      decisionMergeExisting: "合并现有",
      decisionMergeExistingHelp: "人工确认等价关系，默认保留现有正式实现。",
      decisionReplaceCurrent: "替换当前",
      decisionReplaceCurrentHelp: "发布不可变新版本，并切换当前正式版本。",
      decisionSemanticSplit: "拆分身份",
      decisionSemanticSplitHelp: "把当前候选作为新的能力身份发布，旧身份不删除。",
      decisionReject: "拒绝",
      decisionRejectHelp: "终止当前候选，不写入正式胶囊仓库。",
      decisionProcessCandidate: "继续验证",
      decisionProcessCandidateHelp: "继续现有安全、模型和运行验证；不会自动发布。",
      createBackupHelp: "备份当前本地胶囊仓库、品牌配置和使用历史。",
      importLegacyHelp: "逐条重新清洗旧仓内容；不会直接信任或恢复旧实现。",
      restoreHelp: "把整个本地胶囊仓库恢复到所选备份时点。",
      mapLegacyHelp: "把旧胶囊记录关联到已人工确认的正式版本。",
      retryUsageHelp: "重新核对产品 manifest 并登记其精确胶囊版本。",
      cancelRunHelp: "请求取消当前后台任务；已提交的完整事务不会被拆开。",
      renameCapabilityHelp: "只修改展示名称，不改变稳定能力标识。",
      viewDetailsHelp: "查看此胶囊的当前正式版本摘要。",
      disableCapsuleHelp: "停用当前胶囊；历史版本不会被物理删除。",
      enableCapsuleHelp: "重新启用已验证且规则仍有效的当前胶囊。",
      cancelRun: "取消",
      restore: "恢复",
      viewDetails: "查看详情",
      renameCapability: "修改名称",
      renameCapabilityPrompt: "输入新的能力展示名称",
      manifestDigest: "Manifest 摘要",
      preRestoreBackup: "恢复前备份",
      backupAvailable: "可用",
      backupUnavailable: "不可用",
      disableCapsule: "停用",
      enableCapsule: "启用",
      restoreConfirm: "恢复会把本地仓库回退到该备份时点。是否继续？",
      decisionSaved: "决定已保存。",
      modelSaved: "监督模型已保存。",
      backupCreated: "备份已创建。",
      retryUsage: "补登记产品记录",
      usageRetryComplete: "产品使用记录已补登记。",
      restoreComplete: "仓库恢复完成。",
      importStarted: "旧仓重新清洗任务已启动。",
      legacyNotFound: "未发现旧胶囊仓。",
      legacyWarehouse: "旧胶囊仓",
      legacyAliases: "迁移关系",
      legacyPending: "待人工映射",
      legacyRelationship: "关系",
      legacyTarget: "新胶囊版本",
      mapLegacy: "确认映射",
      warnings: "警告",
      truncated: "已截断",
      redacted: "已脱敏",
      verify: "验证",
      review: "复核",
      promote: "提升",
      approve: "通过",
      reject: "拒绝",
      defer: "稍后处理",
      promoted: "已提升",
      pending: "待处理",
      approved: "已通过",
      rejected: "已拒绝",
      deferred: "已延后",
    },
    en: {
      privacy: "All local. Nothing leaves your machine.",
      history: "Session history",
      artifacts: "Build notes",
      welcomeKicker: "Local initialization · Source project",
      welcomeTagline: "Choose a local project folder and bind it as a read-only source.",
      welcomePhilosophy: "This establishes provenance only; it does not publish or promote capsules.",
      sourceBox: "Local source",
      bindSourceBox: "Choose project folder",
      sourceBoxNote: "The scan is read-only and never writes the selected project.",
      sourceBoxReadOnlyNote: "Bind locally, scan read-only, no source writes.",
      sourceBoxBindingDisabled: "Source Box binding is not enabled.",
      viewCurrentRuntime: "View Current Runtime",
      cleaningRuntime: "Running controlled local initialization",
      compatibilityTools: "Compatibility tools",
      quickCompose: "Quick compose",
      compatibilityDisclaimer: "Does not pass formal plan confirmation and is not a standalone product delivery.",
      compatibilityTitle: "Compatibility tools / Quick compose",
      capsules: "Capsules",
      taskPlaceholder: "Describe the tool or page to reweave...",
      taskPackPlaceholder: "Describe a small project pack...",
      runtimePlaceholder: "Source project read-only; local preview enabled",
      buildSmallProjectPack: "Build Small Project Pack",
      generationInput: "Generation input",
      usedPlaceholder: "Selected capsules dock here",
      generationAuto: "Select at least one eligible formal capsule before generating.",
      generationManual: "Generation input: {count} selected. Generate will use exactly these capsules.",
      generationResolved: "Reweave matched {count} capsules.",
      draftsReadyStore: "Capsule drafts are ready. Review the Source Box and store them.",
      selecting: "Reweave is selecting capsules…",
      readyResponse: "Reweave used {count} capsules and prepared a local preview package.",
      acceptanceUsable: "Usable · Interaction verified",
      acceptanceRealBootstrap: "Product bootstrapped in real QWebEngine; full interaction still needs review.",
      acceptanceNeedsBehavior: "Needs review · No closed behavior module",
      acceptanceNeedsQuality: "Needs review · Quality result missing",
      acceptanceNeedsRuntime: "Needs review · Runtime validation required",
      acceptanceRejected: "Rejected · Quality check failed",
      acceptanceRejectedRuntime: "Rejected · Interaction validation failed",
      generationFailed: "Generation failed. Check the task and capsule state.",
      taskPackUnavailable: "Task Pack preview is unavailable.",
      localPreview: "local preview",
      newTask: "New task",
      docked: "docked for this task.",
      removeCapsule: "Remove {name}",
      formalSelectionInvalid: "The selected formal capsules cannot form one capability.",
      formalSelectionNeedsDomRole: "A formal selection needs at least one presentation or interaction role.",
      useInTask: "Use in task",
      readOnly: "Read-only",
      sourceReadOnly: "Source project read-only",
      capsulesUsed: "capsules used",
      readerLabel: "Capsule Reader",
      fromSource: "from",
      tagsPrefix: "tags",
      rolePrefix: "role",
      preview: "Preview",
      previewStatus: "Preview status",
      status: "Status",
      currentRuntime: "Current Runtime",
      runtime: "Runtime",
      smallProjectPack: "Small Project Pack",
      runtimeArtifacts: "Runtime artifacts",
      runtimeTraceFiles: "capsules_used / trace receipts",
      workflow: "Workflow",
      traceAvailable: "Trace available",
      traceUnavailable: "Trace unavailable",
      previewReady: "Preview ready",
      previewNotReady: "Preview not ready",
      smallProjectPackReady: "Small Project Pack ready",
      reactRuntimeVerified: "React app · Runtime verified",
      reactPreviewAlt: "React app preview",
      capsulesLinked: "{count} capsules linked to this runtime",
      noCapsuleUsage: "No capsule usage reported by current runtime",
      productSummary: "Product capability: {capability} · Source writes: {writes} · Trace: {trace}",
      capabilityReady: "ready",
      capabilityReview: "review",
      capabilityUnavailable: "unavailable",
      previewReadyNoAcceptance: "Task Pack preview available · No acceptance history yet · Source writes: 0",
      sourceWrites: "source writes",
      trace: "trace",
      ready: "ready",
      unavailable: "unavailable",
      notReady: "not ready",
      unknown: "unknown",
      workflowViewProvenance: "View provenance",
      workflowBindSource: "Bind Source Box",
      workflowScanSource: "Scan Source Box",
      workflowStoreCapsules: "Store Capsules",
      workflowBuildPack: "Select capsules, then Build Small Project Pack",
      workflowIntentReady: "Intent ready · Plan ready · Quality gate passed · Source writes 0",
      workflowIntentReview: "Intent ready · Plan ready · Quality report available · Source writes 0",
      workflowQualityFailed: "Intent ready · Plan ready · Quality gate failed · Source writes 0",
      workflowPackReady: "Task Pack ready · Source writes 0",
      viewPackage: "View package",
      compareLast: "Compare last",
      sources: "Sources",
      bound: "bound",
      addSource: "Add source",
      lastUsed: "Last used 2d ago",
      previewPackage: "Preview package",
      close: "Close",
      switchLanguage: "Switch language",
      noHistoryReadOnly: "No local preview history yet",
      noHistory: "No history yet",
      historyMeta: "used {count} capsules · {note}",
      scan: "Scan",
      refresh: "Refresh",
      store: "Store",
      prepare: "Prepare",
      sourcePreparing: "Preparing…",
      sourceScanning: "Scanning…",
      sourceReady: "Ready",
      sourceScanned: "Scanned",
      sourceFailed: "Failed",
      sourceNotScanned: "Not scanned",
      artifactCopied: "Artifact path copied.",
      runtimeReadOnlyMessage: "Source project read-only; local preview writes enabled.",
      capsuleReadOnlyMessage: "This capsule is read-only.",
      loadFailed: "Failed to load local demo data. Run the desktop app or a local server.",
      noPreviewPackage: "No preview package is available.",
      noPreviousPackage: "No previous package is available.",
      lunaPackIndexed: "Luna pack indexed",
      contentAwarePreview: "Content-aware preview",
      snippets: "Snippets",
      viewContent: "View content",
      enrichContent: "Enrich content",
      copied: "Copied",
      enrichedContentPreview: "Use enriched content preview",
      capsuleWarehouse: "Capsule Warehouse",
      warehouseReadOnly: "READ-ONLY FORMAL SOURCES",
      back: "Back",
      backToContext: "Back to context",
      searchWarehouse: "Search source projects or capsules",
      codeZoom: "Code size",
      zoomOut: "Zoom out",
      zoomIn: "Zoom in",
      resetCodeSize: "Reset code size",
      sourceProjectOverview: "Source project overview",
      formalSourceCount: "{count} formal sources",
      warehouseRackHelp: "Capsule Warehouse source projects. Use Tab to browse and Enter to open the current project or capsule.",
      warehouseEvidenceRail: "Formal source evidence path",
      exactVersion: "Exact version",
      noFormalCapsules: "No formal capsules are available to browse.",
      warehouseLoadingRelations: "Loading formal capsule source relationships…",
      noFormalSourceIdentity: "Formal capsules do not provide a displayable source project identity.",
      insufficientSourceEvidence: "Insufficient source evidence",
      sourceEvidenceShelf: "Source evidence insufficient",
      unwovenSources: "Unwoven",
      sourceEvidenceShelfCopy: "These formal capsules cannot yet be assigned to one exact source project.",
      noVerifiedCoreCode: "No verified core code is available.",
      warehouseManagement: "Ingestion management",
      warehouseLegend: "Capsule library capability legend",
      sourceProject: "Source project",
      presentationCapability: "Presentation",
      interactionCapability: "Interaction",
      computationCapability: "Computation",
      formalCapsuleCount: "{count} formal capsules",
      sourceVerifiedShort: "Source proven",
      searchResultCount: "{count} results",
      searchNoResults: "No results; the current source projects and focus are unchanged.",
      sourceFactVerified: "Formal version · active · exact source proven · validation passed",
      sourceFactInsufficient: "Formal version · insufficient source evidence",
      multipleExactSources: "Multiple exact project sources prevent a unique source assignment.",
      missingExactSource: "The current exact version has no project source relationship.",
      missingFormalSource: "No verifiable formal project source identity is available.",
      planContextResolved: "Located by the plan's exact capsule, version, and digest.",
      planContextMissing: "The plan binding does not resolve to one formal source; no approximate version was selected.",
      validationPassedShort: "Validation passed",
      validationIncompleteShort: "Validation incomplete",
      emptyCapabilityLane: "No formal {kind} capsules",
      formalContract: "Formal contract",
      contractStatus: "Contract status",
      contractUnavailable: "The exact version contract is unavailable.",
      contractEntrypoint: "Entrypoint",
      contractReceives: "Receives",
      contractProduces: "Produces",
      contractNoInput: "No input",
      contractNoOutput: "No output",
      viewVerifiedCodePath: "View verified code: {path}",
      focusSpoolForEvidence: "Focus a spool to extract evidence",
      showValidationEvidence: "Show validation evidence",
      validationEvidence: "Validation evidence",
      rawEvidence: "Raw evidence JSON",
      evidenceIdentity: "Formal identity and capability",
      evidenceSource: "Exact project source",
      evidenceContracts: "Input, output, error, and runtime contracts",
      evidenceValidation: "Validation and acceptance scope",
      evidenceEntry: "Entry module",
      evidenceAvailable: "Validation passed",
      evidenceUnavailable: "Evidence unavailable",
      warehousePurpose: "Manage read-only sources, capture candidates, review them, and publish formal capsules.",
      developerMode: "Developer mode",
      developerModeHelp: "Show input types, enums, review IDs, backups, and task diagnostics.",
      formalSourceIntake: "Source intake",
      sourceIntakeReview: "Source intake and review",
      intakeSourceContextLabel: "Source context",
      intakeSpecimenLabel: "Current inspection specimen",
      intakeSpecimenEmpty: "Choose a source project to begin inspection",
      intakeSpecimenSelected: "Inspection target selected; formal state is unchanged",
      productReviewContext: "Product capability review",
      productReviewExact: "Showing only the review admitted from this product task",
      inspectSource: "Inspect this source",
      showManagementAdvanced: "Show management advanced options",
      intakeWorkstations: "Source intake workstations",
      sourceStation: "Sources",
      supervisionStation: "Supervision",
      reviewStation: "To review",
      formalStation: "Formal capabilities",
      currentWorkstation: "Current workstation",
      supervisionRoleBoundary: "Capsule supervision and product planning are separate roles; no model is selected automatically here.",
      managementAdvanced: "Management advanced options",
      deliveryMode: "Delivery mode",
      buildProduct: "Build product",
      standaloneProduct: "Standalone product",
      targetIntegration: "Target integration",
      targetReadOnly: "Target read-only · Review-only Patch",
      targetKicker: "STATIC WEB · REVIEW-ONLY PATCH",
      targetTitle: "Integrate formal capsules into an existing site",
      targetSubtitle: "Analyze one explicit HTML entry, review every file change, then confirm the result. Reweave never writes the target project.",
      zeroTargetWrites: "Target writes: 0",
      chooseTarget: "Choose target",
      selectTargetFolder: "Select Static Web folder",
      noTargetSelected: "No target selected",
      targetSelected: "Selected: {name}",
      targetEntry: "HTML entry",
      analyzeTarget: "Analyze target read-only",
      targetAnalyzing: "Analyzing the target read-only…",
      targetProfileReady: "Target profile ready; the source snapshot is unchanged.",
      targetProfileRejected: "Target analysis rejected: {code}",
      targetAnalysisError_entry_not_found: "The selected HTML entry was not found.",
      targetAnalysisRecovery_entry_not_found: "Confirm the relative path exists in the target folder, then analyze read-only again.",
      targetAnalysisError_frontend_contract_rejected: "The target profile failed the frontend contract checks.",
      targetAnalysisRecovery_frontend_contract_rejected: "Reselect the target folder or check the HTML entry, then retry.",
      targetAnalysisError_invalid_response: "Target analysis returned an invalid response.",
      targetAnalysisRecovery_invalid_response: "Reselect the target and analyze read-only again.",
      targetAnalysisRecoveryGeneric: "Fix the target selection or HTML entry, then retry read-only analysis.",
      targetPatchError_frontend_contract_rejected: "The Patch failed the frontend contract checks.",
      targetPatchRecovery_frontend_contract_rejected: "Adjust the task or formal capsule selection, then generate the review Patch again.",
      targetPatchError_invalid_response: "Patch generation returned an invalid response.",
      targetPatchRecovery_invalid_response: "Check the task and capsule selection, then generate again.",
      targetPatchRecoveryGeneric: "Adjust the task or formal capsules, then generate the review Patch again.",
      targetEntryRequired: "Enter an HTML path relative to the target root.",
      targetSelectSummary: "Entry {entry} · read-only analysis complete",
      targetEntryPendingSummary: "Entry {entry} · waiting for read-only analysis",
      composePatch: "Compose Patch",
      targetStageSelect: "Select target",
      targetStageCompose: "Compose review Patch",
      targetStageReview: "Review Patch",
      targetStageConfirmed: "Review receipt",
      targetComposeSummary: "{count} formal capsules · {task}",
      targetComposeSummaryOne: "1 formal capsule · {task}",
      targetConfirmedTitle: "Patch review confirmed",
      showTechnicalEvidence: "Show technical evidence",
      developerEvidence: "Technical evidence",
      targetTask: "What should be added?",
      targetTaskPlaceholder: "For example: add a quote calculator",
      chooseCapsules: "Choose formal capsules",
      targetNoCapsules: "No generation-eligible formal capsules are available.",
      targetCapsuleRequired: "Choose 1–3 formal capsules for one capability, including a presentation or interaction role.",
      targetTaskRequired: "Describe this target integration task.",
      generateReviewPatch: "Generate review Patch",
      targetPatchGenerating: "Generating a review-only Patch…",
      targetPatchReady: "Patch ready; review every file and all validation evidence.",
      targetPatchRejected: "Patch generation rejected: {code}",
      reviewPatch: "Review Patch",
      confirmPatchBoundary: "Confirmation records that you reviewed this result. It does not apply, write, or commit anything.",
      confirmPatch: "Confirm reviewed Patch",
      targetConfirmed: "Confirmed {plan}; target writes remain 0.",
      targetFileCount: "Files: {count}",
      targetResourceCount: "Resources: {count}",
      targetChecksPassed: "Validation: {passed}/{count}",
      targetSourceUnchanged: "Target snapshot unchanged",
      targetTextDiff: "Text Diff",
      targetBinaryDiff: "Binary file: metadata only; no text Diff is rendered.",
      targetWriteZero: "review-only · apply 0 · commit 0 · target write 0",
      sourceProjects: "Source projects",
      discoverSource: "Discover source",
      discoverSourceHelp: "Choose a source directory and discover projects read-only.",
      refreshAll: "Refresh all",
      refreshAllHelp: "Rescan every registered source; shown only in developer mode.",
      supervisionModel: "Supervision model",
      supervisionModelHelp: "Choose a local Ollama model; it supervises and names but never chooses code boundaries.",
      refreshModelsHelp: "Reload locally available supervision models.",
      saveModelHelp: "Save the model and exact digest used for capsule supervision.",
      saveBrandHelp: "Save this project's inherited, cleared, or replacement brand settings.",
      selectModel: "Select a model",
      modelTimeoutNote: "Installed does not mean supervision-verified; cold or large models may enter waiting-model after the fixed timeout.",
      save: "Save",
      reviewItems: "Review items",
      capabilityGroups: "Capability groups",
      backupRestore: "Backup and restore",
      createBackup: "Create backup",
      importLegacy: "Import legacy warehouse",
      intakeRuns: "Intake runs",
      managementLoading: "Loading Capsule Warehouse…",
      managementUnavailable: "Capsule Warehouse management is unavailable.",
      managementReady: "Capsule Warehouse management is ready.",
      noItems: "No projects.",
      noReviews: "No review items.",
      noCapabilities: "No formal capabilities.",
      noBackups: "No backups.",
      noRuns: "No intake runs.",
      confirmProjects: "Confirm selected projects",
      brandMode: "Brand scope",
      brandInherit: "Inherit source-root profile",
      brandClear: "Remove brand",
      brandReplace: "Replace brand profile",
      brandProfile: "Brand profile JSON",
      brandProfileInvalid: "Brand profile must be a JSON object.",
      projectConfirmationPartial: "Some projects could not be confirmed; review their status.",
      refreshProject: "Refresh project",
      authorizeSourceAgent: "Authorize Agent intake",
      authorizeSourceAgentHelp: "Copy a one-time binding request. It writes only Reweave Intake and Review state, never the source project; close Desktop before starting the shuttle.",
      sourceAgentBindingCopied: "The binding request was copied. Do not paste it into a chat prompt; close Desktop, then write it to the shuttle stdin.",
      sourceAgentActive: "Agent intake is authorized. Close Reweave Desktop before starting the shuttle.",
      sourceAgentRevoked: "Agent intake authorization was revoked.",
      sourceAgentStale: "The source or formal state changed; the old authorization cannot be used.",
      sourceAgentConflict: "Conflicting source authorizations were found and failed closed.",
      revokeSourceAgent: "Revoke Agent intake",
      reviewSourceAgent: "View this Agent review",
      sourceAgentReviewMissing: "No Review is bound to this exact Agent intake; unrelated Reviews are not shown.",
      source_handoff_request_invalid: "The source Agent authorization request is invalid.",
      source_handoff_clipboard_failed: "Clipboard write failed and the source Agent authorization was revoked.",
      source_handoff_clipboard_revoke_failed: "Clipboard write failed and revocation could not be confirmed. Keep the Shuttle closed and refresh state.",
      sourceDerivedAgentTitle: "Let an Agent prepare a one-file computation proposal",
      sourceDerivedAgentAuthorize: "Authorize Agent to prepare proposal",
      sourceDerivedAgentActive: "Authorization copied. Close Reweave Desktop before starting the Shuttle.",
      sourceDerivedAgentCopiedClose: "Binding copied. Close Reweave Desktop.",
      sourceDerivedAgentWaiting: "Waiting for the Agent to prepare a proposal.",
      sourceDerivedAgentApprove: "Approve proposal",
      sourceDerivedAgentReject: "Reject proposal",
      sourceDerivedAgentApproved: "Proposal approved. Close Desktop before the Agent starts the isolated run.",
      sourceDerivedAgentRejected: "Proposal rejected; no model was called.",
      sourceDerivedAgentRevoke: "Revoke Agent authorization",
      sourceDerivedAgentRevokeConfirm: "Revoke this Agent computation-proposal authorization?",
      sourceDerivedAgentRevoked: "Agent authorization revoked.",
      sourceDerivedAgentStale: "The source, model, or formal warehouse drifted; only revocation is allowed.",
      sourceDerivedAgentConflict: "Agent authorization state conflicts; only safe revocation is allowed.",
      sourceDerivedAgentModelNotice: "Approval still does not call a model. The Agent run later calls the source model and supervisor once each.",
      source_derived_handoff_clipboard_failed: "Clipboard write failed and the authorization was revoked.",
      source_derived_handoff_clipboard_revoke_failed: "Clipboard write failed and revocation was not confirmed. Keep the Shuttle closed and refresh.",
      sourceDerivedTitle: "Generate an isolated computation from one evidence file",
      sourceDerivedNotice: "This calls the frozen source-proposal model once and the supervisor once. Failures are not retried. It creates only an isolated Review and does not write the formal capability warehouse.",
      sourceDerivedRelpath: "Relative JS/TS evidence path",
      sourceDerivedBehavior: "Behavior intent",
      sourceDerivedInputField: "Input field",
      sourceDerivedInputMin: "Minimum input length",
      sourceDerivedInputMax: "Maximum input length",
      sourceDerivedResultField: "Result field",
      sourceDerivedEnum: "Result enum (one per line)",
      sourceDerivedCases: "Acceptance cases",
      sourceDerivedCaseInput: "Input text",
      sourceDerivedCaseExpected: "Expected enum result",
      sourceDerivedAddCase: "Add acceptance case",
      sourceDerivedRemoveCase: "Remove this acceptance case",
      sourceDerivedStart: "Authorize and generate isolated capability proposal",
      sourceDerivedReviewReady: "Isolated validation reached review_required; no formal admission or publication occurred.",
      source_derivation_request_invalid: "The one-file source authorization is invalid.",
      source_derivation_evidence_invalid: "The evidence file is unsafe, unreadable, oversized, or contains a possible secret.",
      source_derivation_run_stale: "The source, model, or formal catalog changed; the run failed closed.",
      registerJavascriptSource: "Register JavaScript computation source",
      registerJavascriptSourceHelp: "Register a source root or subdirectory as a read-only JavaScript computation source.",
      javascriptSourceRoot: "Source root",
      javascriptSourceRootHelp: "Choose an already bound read-only source directory.",
      sourceRootSelectionRequired: "Select a source root.",
      sourceRootSelectionStale: "The previously selected source root is unavailable. Select it again; no other source was substituted.",
      javascriptProjectRelpath: "Project or subdirectory (. means source root)",
      javascriptProjectRelpathHelp: "Limit the computation scan scope; this directory is never modified.",
      javascriptDisplayName: "Computation source name",
      javascriptDisplayNameHelp: "Give this computation source a recognizable local name; leave blank to use the directory name.",
      javascriptSourceType: "JavaScript computation source",
      staticWebSourceType: "Static web source",
      unknownSourceType: "Unknown source type",
      refreshProjectHelp: "Rescan this source project read-only.",
      scanJavascriptComputations: "Find reusable calculations",
      scanJavascriptComputationsHelp: "Inspect JavaScript functions in this project read-only. Reweave will not run, modify, or build the source project, and it will not publish a capsule yet.",
      scanJavascriptRunning: "Analyzing JavaScript functions read-only…",
      scanJavascriptFound: "Found {count} calculations that can be validated further.",
      noJavascriptComputations: "No pure calculation matched the current safety scope. The source project was not modified.",
      projectScanReady: "Ready for a read-only calculation scan.",
      projectScanPending: "This project is not confirmed yet. Confirm the source project first.",
      projectScanSourceMissing: "The source directory is unavailable. Select the original directory again.",
      projectScanStaticUnsupported: "Static Web extraction is unsupported, but Reweave can still look for pure calculations.",
      projectScanPlatformUnsupported: "Legacy JavaScript capture is unsupported on this platform; the source was not read.",
      projectScanIncomplete: "This project record is incomplete. Discover or register the project again.",
      projectScanUnknownType: "The source type is unknown. Discover or register the project again.",
      projectScanUnknownState: "The project state is unknown. Refresh the project list and try again.",
      adapterInputKind: "Input type",
      adapterInputKindHelp: "Simple mode uses integers; configure booleans, enums, and bounded strings in developer mode.",
      adapterEnumValues: "Enum values (one per line)",
      adapterEnumValuesHelp: "List exact allowed string values, one per line.",
      captureNeedsDecision: "Waiting for your safety decision; model supervision and runtime validation have not run.",
      captureResubmitRequired: "Decision saved. Return to the function and click Continue validation to rebuild from current source.",
      captureResumeReview: "Resume waiting review (optional)",
      captureResumeReviewHelp: "Developer recovery control; the normal flow links the current review automatically.",
      adapterCreationPathRetired: "The legacy calculation entry point is retired. Scan for calculations again.",
      adapterContractVersionExpired: "This legacy candidate has expired. Scan again; it can no longer be processed or published.",
      adapterInputField: "Input field",
      adapterInputFieldHelp: "The product-facing field; for example, map source parameter x to quantity.",
      adapterInputSourceLabel: "Input {index} (source parameter: {parameter})",
      adapterInputFieldVisibleHelp: "This is the input name used by the new product. For example, quantity can mean an item count.",
      adapterMinimum: "Minimum",
      adapterMinimumHelp: "The smallest allowed safe integer. Enter a real business limit.",
      adapterMaximum: "Maximum",
      adapterMaximumHelp: "The largest allowed safe integer. Enter a real business limit.",
      adapterMinimumLength: "Minimum length",
      adapterMaximumLength: "Maximum length",
      adapterResultEnum: "Result enum (one per line)",
      adapterResultEnumHelp: "List every exact string value the computation may return, one per line.",
      adapterWitness: "Acceptance input for {value}",
      adapterWitnessHelp: "This input must make the old function return the matching enum value and satisfy the declared UTF-16 length bounds.",
      adapterResultField: "Result field",
      adapterResultFieldHelp: "The field used by products to receive this result, for example total.",
      adapterResultFieldVisibleHelp: "This is the result name used by the new product. For example, total can mean a total price.",
      adapterExample: "Business example",
      adapterExampleHelp: "Enter an input whose correct result you know; it must be within the declared range.",
      adapterExpected: "Expected result",
      adapterExpectedHelp: "The actual integer result the old function should return for the example above.",
      adapterSimpleHelp: "Map source parameters to product fields; ranges define accepted input; the example and expected result check the real function.",
      adapterMappingPreview: "Will submit: {mapping}",
      adapterMappingConfirmation: "I confirm this proves only the mapping and specified examples, not total equivalence.",
      adapterMappingConfirmShort: "I confirm",
      createComputationAdapter: "Create computation candidate",
      continueCaptureValidation: "Continue validation",
      adapterMappingInvalid: "Enter valid unique fields, bounds, enums, and one acceptance input per result.",
      adapterInspectionComplete: "Computation function inspection completed.",
      adapterCandidateCreated: "Computation candidate created; continue review.",
      captureWaitingModel: "Waiting for the local supervision model; validation is incomplete.",
      captureWaitingValidation: "Waiting for Node runtime validation; nothing was published.",
      captureRejected: "Candidate rejected; no formal capsule was written.",
      captureReviewRequired: "Security, model, and runtime validation passed; publication review is required.",
      captureDuplicate: "Matched the active formal version exactly and linked its source.",
      captureOutcomeUnknown: "The candidate returned an unknown status and was stopped.",
      captureOfferStale: "The source or function list changed. Scan again before submitting.",
      captureExampleMismatch: "The business example does not match the old function's real result. Check the input and expected result.",
      captureSourceChanged: "The source changed during scanning. Nothing was saved; scan again.",
      captureWorkerTimeout: "Computation validation timed out. Nothing was saved; review the function scope and retry.",
      captureSecurityRejected: "The function did not pass the safety boundary. Nothing was saved; developer mode shows diagnostics.",
      captureRequestInvalid: "The submission is incomplete or expired. Scan again and refill it.",
      managementOperationFailed: "The operation did not complete and no formal capsule was written. Retry or inspect diagnostics in developer mode.",
      reviewStatusWaitingUser: "Waiting for user decision",
      reviewStatusWaitingModel: "Waiting for model",
      reviewStatusWaitingValidation: "Waiting for runtime validation",
      reviewStatusReviewRequired: "Waiting for publication review",
      reviewStatusDuplicate: "Exact duplicate",
      reviewStatusRejected: "Rejected",
      captureReview: "Computation safety decision",
      captureSafetySummary: "Safety scan: {ambiguous} ambiguous, {brand} brand, {enums} enum parameters.",
      capabilityKeyLabel: "Capability key",
      capabilityKeyHelp: "Stable snake_case identity shared by one complete capability, for example quote_calculation.",
      roleKeyLabel: "Role key",
      roleKeyHelp: "Stable identity for this atomic role, for example total_price.",
      variantKeyLabel: "Variant key",
      variantKeyHelp: "Stable identity for another implementation of the same role; the first is usually default.",
      displayNameLabel: "Display name",
      displayNameHelp: "A user-facing label that can be renamed after publication.",
      retainedVersionLabel: "Retained formal version",
      retainedVersionHelp: "Choose the existing formal version to retain after manual equivalence review.",
      targetCapsuleLabel: "Target capsule",
      targetCapsuleHelp: "Choose the existing capsule to replace or use as the semantic-split source.",
      decisionConfirmFictional: "Fictional example",
      decisionConfirmFictionalHelp: "Use only when you know the matched content is not a customer or other real record.",
      decisionRejectRealRecord: "Real record: reject",
      decisionRejectRealRecordHelp: "Confirm a real record is present and stop this candidate without publishing it.",
      decisionConfirmSafeRedaction: "Confirm redaction",
      decisionConfirmSafeRedactionHelp: "Confirm the cleaned candidate no longer contains real records.",
      decisionRetainBrand: "Brand-limited",
      decisionRetainBrandHelp: "Allow this capsule only for the current brand profile.",
      decisionRemoveBrand: "Remove brand",
      decisionRemoveBrandHelp: "Apply current cleaning rules to remove brand content and process again.",
      decisionConfirmEnum: "Confirm enum",
      decisionConfirmEnumHelp: "Confirm these strings are business enums, not real records.",
      decisionConfirmAssets: "Confirm images",
      decisionConfirmAssetsHelp: "Confirm image pixels contain no customer screenshots or other real records.",
      decisionPublishGeneral: "Publish (general)",
      decisionPublishGeneralHelp: "Publish under the current identity for contract-compatible products.",
      decisionPublishBrand: "Publish (brand)",
      decisionPublishBrandHelp: "Publish under the current identity for the current brand scope only.",
      decisionCreateVariant: "New variant",
      decisionCreateVariantHelp: "Keep the current implementation and publish this one as another variant.",
      decisionMergeExisting: "Merge existing",
      decisionMergeExistingHelp: "Confirm equivalence manually and keep the existing formal implementation.",
      decisionReplaceCurrent: "Replace current",
      decisionReplaceCurrentHelp: "Publish an immutable new version and switch the current formal version.",
      decisionSemanticSplit: "Split identity",
      decisionSemanticSplitHelp: "Publish this candidate as a new capability identity without deleting the old one.",
      decisionReject: "Reject",
      decisionRejectHelp: "Stop this candidate without writing a formal capsule.",
      decisionProcessCandidate: "Continue validation",
      decisionProcessCandidateHelp: "Continue the existing security, model, and runtime gates; this never auto-publishes.",
      createBackupHelp: "Back up the local capsule warehouse, brand configuration, and usage history.",
      importLegacyHelp: "Reclean old warehouse entries one by one; old implementations are never trusted directly.",
      restoreHelp: "Restore the complete local capsule warehouse to the selected backup point.",
      mapLegacyHelp: "Link an old capsule record to a manually confirmed formal version.",
      retryUsageHelp: "Recheck the product manifest and register its exact capsule versions.",
      cancelRunHelp: "Request cancellation of this background task; completed transactions remain atomic.",
      renameCapabilityHelp: "Change only the display name without changing the stable capability key.",
      viewDetailsHelp: "View the current formal-version summary for this capsule.",
      disableCapsuleHelp: "Disable the current capsule without physically deleting version history.",
      enableCapsuleHelp: "Enable a current capsule whose validation evidence remains valid.",
      cancelRun: "Cancel",
      restore: "Restore",
      viewDetails: "View details",
      renameCapability: "Rename",
      renameCapabilityPrompt: "Enter a new capability display name",
      manifestDigest: "Manifest digest",
      preRestoreBackup: "Pre-restore backup",
      backupAvailable: "Available",
      backupUnavailable: "Unavailable",
      disableCapsule: "Disable",
      enableCapsule: "Enable",
      restoreConfirm: "Restore rewinds the local warehouse to this backup. Continue?",
      decisionSaved: "Decision saved.",
      modelSaved: "Supervision model saved.",
      backupCreated: "Backup created.",
      retryUsage: "Register product usage",
      usageRetryComplete: "Product usage registration completed.",
      restoreComplete: "Warehouse restore complete.",
      importStarted: "Legacy recleaning run started.",
      legacyNotFound: "No legacy capsule warehouse found.",
      legacyWarehouse: "Legacy capsule warehouse",
      legacyAliases: "Migration relationships",
      legacyPending: "Pending human mapping",
      legacyRelationship: "Relationship",
      legacyTarget: "New capsule version",
      mapLegacy: "Confirm mapping",
      warnings: "Warnings",
      truncated: "truncated",
      redacted: "redacted",
      verify: "Verify",
      review: "Review",
      promote: "Promote",
      approve: "Approve",
      reject: "Reject",
      defer: "Defer",
      promoted: "Promoted",
      pending: "Pending",
      approved: "Approved",
      rejected: "Rejected",
      deferred: "Deferred",
    },
  };

  var els = {};
  var desktopBridge = null;
  var bridgeReady = false;
  var desktopShellState = null;
  var verifyingSourceIds = {};
  var previewingSourceIds = {};
  var reviewingSourceIds = {};
  var lastPreviewPath = "";
  var lastReactPreview = null;
  var pendingGeneratePromise = null;
  var useEnrichedContentPreview = false;
  var usedCapsuleSelectionMode = "manual";
  var previewViewerMode = "view";
  var lumoLiteArtifacts = [];
  var BUILD_NOTE_FILES = {
    "PREVIEW_README.md": true,
    "adapter_mapping.json": true,
    "behavior_adaptation.json": true,
    "behavior_contract.json": true,
    "behavior_validation.json": true,
    "capsules_used.json": true,
    "composition_plan.json": true,
    "frontend_runtime_state.json": true,
    "provenance.json": true,
    "quality_gate.json": true,
    "project_graph.json": true,
    "react_adaptation.json": true,
    "react_compile.json": true,
    "react_runtime_validation.json": true,
    "snippets_used.json": true,
    "summary.md": true,
    "task_intent.json": true,
    "task_pack.json": true,
    "task_plan.json": true,
  };
  var bridgeHelpers = window.ReweaveBridgeHelpers || {};
  var renderers = window.ReweaveRenderers || {};
  var artifactRenderers = window.ReweaveArtifacts || {};
  var sourceWorkflow = window.ReweaveSourceWorkflow || {};
  var capsuleReader = window.ReweaveCapsuleReader || {};
  var capsuleWarehouseScene = window.ReweaveCapsuleWarehouseScene.create({
    getCapsules: function () {
      return data && Array.isArray(data.capsules) ? data.capsules : [];
    },
    getProjects: function () {
      return ingestionManagement.projects;
    },
    readCapsuleDetail: function (capsuleId) {
      return bridgeCall("get_capsule_detail", JSON.stringify({ capsule_id: capsuleId })).then(function (raw) {
        var result = parseBridgeJson(raw);
        return managementPayload(result);
      });
    },
    readCapsuleCoreCode: function (capsuleId, versionId, projectId) {
      return bridgeCall("get_capsule_core_code_projection", JSON.stringify({
        capsule_id: capsuleId,
        version_id: versionId,
        project_id: projectId,
      })).then(function (raw) {
        var result = parseBridgeJson(raw);
        return managementPayload(result);
      });
    },
    openManagement: function (specimenContext) {
      openIngestionScene("warehouse", specimenContext || null);
    },
    getLocale: function () {
      return locale;
    },
    targetAvailable: function () {
      var button = $("btn-open-target");
      return !!(button && !button.disabled && !button.classList.contains("hidden"));
    },
    openProduct: function () {
      productPlanScene.open();
    },
    openTarget: function () {
      var button = $("btn-open-target");
      if (button && !button.disabled) button.click();
    },
    openCompatibility: function () {
      var button = $("btn-product-plan-back");
      if (button) button.click();
      else {
        showScreen("screen-main");
        syncAppState();
      }
    },
    toggleLocale: toggleLocale,
    capsuleReader: capsuleReader,
    t: t,
    showScreen: showScreen,
    syncAppState: syncAppState,
    transition: runSceneThreadTransition,
  });
  var productPlanScene = window.ReweaveProductPlanScene.create({
    canOpenProduct: function () {
      return !!(
        desktopShellState &&
        desktopShellState.canPlanProduct === true &&
        desktopShellState.productPlanning
      );
    },
    getLocale: function () {
      return locale;
    },
    getPlanningState: function () {
      return desktopShellState && desktopShellState.productPlanning;
    },
    setSelectedPlanningModel: function (model) {
      if (!desktopShellState || !desktopShellState.productPlanning) return;
      desktopShellState.productPlanning.selected_model = model;
    },
    call: function (method, payload) {
      return bridgeCall(method, JSON.stringify(payload || {})).then(function (raw) {
        return parseBridgeJson(raw);
      });
    },
    openWarehouse: function (context) {
      capsuleWarehouseScene.open(context || null);
    },
    openIngestion: function (context) {
      openIngestionScene("product", context || null);
    },
    toggleLocale: toggleLocale,
    showScreen: showScreen,
  });
  var targetIntegration = window.ReweaveTargetWorkflow.create({
    getBridge: function () {
      return desktopBridge;
    },
    bridgeCall: bridgeCall,
    parseBridgeJson: parseBridgeJson,
    getCapsules: function () {
      return data && Array.isArray(data.capsules) ? data.capsules : [];
    },
    isCapsuleGenerateEligible: isCapsuleGenerateEligible,
    formalSelectionError: formalSelectionError,
    t: t,
    formatText: formatText,
    getLocale: function () {
      return locale;
    },
    showScreen: showScreen,
    syncAppState: syncAppState,
    openProduct: function () {
      productPlanScene.open();
    },
    openWarehouse: function (context) {
      capsuleWarehouseScene.open(context || null);
    },
    openIngestion: function () {
      openIngestionScene("product", null);
    },
    openCompatTools: function () {
      showScreen("screen-main");
      syncAppState();
    },
    toggleLocale: toggleLocale,
  });

  function $(id) {
    return document.getElementById(id);
  }

  function parseBridgeJson(raw) {
    return bridgeHelpers.parseBridgeJson ? bridgeHelpers.parseBridgeJson(raw) : null;
  }

  function hasDesktopBridge() {
    return !!(desktopBridge && typeof desktopBridge.get_initial_state === "function");
  }

  function desktopCapability(name) {
    return bridgeHelpers.desktopCapability
      ? bridgeHelpers.desktopCapability(desktopShellState, name)
      : false;
  }

  function isLumoLiteReadOnly() {
    return bridgeHelpers.isLumoLiteReadOnly
      ? bridgeHelpers.isLumoLiteReadOnly(desktopShellState, data)
      : false;
  }

  function isLumoLiteState(state) {
    return bridgeHelpers.isLumoLiteState ? bridgeHelpers.isLumoLiteState(state) : false;
  }

  function canBuildTaskPackPreview() {
    return bridgeHelpers.canBuildTaskPackPreview
      ? bridgeHelpers.canBuildTaskPackPreview(desktopShellState, data)
      : false;
  }

  function canGenerateProduct() {
    return desktopCapability("canGenerateProduct");
  }

  function clearLumoLiteMockState() {
    delete data.generatedPackage;
    delete data.lastPreview;
    delete data.previewPath;
    data.history = [];
    data.sampleTask = "";
    lastPreviewPath = "";
  }

  function normalizeMockFallback() {
    data.sourceBoxes = [];
    data.capsules = [];
    data.warehouseCapsules = [];
    data.generateCapsuleIds = [];
    data.history = [];
    data.sampleTask = "";
    data.lumoLiteMode = "source_read_only_preview_write";
    data.lumoLiteRuntimeSummary = {
      line: "Source project read-only / local preview enabled",
      capsules_used: 0,
      preview_ready: false,
      trace_available: false,
      product_capability_line: "Product capability: unavailable · Source writes: 0 · Trace unavailable",
      product_base_status: "",
      task_pack_status: "",
    };
    data.cleaningSteps = ["Current Runtime / artifacts"];
    data.generatedPackage = {
      folder: "",
      files: [],
      stats: {
        capsulesUsed: 0,
        preview: "Current Runtime / artifacts",
        provenance: "Trace unavailable without Lumo Lite runtime",
      },
    };
  }

  function syncSourceControls() {
    var addSourceBtn = document.querySelector(".btn-add-source");
    if (!addSourceBtn) return;
    addSourceBtn.disabled = true;
    addSourceBtn.classList.add("hidden");
  }

  function syncWelcomeSourceBoxMode() {
    var bindBtn = $("btn-select-folder");
    var note = $("source-box-mode-note");
    var runtimeBtn = $("btn-view-runtime");
    if (!bindBtn) return;
    var readOnly = hasDesktopBridge() && isLumoLiteReadOnly();
    bindBtn.textContent = t("bindSourceBox");
    bindBtn.disabled = true;
    bindBtn.setAttribute("aria-disabled", "true");
    bindBtn.classList.add("hidden");
    setOptionalTitle(bindBtn, t("sourceBoxBindingDisabled"));
    if (note) {
      note.textContent = readOnly ? t("sourceBoxReadOnlyNote") : t("sourceBoxNote");
    }
    if (runtimeBtn) runtimeBtn.classList.toggle("hidden", !readOnly);
  }

  function getLumoLiteRuntimeSummary() {
    if (desktopShellState && desktopShellState.lumoLiteRuntimeSummary) {
      return desktopShellState.lumoLiteRuntimeSummary;
    }
    return data && data.lumoLiteRuntimeSummary ? data.lumoLiteRuntimeSummary : null;
  }

  function lumoPreviewFiles() {
    var seen = {};
    return lumoLiteArtifacts.reduce(function (files, artifact) {
      var name = artifact && artifact.kind === "preview_artifact" ? String(artifact.basename || "") : "";
      if (name && !seen[name]) {
        seen[name] = true;
        files.push(name);
      }
      return files;
    }, []);
  }

  function userFacingFiles(files) {
    return (Array.isArray(files) ? files : []).filter(function (name) {
      return !BUILD_NOTE_FILES[name];
    });
  }

  function applyLumoLiteRuntimeView() {
    if (!els.taskInput) return;
    if (!isLumoLiteReadOnly()) {
      setRuntimeSidecarAvailable(false);
      return;
    }
    var summary = getLumoLiteRuntimeSummary() || {};
    var taskPackPreview = canGenerateProduct() || canBuildTaskPackPreview();
    if (els.btnLumoArtifacts) {
      els.btnLumoArtifacts.classList.toggle("hidden", lumoLiteArtifacts.length === 0);
    }
    var artifactFiles = lumoPreviewFiles();
    var generatedFiles = data.generatedPackage && Array.isArray(data.generatedPackage.files)
      ? data.generatedPackage.files
      : [];
    var productFiles = userFacingFiles(artifactFiles.length ? artifactFiles : generatedFiles);
    var generatedProductEntry = data.generatedPackage && data.generatedPackage.productEntry;
    var generatedProductPath = generatedProductEntry && generatedProductEntry.path;
    var hasTaskPackPreview =
      taskPackPreview &&
      (productFiles.length > 0 ||
        (!!lastPreviewPath &&
          (generatedFiles.indexOf("task_pack.json") >= 0 ||
            (!!generatedProductPath && generatedFiles.indexOf(generatedProductPath) >= 0))));
    var generatedTraceAvailable = hasTaskPackPreview && data.generatedTraceVerified === true;
    var traceAvailable = !!summary.trace_available || generatedTraceAvailable;
    var capsulesUsed = hasTaskPackPreview ? usedCapsuleIds.length : Number(summary.capsules_used || 0);
    var traceText = traceAvailable ? t("traceAvailable") : t("traceUnavailable");
    var previewText = hasTaskPackPreview
      ? t("smallProjectPackReady")
      : summary.preview_ready
        ? t("previewReady")
        : t("previewNotReady");
    var sourceWrites = summary.source_project_write_count;
    var previewReadyWithoutHistory = taskPackPreview && !summary.status && !summary.trace_available;
    if (previewReadyWithoutHistory || hasTaskPackPreview) sourceWrites = 0;
    if (sourceWrites === undefined || sourceWrites === null || sourceWrites === "") sourceWrites = t("unknown");
    setRuntimeSidecarAvailable(
      !!(summary.status || summary.preview_ready || traceAvailable || sourceWrites === 0)
    );
    var capability =
      lastPreviewAcceptance && hasTaskPackPreview
        ? lastPreviewAcceptance.reason === "real_qwebengine_product_bootstrap"
          ? t("capabilityReview")
          : lastPreviewAcceptance.verdict === "usable"
          ? t("capabilityReady")
          : lastPreviewAcceptance.verdict === "needs_review"
            ? t("capabilityReview")
            : t("capabilityUnavailable")
        : sourceWrites === 0 && traceAvailable
          ? t("capabilityReady")
        : summary.status
          ? t("capabilityReview")
          : t("capabilityUnavailable");
    var responseText = lastPreviewAcceptance && hasTaskPackPreview
      ? previewAcceptanceText(lastPreviewAcceptance)
      : previewReadyWithoutHistory
      ? t("previewReadyNoAcceptance")
      : formatText("productSummary", {
          capability: capability,
          writes: sourceWrites,
          trace: traceAvailable ? t("ready") : t("unavailable"),
        });

    if (!taskPackPreview) els.taskInput.value = "";
    els.taskInput.placeholder = taskPackPreview ? t("taskPackPlaceholder") : t("runtimePlaceholder");
    els.taskInput.disabled = !taskPackPreview;
    if (els.btnGenerate) {
      els.btnGenerate.disabled = !taskPackPreview;
      els.btnGenerate.setAttribute("aria-disabled", taskPackPreview ? "false" : "true");
      els.btnGenerate.title = taskPackPreview ? t("buildSmallProjectPack") : t("runtimeReadOnlyMessage");
      els.btnGenerate.classList.toggle("hidden", !taskPackPreview);
    }
    if (els.generatedPackage) {
      els.generatedPackage.classList.toggle("runtime-read-only", !hasTaskPackPreview);
    }
    var title = document.querySelector(".generated-title");
    if (title) title.textContent = hasTaskPackPreview ? t("smallProjectPack") : t("currentRuntime");
    if (els.generatedTree && hasTaskPackPreview && productFiles.length > 0) {
      els.generatedTree.innerHTML = renderers.renderFileTree
        ? renderers.renderFileTree(t("smallProjectPack") + "/", productFiles, escapeHtml)
        : '<div class="folder">' + escapeHtml(t("smallProjectPack")) + "/</div>";
    } else if (els.generatedTree && !hasTaskPackPreview) {
      els.generatedTree.innerHTML =
        '<div class="folder">' + escapeHtml(t("runtimeArtifacts")) + "</div>" +
        '<div class="file highlight">frontend_runtime_state.json</div>' +
        '<div class="file highlight-subtle">' + escapeHtml(t("runtimeTraceFiles")) + "</div>";
    }
    if (els.generatedPreview) {
      els.generatedPreview.classList.toggle("hidden", !hasTaskPackPreview);
    }
    var previewLabel = document.querySelector(".preview-label");
    if (previewLabel) previewLabel.textContent = lastReactPreview ? t("reactRuntimeVerified") : previewText;
    if (els.usedCount && !hasTaskPackPreview) {
      els.usedCount.textContent = String(capsulesUsed);
    }
    if (els.usedCapsuleDock && !hasTaskPackPreview) {
      var usedText =
        capsulesUsed > 0
          ? formatText("capsulesLinked", { count: capsulesUsed })
          : t("noCapsuleUsage");
      els.usedCapsuleDock.innerHTML =
        '<span class="used-placeholder runtime-used-note">' + escapeHtml(usedText) + "</span>";
    }
    if (els.genCapsulesUsed && !hasTaskPackPreview) {
      els.genCapsulesUsed.innerHTML =
        '<span class="meta-icon" aria-hidden="true">◫</span> ' +
        capsulesUsed +
        " " +
        escapeHtml(t("capsulesUsed"));
    }
    if (els.workflowStatus) {
      var workflowText = hasTaskPackPreview
        ? taskPackStatusFromFiles(artifactFiles.length ? artifactFiles : data.generatedPackage.files || [])
        : currentWorkflowStep(hasTaskPackPreview);
      els.workflowStatus.innerHTML =
        '<span class="meta-icon" aria-hidden="true">↳</span> ' +
        escapeHtml(t("workflow")) +
        ": " +
        escapeHtml(workflowText);
    }
    var metaLines = document.querySelectorAll(".generated-meta .meta-line");
    if (metaLines[2]) metaLines[2].innerHTML = '<span class="meta-icon" aria-hidden="true">◎</span> ' + previewText;
    if (metaLines[3]) metaLines[3].innerHTML = '<span class="meta-icon" aria-hidden="true">⛓</span> ' + traceText;
    if (els.runtimeSidecarMode) els.runtimeSidecarMode.textContent = t("sourceReadOnly");
    if (els.runtimeSidecarSource) {
      els.runtimeSidecarSource.textContent = responseText;
    }
    if (els.runtimeSidecarStatus) {
      els.runtimeSidecarStatus.textContent =
        t("sourceWrites") +
        ": " +
        sourceWrites +
        "\n" +
        t("trace") +
        ": " +
        (traceAvailable ? t("ready") : t("unavailable")) +
        "\n" +
        t("preview") +
        ": " +
        (hasTaskPackPreview || summary.preview_ready ? t("ready") : t("notReady")) +
        "\n" +
        t("capsules") +
        ": " +
        capsulesUsed;
    }
    if (els.previewPackageActions) {
      els.previewPackageActions.classList.toggle("hidden", !hasTaskPackPreview);
      var viewPackage = $("btn-view-package");
      var comparePackage = $("btn-compare-last");
      if (viewPackage) viewPackage.classList.toggle("hidden", !hasTaskPackPreview);
      if (comparePackage) comparePackage.classList.add("hidden");
    }
    if (els.reweaveResponse) els.reweaveResponse.textContent = responseText;
  }

  function currentWorkflowStep(hasTaskPackPreview) {
    if (hasTaskPackPreview) return t("workflowViewProvenance");
    var sources = Array.isArray(data.sourceBoxes) ? data.sourceBoxes : [];
    if (!sources.length) return t("workflowBindSource");
    var needsScan = sources.some(function (src) {
      return (src.scan_status || "not_scanned") === "not_scanned";
    });
    if (needsScan) return t("workflowScanSource");
    var capsules = Array.isArray(data.warehouseCapsules) ? data.warehouseCapsules : data.capsules || [];
    if (!capsules.length) return t("workflowStoreCapsules");
    return t("workflowBuildPack");
  }

  function taskPackStatusFromFiles(files) {
    files = Array.isArray(files) ? files : [];
    if (
      files.indexOf("task_intent.json") >= 0 &&
      files.indexOf("task_plan.json") >= 0 &&
      files.indexOf("quality_gate.json") >= 0
    ) {
      var qualityStatus = data.qualityGate && data.qualityGate.status;
      if (qualityStatus === "passed") return t("workflowIntentReady");
      if (qualityStatus === "failed") return t("workflowQualityFailed");
      return t("workflowIntentReview");
    }
    if (files.indexOf("task_pack.json") >= 0) return t("workflowPackReady");
    return t("workflowViewProvenance");
  }

  function bridgeCall(method, arg) {
    return new Promise(function (resolve) {
      if (!hasDesktopBridge()) {
        resolve(null);
        return;
      }
      var fn = desktopBridge[method];
      if (typeof fn !== "function") {
        resolve(null);
        return;
      }
      var ret;
      try {
        ret = arg !== undefined ? fn(arg) : fn();
      } catch (e) {
        console.warn("[Reweave] bridge call failed:", method, e);
        resolve(null);
        return;
      }
      if (ret && typeof ret.then === "function") {
        ret.then(resolve).catch(function () {
          resolve(null);
        });
        return;
      }
      resolve(ret);
    });
  }

  function initDesktopBridge(callback) {
    var finished = false;
    var connecting = false;
    function finish(available) {
      if (finished) return;
      finished = true;
      if (typeof callback === "function") callback(available);
    }

    function attach() {
      if (window.reweaveBridge && typeof window.reweaveBridge.get_initial_state === "function") {
        desktopBridge = window.reweaveBridge;
        bridgeReady = true;
        bridgeCall("get_initial_state").then(function (raw) {
          desktopShellState = parseBridgeJson(raw);
          applyDesktopInitialState(desktopShellState);
          finish(true);
        });
        return true;
      }
      return false;
    }

    function connectQtBridge() {
      if (
        finished ||
        connecting ||
        window.__reweaveWebChannelConnecting ||
        typeof qt === "undefined" ||
        !qt.webChannelTransport ||
        typeof QWebChannel === "undefined"
      ) {
        return false;
      }
      connecting = true;
      window.__reweaveWebChannelConnecting = true;
      new QWebChannel(qt.webChannelTransport, function (channel) {
        window.__reweaveWebChannelConnecting = false;
        window.reweaveBridge = channel.objects.reweaveBridge;
        connecting = false;
        attach();
      });
      return true;
    }

    if (attach()) return;
    var retryUntil = Date.now() + 6000;
    function retryAttach() {
      if (attach() || connectQtBridge() || finished) return;
      if (Date.now() < retryUntil) setTimeout(retryAttach, 50);
    }
    retryAttach();

    window.addEventListener("reweave-bridge-ready", function onReady() {
      window.removeEventListener("reweave-bridge-ready", onReady);
      if (!attach()) finish(false);
    });

    setTimeout(function () {
      finish(hasDesktopBridge());
    }, 7000);
  }

  function mergeSourceFromDesktop(source) {
    if (!source || !source.id) return;
    if (!data.sourceBoxes) data.sourceBoxes = [];
    var idx = -1;
    data.sourceBoxes.forEach(function (s, i) {
      if (s.id === source.id || (source.path && s.path === source.path)) idx = i;
    });
    var entry = sourceWorkflow.normalizeSource ? sourceWorkflow.normalizeSource(source) : source;
    if (idx >= 0) {
      data.sourceBoxes[idx] = entry;
    } else {
      data.sourceBoxes.push(entry);
    }
  }

  function normalizeDockCapsule(c) {
    return capsuleReader.normalizeCapsule ? capsuleReader.normalizeCapsule(c) : c || null;
  }

  function isMetadataCapsule(cap) {
    return capsuleReader.isMetadataCapsule ? capsuleReader.isMetadataCapsule(cap) : false;
  }

  function isCapsuleGenerateEligible(cap) {
    if (!cap) return false;
    var status = cap.status || "active";
    if (cap.formal_version) {
      return status === "active" && cap.generation_eligible === true;
    }
    return status === "active" || status === "ready";
  }

  function isCapsuleManageEligible(cap) {
    return !!(
      cap &&
      !cap.formal_version &&
      !isLumoLiteReadOnly() &&
      isCapsuleGenerateEligible(cap)
    );
  }

  function applyWarehouseCapsules(capsules) {
    if (!Array.isArray(capsules)) return;
    data.capsules = capsules.map(normalizeDockCapsule).filter(Boolean);
    data.warehouseCapsules = data.capsules.slice();
    data.generateCapsuleIds = data.capsules.filter(isCapsuleGenerateEligible).map(function (cap) {
      return cap.id;
    });
    usedCapsuleIds = usedCapsuleIds.filter(function (id) {
      return data.generateCapsuleIds.indexOf(id) !== -1;
    });
    if (selectedCapsuleId && data.generateCapsuleIds.indexOf(selectedCapsuleId) === -1) {
      selectedCapsuleId = null;
      if (els.reader) hideCapsuleReader();
    }
    if (els.capsuleStrip) {
      renderCapsuleStrip();
    }
    if (els.usedCapsuleDock && els.usedCount) renderUsedChips();
    capsuleWarehouseScene.sync();
    productPlanScene.sync();
    targetIntegration.sync();
    updateEnrichedContentToggle();
  }

  function applyDesktopInitialState(state) {
    if (!hasDesktopBridge() || !state || !data) return;
    clearLumoLiteMockState();
    delete data.lumoLiteMode;
    delete data.lumoLiteRuntimeSummary;
    lastPreviewAcceptance = null;
    lastReactPreview = null;
    delete data.qualityGate;
    data.generatedTraceVerified = false;
    delete data.lunaPack;
    delete data.contentAwareGenerate;
    if (isLumoLiteState(state)) {
      data.lumoLiteRuntimeSummary = state.lumoLiteRuntimeSummary || null;
    }
    if (Array.isArray(state.sourceBoxes)) {
      data.sourceBoxes = state.sourceBoxes.map(function (s) {
        return sourceWorkflow.normalizeSource ? sourceWorkflow.normalizeSource(s) : s;
      }).filter(Boolean);
    }
    if (Array.isArray(state.warehouseCapsules)) {
      applyWarehouseCapsules(state.warehouseCapsules);
    } else if (state.useLocalCapsules && Array.isArray(state.capsules) && state.capsules.length) {
      applyWarehouseCapsules(state.capsules);
    }
    if (Array.isArray(state.history)) data.history = state.history.slice();
    applyIngestionInitialState(state.capsuleIngestionV1 || null);
    if (state.generatedPackage) {
      data.generatedPackage = state.generatedPackage;
    } else {
      delete data.generatedPackage;
    }
    lumoLiteArtifacts = Array.isArray(state.lumoLiteArtifacts)
      ? state.lumoLiteArtifacts.slice()
      : [];
    if (els.btnLumoArtifacts) {
      els.btnLumoArtifacts.classList.toggle("hidden", lumoLiteArtifacts.length === 0);
    }
    if (state.previewPath) {
      lastPreviewPath = state.previewPath;
    } else if (state.lastPreview && state.lastPreview.previewPath) {
      lastPreviewPath = state.lastPreview.previewPath;
    } else {
      lastPreviewPath = "";
    }
    if ($("sources-count")) {
      renderSources();
    }
    syncSourceControls();
    syncWelcomeSourceBoxMode();
    targetIntegration.sync();
    if ($("history-list")) renderHistory();
    if (els.reweaveResponse) els.reweaveResponse.textContent = "";
    if (els.generatedTree && els.generatedPreview) syncGeneratedPackageView();
    if (!isLumoLiteReadOnly()) {
      var canGenerate = canGenerateProduct();
      if (els.taskInput) {
        els.taskInput.disabled = !canGenerate;
        els.taskInput.placeholder = t("taskPlaceholder");
      }
      if (els.btnGenerate) {
        els.btnGenerate.disabled = !canGenerate;
        els.btnGenerate.classList.toggle("hidden", !canGenerate);
        els.btnGenerate.setAttribute("aria-disabled", canGenerate ? "false" : "true");
      }
    }
    applyLumoLiteRuntimeView();
  }

  function managementPayload(result) {
    if (!result || result.ok === false) return null;
    return result.data && typeof result.data === "object" ? result.data : result;
  }

  function managementList(result, names) {
    var payload = managementPayload(result);
    if (!payload) return [];
    if (Array.isArray(payload)) return payload.slice();
    for (var i = 0; i < names.length; i += 1) {
      if (Array.isArray(payload[names[i]])) return payload[names[i]].slice();
    }
    return [];
  }

  function managementError(result) {
    var error = result && result.error;
    var code = error && (error.message_key || error.code) ? String(error.message_key || error.code) : "internal_error";
    if (STR[locale][code]) return code;
    return {
      offer_stale: "captureOfferStale",
      adapter_offer_stale: "captureOfferStale",
      adapter_mapping_invalid: "adapterMappingInvalid",
      adapter_example_mismatch: "captureExampleMismatch",
      source_changed: "captureSourceChanged",
      candidate_boundary_changed: "captureSourceChanged",
      source_unavailable: "projectScanSourceMissing",
      source_platform_unsupported_v1: "projectScanPlatformUnsupported",
      worker_timeout: "captureWorkerTimeout",
      bundle_security_rejected: "captureSecurityRejected",
      adapter_security_rejected: "captureSecurityRejected",
      capture_request_invalid: "captureRequestInvalid",
      capture_resubmission_required: "captureResubmitRequired",
      adapter_creation_path_retired: "adapterCreationPathRetired",
      adapter_contract_version_expired: "adapterContractVersionExpired",
    }[code] || "managementOperationFailed";
  }

  function applyIngestionInitialState(block) {
    if (!block || typeof block !== "object") return;
    var payload = block.data && typeof block.data === "object" ? block.data : block;
    ingestionManagement.available = payload.available !== false;
    if (Array.isArray(payload.sourceRoots)) {
      ingestionManagement.sourceRoots = payload.sourceRoots.slice();
      if (
        ingestionManagement.selectedSourceRootId &&
        !ingestionManagement.sourceRoots.some(function (root) {
          return String(root.root_id || "") === ingestionManagement.selectedSourceRootId &&
            String(root.status || "") === "bound";
        })
      ) {
        ingestionManagement.selectedSourceRootId = "";
        ingestionManagement.sourceRootSelectionStale = true;
        ingestionManagement.errorKey = "sourceRootSelectionStale";
      }
    }
    if (Array.isArray(payload.projects)) ingestionManagement.projects = payload.projects.slice();
    if (Array.isArray(payload.review_items)) ingestionManagement.reviewItems = payload.review_items.slice();
    if (Array.isArray(payload.capability_groups)) ingestionManagement.capabilityGroups = payload.capability_groups.slice();
    if (Array.isArray(payload.backups)) ingestionManagement.backups = payload.backups.slice();
    if (Array.isArray(payload.recoverableProducts)) {
      ingestionManagement.recoverableProducts = payload.recoverableProducts.slice();
    }
    if (Array.isArray(payload.historicalProducts)) {
      ingestionManagement.historicalProducts = payload.historicalProducts.slice();
    }
    if (payload.legacy && typeof payload.legacy === "object") ingestionManagement.legacy = payload.legacy;
    if (payload.selected_model || payload.selectedSupervisionModel) {
      ingestionManagement.selectedModel = payload.selected_model || payload.selectedSupervisionModel;
    }
    ingestionManagement.loaded = false;
    var button = $("btn-capsule-warehouse");
    if (button) button.classList.toggle("hidden", !ingestionManagement.available);
    renderIngestionManagement();
    capsuleWarehouseScene.sync();
    productPlanScene.sync();
  }

  function setManagementStatus(key) {
    ingestionManagement.errorKey = key || "";
    var status = $("capsule-warehouse-status");
    if (!status) return;
    status.textContent = key ? (STR[locale][key] || key) : t("managementReady");
    var waiting = captureStatusIsWaiting(key);
    status.classList.toggle("is-waiting", waiting);
    status.classList.toggle("is-error", !!key && !waiting && [
      "managementLoading",
      "decisionSaved",
      "modelSaved",
      "backupCreated",
      "adapterInspectionComplete",
      "adapterCandidateCreated",
      "captureDuplicate",
      "restoreComplete",
      "importStarted",
      "sourceAgentBindingCopied",
      "sourceAgentRevoked",
    ].indexOf(key) < 0);
  }

  function captureOutcomeStatusKey(outcome) {
    var status = outcome && typeof outcome === "object" ? String(outcome.status || "") : "";
    return {
      waiting_user: "captureNeedsDecision",
      waiting_model: "captureWaitingModel",
      waiting_validation: "captureWaitingValidation",
      rejected: "captureRejected",
      review_required: "captureReviewRequired",
      duplicate: "captureDuplicate",
    }[status] || "captureOutcomeUnknown";
  }

  function captureStatusIsWaiting(key) {
    return [
      "captureNeedsDecision",
      "captureResubmitRequired",
      "captureWaitingModel",
      "captureWaitingValidation",
      "captureReviewRequired",
    ].indexOf(key) >= 0;
  }

  function setOptionalTitle(element, value) {
    if (!element) return element;
    var title = String(value || "").trim();
    if (title) element.title = title;
    else element.removeAttribute("title");
    return element;
  }

  function controlHelp(element, key) {
    var help = key && ((STR[locale] && STR[locale][key]) || STR.en[key]);
    setOptionalTitle(element, help);
    return element;
  }

  function syncWarehouseMode() {
    var popover = $("capsule-warehouse-popover");
    var toggle = $("warehouse-developer-mode");
    if (toggle) toggle.checked = ingestionManagement.developerMode === true;
    if (popover) popover.classList.toggle("developer-mode", ingestionManagement.developerMode === true);
  }

  function syncIngestionSpecimen() {
    var specimen = ingestionNavigation.specimen;
    var productReview = ingestionNavigation.productReview;
    var reviewItem = productReview
      ? ingestionManagement.reviewItems.find(function (item) {
          return String(item.review_id || "") === productReview.review_id;
        })
      : null;
    var reviewCandidate =
      reviewItem && reviewItem.candidate &&
      typeof reviewItem.candidate === "object"
        ? reviewItem.candidate
        : {};
    var surface = $("capsule-ingestion-specimen");
    var name = $("ingestion-specimen-name");
    var context = $("ingestion-specimen-context");
    if (!surface || !name || !context) return;
    surface.classList.toggle("is-empty", !specimen && !productReview);
    surface.classList.toggle(
      "is-exact",
      !!productReview || !!(specimen && specimen.exact_source)
    );
    surface.dataset.capabilityKind = productReview
      ? String(reviewItem && (
          reviewItem.capability_kind ||
          reviewCandidate.capability_kind
        ) || "")
      : specimen
        ? String(specimen.capability_kind || "")
        : "";
    name.textContent = productReview
      ? String(
          reviewItem && (
            reviewItem.display_name ||
            reviewItem.suggested_name
          ) || t("productReviewContext")
        )
      : specimen
        ? String(specimen.display_name || t("sourceProject"))
        : t("intakeSpecimenEmpty");
    var kindKey = specimen && {
      presentation: "presentationCapability",
      interaction: "interactionCapability",
      computation: "computationCapability",
    }[String(specimen.capability_kind || "")];
    var version = specimen ? String(specimen.version_id || "") : "";
    context.textContent = productReview
      ? t("productReviewExact")
      : !specimen
      ? ""
      : specimen.capsule_name
        ? [
          kindKey ? t(kindKey) : "",
          String(specimen.capsule_name),
          version.length > 18 ? version.slice(0, 15) + "…" : version,
        ].filter(Boolean).join(" · ")
        : specimen.exact_source
          ? formatText("formalCapsuleCount", { count: Number(specimen.formal_capsule_count || 0) })
          : t("intakeSpecimenSelected");
    ["presentation", "interaction", "computation"].forEach(function (kind) {
      var value = $("ingestion-specimen-" + kind);
      var counts = specimen && specimen.capsule_counts;
      if (value) {
        value.textContent = productReview
          ? surface.dataset.capabilityKind === kind ? "1" : "—"
          : counts && Number.isFinite(Number(counts[kind]))
            ? String(Number(counts[kind]))
            : "—";
      }
    });
    document.querySelectorAll("[data-specimen-project-id]").forEach(function (button) {
      button.setAttribute(
        "aria-pressed",
        specimen && specimen.project_id &&
          String(specimen.project_id) === String(button.dataset.specimenProjectId || "")
          ? "true"
          : "false"
      );
    });
  }

  function syncIngestionStation() {
    var station = ingestionNavigation.station;
    document.querySelectorAll("[data-ingestion-station]").forEach(function (button) {
      var active = button.dataset.ingestionStation === station;
      button.classList.toggle("is-active", active);
      button.setAttribute("aria-selected", active ? "true" : "false");
      button.setAttribute("tabindex", active ? "0" : "-1");
    });
    document.querySelectorAll("[data-ingestion-panel]").forEach(function (panel) {
      var active = panel.dataset.ingestionPanel === station;
      panel.classList.toggle("is-active", active);
      panel.hidden = !active;
    });
    var sourceCount = $("ingestion-source-count");
    var formalCount = $("ingestion-formal-count");
    var supervisionStatus = $("ingestion-supervision-status");
    if (sourceCount) sourceCount.textContent = String(ingestionManagement.projects.length);
    if (formalCount) formalCount.textContent = String(ingestionManagement.capabilityGroups.length);
    if (supervisionStatus) supervisionStatus.textContent = ingestionManagement.selectedModel ? "✓" : "—";
    syncIngestionSpecimen();
  }

  function syncFormalNavigation() {
    var targetEntry = $("btn-open-target");
    var targetAvailable = !!(
      targetEntry &&
      !targetEntry.disabled &&
      !targetEntry.classList.contains("hidden")
    );
    document.querySelectorAll("[data-formal-target-nav]").forEach(function (button) {
      button.classList.toggle("hidden", !targetAvailable);
      button.disabled = !targetAvailable;
      button.setAttribute("aria-disabled", targetAvailable ? "false" : "true");
    });
    document.querySelectorAll(".reweave-workspace-bar .btn-lang").forEach(function (button) {
        button.textContent = locale === "zh" ? "中·EN" : "EN·中";
    });
  }

  function runSceneThreadTransition(kind) {
    var line = $("scene-thread-transition");
    if (!line) return;
    line.dataset.kind = kind || "warehouse";
    line.classList.remove("is-active");
    void line.offsetWidth;
    line.classList.add("is-active");
    window.setTimeout(function () { line.classList.remove("is-active"); }, 220);
  }

  function openIngestionScene(fromScene, specimenContext) {
    var active = document.activeElement;
    ingestionNavigation.returnScene = fromScene || "product";
    ingestionNavigation.focusId = active && active.id ? active.id : "";
    var productReview =
      ingestionNavigation.returnScene === "product" &&
      specimenContext &&
      specimenContext.station === "review" &&
      typeof specimenContext.review_id === "string"
        ? {
            review_id: specimenContext.review_id,
            plan_token: String(specimenContext.plan_token || ""),
            projection_digest: String(
              specimenContext.projection_digest || ""
            ),
            return_focus_id: String(
              specimenContext.return_focus_id || ""
            ),
          }
        : null;
    ingestionNavigation.productReview = productReview;
    ingestionNavigation.sourceHandoffReview = null;
    ingestionNavigation.station = productReview ? "review" : "source";
    ingestionNavigation.specimen = !productReview &&
      specimenContext && typeof specimenContext === "object"
      ? {
        project_id: specimenContext.project_id || null,
        project_key: String(specimenContext.project_key || ""),
        display_name: String(specimenContext.display_name || ""),
        exact_source: specimenContext.exact_source === true,
        formal_capsule_count: Number(specimenContext.formal_capsule_count || 0),
        capsule_counts: specimenContext.capsule_counts || null,
        capsule_id: specimenContext.capsule_id || null,
        capsule_name: specimenContext.capsule_name || null,
        capability_kind: specimenContext.capability_kind || null,
        version_id: specimenContext.version_id || null,
        canonical_hash: specimenContext.canonical_hash || null,
      }
      : null;
    if (ingestionNavigation.returnScene === "warehouse") capsuleWarehouseScene.suspend();
    runSceneThreadTransition("ingestion");
    showScreen("screen-capsule-ingestion");
    var ingestionScreen = $("screen-capsule-ingestion");
    if (ingestionScreen) ingestionScreen.scrollTop = 0;
    window.scrollTo(0, 0);
    syncIngestionStation();
    syncFormalNavigation();
    if (!ingestionManagement.loaded && !ingestionManagement.loading) {
      refreshIngestionManagement();
    } else {
      renderIngestionManagement();
    }
    window.setTimeout(function () {
      var current = document.querySelector("[data-ingestion-station].is-active");
      if (current) current.focus({ preventScroll: true });
    }, 0);
  }

  function closeIngestionScene() {
    var productReview = ingestionNavigation.productReview;
    if (ingestionNavigation.returnScene === "warehouse") {
      capsuleWarehouseScene.resume();
    } else {
      showScreen("screen-product-plan");
      if (productReview && productReview.plan_token) {
        productPlanScene.refreshCurrentWorkspace({
          focusId:
            productReview.return_focus_id ||
            ingestionNavigation.focusId,
        });
      } else {
        productPlanScene.resume();
      }
    }
    ingestionNavigation.productReview = null;
    ingestionNavigation.sourceHandoffReview = null;
    window.setTimeout(function () {
      var target =
        !productReview && ingestionNavigation.focusId
          ? $(ingestionNavigation.focusId)
          : null;
      if (target) target.focus();
    }, 0);
  }

  function reviewStatusLabel(status) {
    var key = {
      waiting_user: "reviewStatusWaitingUser",
      waiting_model: "reviewStatusWaitingModel",
      waiting_validation: "reviewStatusWaitingValidation",
      review_required: "reviewStatusReviewRequired",
      duplicate: "reviewStatusDuplicate",
      rejected: "reviewStatusRejected",
    }[String(status || "")];
    return key ? t(key) : String(status || t("unknown"));
  }

  function reviewDecisionCopy(decision) {
    return {
      process_candidate: ["decisionProcessCandidate", "decisionProcessCandidateHelp"],
      confirm_fictional_fixture: ["decisionConfirmFictional", "decisionConfirmFictionalHelp"],
      confirm_safe_redaction: ["decisionConfirmSafeRedaction", "decisionConfirmSafeRedactionHelp"],
      confirm_real_record_reject: ["decisionRejectRealRecord", "decisionRejectRealRecordHelp"],
      remove_brand: ["decisionRemoveBrand", "decisionRemoveBrandHelp"],
      retain_brand_limited: ["decisionRetainBrand", "decisionRetainBrandHelp"],
      confirm_selected_string_enumeration: ["decisionConfirmEnum", "decisionConfirmEnumHelp"],
      confirm_assets_contain_no_real_records: ["decisionConfirmAssets", "decisionConfirmAssetsHelp"],
      publish_general: ["decisionPublishGeneral", "decisionPublishGeneralHelp"],
      publish_brand_limited: ["decisionPublishBrand", "decisionPublishBrandHelp"],
      create_variant: ["decisionCreateVariant", "decisionCreateVariantHelp"],
      merge_existing: ["decisionMergeExisting", "decisionMergeExistingHelp"],
      replace_current: ["decisionReplaceCurrent", "decisionReplaceCurrentHelp"],
      semantic_split: ["decisionSemanticSplit", "decisionSemanticSplitHelp"],
      reject: ["decisionReject", "decisionRejectHelp"],
    }[decision] || null;
  }

  function stableSnakeKey(value, fallback) {
    var text = String(value || "")
      .replace(/([a-z0-9])([A-Z])/g, "$1_$2")
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "_")
      .replace(/^_+|_+$/g, "")
      .replace(/_+/g, "_");
    if (!/^[a-z_][a-z0-9_]*$/.test(text)) return fallback;
    return text;
  }

  function looksPrivateManagementValue(value) {
    var text = String(value || "").trim();
    return (
      /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(text) ||
      /^\//.test(text) ||
      /^[a-zA-Z]:[\\/]/.test(text) ||
      /^\\\\/.test(text) ||
      /^file:\/\//i.test(text) ||
      /^~[\\/]/.test(text)
    );
  }

  function managementFingerprint(value) {
    var hash = 2166136261;
    var input = String(value || "");
    for (var index = 0; index < input.length; index += 1) {
      hash ^= input.charCodeAt(index);
      hash = Math.imul(hash, 16777619);
    }
    return ("000000" + (hash >>> 0).toString(16)).slice(-6);
  }

  function managementDisplayLabel(value, identity, fallbackKey) {
    var label = String(value || "").trim();
    if (label && label !== "." && !looksPrivateManagementValue(label)) return label;
    return t(fallbackKey) + " · " + managementFingerprint(identity || label || fallbackKey);
  }

  function sourceRootDisplayLabel(root) {
    var path = String(root && root.current_path || "").replace(/[\\/]+$/, "");
    var basename = path.split(/[\\/]/).filter(Boolean).pop() || "";
    if (!basename || basename === "." || basename === ".." || looksPrivateManagementValue(basename)) {
      basename = t("javascriptSourceRoot");
    }
    return basename + " · " + managementFingerprint(root && root.root_id);
  }

  function selectDiscoveredSourceRoot(value) {
    var payload = value && typeof value === "object" ? value : {};
    var root = payload.source_root ||
      (payload.discovery && payload.discovery.source_root) ||
      null;
    if (
      !root ||
      typeof root !== "object" ||
      String(root.root_id || "") === "" ||
      String(root.status || "") !== "bound"
    ) {
      return false;
    }
    if (!ingestionManagement.sourceRoots.some(function (item) {
      return String(item.root_id || "") === String(root.root_id);
    })) {
      ingestionManagement.sourceRoots.push(root);
    }
    ingestionManagement.selectedSourceRootId = String(root.root_id);
    ingestionManagement.sourceRootSelectionStale = false;
    if (ingestionManagement.errorKey === "sourceRootSelectionStale") {
      ingestionManagement.errorKey = "";
    }
    return true;
  }

  function reviewIdentityDefaults(item, candidate, reviewName) {
    var payload = candidate && candidate.ephemeral_capture_payload;
    var selected = payload && payload.selected_function;
    var mapping = payload && payload.mapping;
    var exportName = selected && selected.export_name;
    var base = stableSnakeKey(exportName || reviewName, "captured_calculation");
    var result = stableSnakeKey(mapping && mapping.result_field, base);
    if (result === "result") result = base;
    var display = String(exportName || reviewName || "Captured calculation")
      .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
      .replace(/[_-]+/g, " ")
      .trim();
    if (!display) display = "Captured calculation";
    return {
      capability_key: stableSnakeKey(candidate && candidate.suggested_capability_key, base + "_calculation"),
      role_key: stableSnakeKey(candidate && candidate.suggested_role_key, result),
      variant_key: "default",
      display_name: String(candidate && candidate.suggested_display_name || display),
    };
  }

  function emptyManagementList(container, key) {
    if (!container) return;
    var item = document.createElement("p");
    item.className = "warehouse-empty";
    item.textContent = t(key);
    container.appendChild(item);
  }

  function managementBrandProfile(project) {
    var profile = project && project.brand_profile_json;
    if (profile && typeof profile === "object" && !Array.isArray(profile)) return profile;
    if (typeof profile === "string") {
      try {
        var parsed = JSON.parse(profile);
        if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) return parsed;
      } catch (_error) {
        return {};
      }
    }
    return {};
  }

  function createBrandEditor(project) {
    var wrap = document.createElement("div");
    wrap.className = "warehouse-actions warehouse-brand-editor";
    var modeLabel = document.createElement("label");
    modeLabel.className = "warehouse-field";
    modeLabel.appendChild(document.createTextNode(t("brandMode")));
    var mode = document.createElement("select");
    [
      ["inherit", "brandInherit"],
      ["clear", "brandClear"],
      ["replace", "brandReplace"],
    ].forEach(function (definition) {
      var option = document.createElement("option");
      option.value = definition[0];
      option.textContent = t(definition[1]);
      mode.appendChild(option);
    });
    var savedMode = String((project && project.brand_mode) || "inherit");
    mode.value = ["inherit", "clear", "replace"].indexOf(savedMode) >= 0
      ? savedMode
      : "inherit";
    modeLabel.appendChild(mode);
    wrap.appendChild(modeLabel);

    var profileLabel = document.createElement("label");
    profileLabel.className = "warehouse-field warehouse-brand-profile";
    profileLabel.appendChild(document.createTextNode(t("brandProfile")));
    var profile = document.createElement("textarea");
    profile.rows = 3;
    profile.maxLength = 32768;
    profile.spellcheck = false;
    profile.value = JSON.stringify(managementBrandProfile(project), null, 2);
    profileLabel.appendChild(profile);
    wrap.appendChild(profileLabel);

    function sync() {
      profileLabel.classList.toggle("hidden", mode.value !== "replace");
    }
    mode.addEventListener("change", sync);
    sync();
    return {
      element: wrap,
      read: function () {
        var result = { brand_mode: mode.value };
        if (mode.value === "replace") {
          try {
            var parsed = JSON.parse(profile.value || "{}");
            if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error("object required");
            result.brand_profile = parsed;
          } catch (_error) {
            setManagementStatus("brandProfileInvalid");
            profile.focus();
            return null;
          }
        }
        return result;
      },
    };
  }

  function submitProjectConfirmations(entries, onComplete) {
    bridgeCall("confirm_projects", JSON.stringify({ projects: entries })).then(function (raw) {
      var result = parseBridgeJson(raw);
      var payload = managementPayload(result);
      if (!payload) {
        setManagementStatus(managementError(result));
        return;
      }
      var errors = Array.isArray(payload.errors) ? payload.errors : [];
      if (errors.length) setManagementStatus("projectConfirmationPartial");
      if (typeof onComplete === "function") onComplete(errors);
      if (!trackManagementRuns(result)) refreshIngestionManagement();
    });
  }

  function adapterSafeInteger(control) {
    var text = String(control.value || "").trim();
    var value = Number(text);
    if (!text || !Number.isSafeInteger(value)) {
      if (typeof control.reportValidity === "function") control.reportValidity();
      return null;
    }
    return value;
  }

  function refreshAdapterReviewItems(onComplete) {
    bridgeCall("list_review_items", JSON.stringify({})).then(function (raw) {
      var result = parseBridgeJson(raw);
      if (!managementPayload(result)) {
        setManagementStatus(managementError(result));
        return;
      }
      ingestionManagement.reviewItems = managementList(result, ["review_items", "items"]);
      renderManagementReviews();
      if (typeof onComplete === "function") onComplete(ingestionManagement.reviewItems);
    });
  }

  function renderJavascriptComputationOffers(projectBlock, project, inspection) {
    if (!inspection || inspection.schema !== "computation_capture_offers.v2") return;
    var offers = Array.isArray(inspection.offers) ? inspection.offers : [];
    var resumableReviews = ingestionManagement.reviewItems.filter(function (item) {
      return item && item.adapter_contract_version_expired !== true &&
        String(item.project_id || "") === String(inspection.project_id || "") &&
        item.candidate_status === "waiting_user" &&
        item.resume_contract === "resubmit_ephemeral_capture.v1";
    });
    var panel = document.createElement("div");
    panel.className = "warehouse-project-config";
    if (!offers.length) {
      emptyManagementList(panel, "noJavascriptComputations");
      projectBlock.appendChild(panel);
      return;
    }
    offers.forEach(function (offer) {
      var resumeKey = String(offer.offer_id || "");
      var parameters = Array.isArray(offer.parameters) ? offer.parameters : [];
      var details = document.createElement("details");
      details.className = "warehouse-review";
      details.title = t("adapterSimpleHelp");
      var summary = document.createElement("summary");
      summary.appendChild(document.createTextNode(String(offer.export_name || "function")));
      var signatureMeta = document.createElement("span");
      signatureMeta.className = "warehouse-developer-only warehouse-meta";
      signatureMeta.textContent = "(" + parameters.map(function (item) {
        return String(item.name || "parameter");
      }).join(", ") + ")";
      summary.appendChild(signatureMeta);
      var sourceMeta = document.createElement("span");
      sourceMeta.className = "warehouse-developer-only warehouse-meta";
      sourceMeta.textContent = " · " + [offer.module_relpath, String(offer.dependency_count || 0)].filter(Boolean).join(" · ");
      summary.appendChild(sourceMeta);
      details.appendChild(summary);

      var resumeReview = controlHelp(document.createElement("select"), "captureResumeReviewHelp");
      var newReview = document.createElement("option");
      newReview.value = "";
      newReview.textContent = t("captureResumeReview");
      resumeReview.appendChild(newReview);
      resumableReviews.forEach(function (item, reviewIndex) {
        var option = document.createElement("option");
        option.value = String(item.review_id || "");
        option.textContent = t("captureReview") + " · " + String(item.created_at || reviewIndex + 1);
        option.title = String(item.review_id || "");
        if (option.value === ingestionManagement.captureResume[resumeKey]) option.selected = true;
        resumeReview.appendChild(option);
      });
      if (!resumeReview.value && resumableReviews.length === 1 && offers.length === 1) {
        resumeReview.value = String(resumableReviews[0].review_id || "");
        ingestionManagement.captureResume[resumeKey] = resumeReview.value;
      }
      var resumeLabel = document.createElement("label");
      resumeLabel.className = "warehouse-field" +
        (resumableReviews.length > 0 && !(resumableReviews.length === 1 && offers.length === 1)
          ? ""
          : " warehouse-developer-only");
      resumeLabel.textContent = t("captureResumeReview");
      resumeLabel.title = t("captureResumeReviewHelp");
      resumeLabel.appendChild(resumeReview);
      details.appendChild(resumeLabel);

      var argumentControls = [];
      parameters.forEach(function (parameter, parameterIndex) {
        var row = document.createElement("div");
        row.className = "warehouse-actions";
        var name = document.createElement("strong");
        name.className = "warehouse-meta";
        name.textContent = formatText("adapterInputSourceLabel", {
          index: parameterIndex + 1,
          parameter: String(parameter.name || "parameter"),
        });
        name.title = t("adapterInputFieldHelp");
        row.appendChild(name);

        var field = controlHelp(document.createElement("input"), "adapterInputFieldHelp");
        field.type = "text";
        field.required = true;
        field.pattern = "[a-z][a-z0-9]*(?:_[a-z0-9]+)*";
        field.autocomplete = "off";
        field.spellcheck = false;
        if (/^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$/.test(String(parameter.name || ""))) field.value = String(parameter.name);
        var fieldLabel = document.createElement("label");
        fieldLabel.className = "warehouse-field";
        fieldLabel.textContent = t("adapterInputField");
        fieldLabel.title = t("adapterInputFieldHelp");
        fieldLabel.appendChild(field);
        row.appendChild(fieldLabel);
        var fieldHelp = document.createElement("span");
        fieldHelp.id = "adapter-input-help-" + resumeKey.slice(0, 12) + "-" + parameterIndex;
        fieldHelp.className = "warehouse-meta";
        fieldHelp.textContent = t("adapterInputFieldVisibleHelp");
        field.setAttribute("aria-describedby", fieldHelp.id);
        row.appendChild(fieldHelp);

        var kind = controlHelp(document.createElement("select"), "adapterInputKindHelp");
        var inputKinds = [["integer", "integer"], ["boolean", "boolean"], ["enum", "enum"]];
        if (parameters.length === 1) inputKinds.push(["string", "string"]);
        inputKinds.forEach(function (entry) {
          var option = document.createElement("option");
          option.value = entry[0];
          option.textContent = entry[1];
          kind.appendChild(option);
        });
        var kindLabel = document.createElement("label");
        kindLabel.className = "warehouse-field warehouse-developer-only";
        kindLabel.textContent = t("adapterInputKind");
        kindLabel.title = t("adapterInputKindHelp");
        kindLabel.appendChild(kind);
        row.appendChild(kindLabel);

        var minimum = controlHelp(document.createElement("input"), "adapterMinimumHelp");
        minimum.type = "number";
        minimum.step = "1";
        minimum.placeholder = "0";
        var minimumLabel = document.createElement("label");
        minimumLabel.className = "warehouse-field";
        minimumLabel.textContent = t("adapterMinimum");
        minimumLabel.title = t("adapterMinimumHelp");
        minimumLabel.appendChild(minimum);
        row.appendChild(minimumLabel);
        var maximum = controlHelp(document.createElement("input"), "adapterMaximumHelp");
        maximum.type = "number";
        maximum.step = "1";
        maximum.placeholder = "10000";
        var maximumLabel = document.createElement("label");
        maximumLabel.className = "warehouse-field";
        maximumLabel.textContent = t("adapterMaximum");
        maximumLabel.title = t("adapterMaximumHelp");
        maximumLabel.appendChild(maximum);
        row.appendChild(maximumLabel);
        var values = controlHelp(document.createElement("textarea"), "adapterEnumValuesHelp");
        values.rows = 2;
        var valuesLabel = document.createElement("label");
        valuesLabel.className = "warehouse-field warehouse-developer-only";
        valuesLabel.textContent = t("adapterEnumValues");
        valuesLabel.title = t("adapterEnumValuesHelp");
        valuesLabel.appendChild(values);
        row.appendChild(valuesLabel);
        var example = controlHelp(document.createElement("input"), "adapterExampleHelp");
        example.type = "text";
        example.required = true;
        example.placeholder = "4";
        var exampleLabel = document.createElement("label");
        exampleLabel.className = "warehouse-field";
        exampleLabel.textContent = t("adapterExample");
        exampleLabel.title = t("adapterExampleHelp");
        exampleLabel.appendChild(example);
        row.appendChild(exampleLabel);
        var controls = {
          parameter_binding_id: String(parameter.parameter_binding_id || ""),
          source_name: String(parameter.name || "parameter"),
          field: field,
          kind: kind,
          minimum: minimum,
          minimumLabel: minimumLabel,
          maximum: maximum,
          maximumLabel: maximumLabel,
          values: values,
          valuesLabel: valuesLabel,
          example: example,
          exampleLabel: exampleLabel,
        };
        function syncKind() {
          var integer = kind.value === "integer";
          var enumeration = kind.value === "enum";
          var boundedString = kind.value === "string";
          minimumLabel.classList.toggle("hidden", !integer && !boundedString);
          maximumLabel.classList.toggle("hidden", !integer && !boundedString);
          valuesLabel.classList.toggle("hidden", !enumeration);
          exampleLabel.classList.toggle("hidden", boundedString);
          minimum.required = integer || boundedString;
          maximum.required = integer || boundedString;
          values.required = enumeration;
          example.required = !boundedString;
        }
        kind.addEventListener("change", syncKind);
        syncKind();
        argumentControls.push(controls);
        details.appendChild(row);
      });

      var resultRow = document.createElement("div");
      resultRow.className = "warehouse-actions";
      var resultField = controlHelp(document.createElement("input"), "adapterResultFieldHelp");
      resultField.type = "text";
      resultField.pattern = "[a-z][a-z0-9]*(?:_[a-z0-9]+)*";
      resultField.required = true;
      resultField.value = "result";
      var resultLabel = document.createElement("label");
      resultLabel.className = "warehouse-field";
      resultLabel.textContent = t("adapterResultField");
      resultLabel.title = t("adapterResultFieldHelp");
      resultLabel.appendChild(resultField);
      resultRow.appendChild(resultLabel);
      var resultHelp = document.createElement("span");
      resultHelp.id = "adapter-result-help-" + resumeKey.slice(0, 12);
      resultHelp.className = "warehouse-meta";
      resultHelp.textContent = t("adapterResultFieldVisibleHelp");
      resultField.setAttribute("aria-describedby", resultHelp.id);
      resultRow.appendChild(resultHelp);
      var expected = controlHelp(document.createElement("input"), "adapterExpectedHelp");
      expected.type = "number";
      expected.step = "1";
      expected.required = true;
      expected.placeholder = "20";
      var expectedLabel = document.createElement("label");
      expectedLabel.className = "warehouse-field";
      expectedLabel.textContent = t("adapterExpected");
      expectedLabel.title = t("adapterExpectedHelp");
      expectedLabel.appendChild(expected);
      resultRow.appendChild(expectedLabel);
      var resultEnum = controlHelp(document.createElement("textarea"), "adapterResultEnumHelp");
      resultEnum.rows = 3;
      var resultEnumLabel = document.createElement("label");
      resultEnumLabel.className = "warehouse-field warehouse-developer-only hidden";
      resultEnumLabel.textContent = t("adapterResultEnum");
      resultEnumLabel.title = t("adapterResultEnumHelp");
      resultEnumLabel.appendChild(resultEnum);
      resultRow.appendChild(resultEnumLabel);
      details.appendChild(resultRow);
      var witnessRows = document.createElement("div");
      witnessRows.className = "warehouse-project-config warehouse-developer-only hidden";
      details.appendChild(witnessRows);
      var witnessControls = [];
      function captureUsesBoundedString() {
        return argumentControls.length === 1 &&
          argumentControls[0].kind.value === "string";
      }
      function resultEnumValues() {
        return String(resultEnum.value || "")
          .split(/\r?\n/)
          .map(function (value) { return value.trim(); })
          .filter(Boolean);
      }
      function renderWitnessRows() {
        var previous = {};
        witnessControls.forEach(function (control) {
          previous[control.result] = String(control.input.value || "");
        });
        witnessControls = [];
        witnessRows.innerHTML = "";
        resultEnumValues().forEach(function (value) {
          var label = document.createElement("label");
          label.className = "warehouse-field";
          label.textContent = formatText("adapterWitness", { value: value });
          label.title = t("adapterWitnessHelp");
          var input = controlHelp(document.createElement("input"), "adapterWitnessHelp");
          input.type = "text";
          input.maxLength = 10000;
          input.value = previous[value] || "";
          label.appendChild(input);
          witnessRows.appendChild(label);
          witnessControls.push({ result: value, input: input });
        });
      }
      function syncCaptureMode() {
        var boundedString = captureUsesBoundedString();
        expectedLabel.classList.toggle("hidden", boundedString);
        expected.required = !boundedString;
        resultEnumLabel.classList.toggle("hidden", !boundedString);
        resultEnum.required = boundedString;
        witnessRows.classList.toggle("hidden", !boundedString);
        argumentControls.forEach(function (control) {
          if (control.minimumLabel.firstChild) {
            control.minimumLabel.firstChild.nodeValue =
              t(boundedString ? "adapterMinimumLength" : "adapterMinimum");
          }
          if (control.maximumLabel.firstChild) {
            control.maximumLabel.firstChild.nodeValue =
              t(boundedString ? "adapterMaximumLength" : "adapterMaximum");
          }
        });
        if (boundedString) renderWitnessRows();
      }

      var preview = document.createElement("p");
      preview.className = "warehouse-meta warehouse-mapping-preview warehouse-developer-only";
      preview.title = t("adapterSimpleHelp");
      details.appendChild(preview);
      function updatePreview() {
        var boundedString = captureUsesBoundedString();
        var parts = argumentControls.map(function (control) {
          var fieldName = String(control.field.value || "?").trim() || "?";
          var domain = control.kind.value === "integer"
            ? String(control.minimum.value || "?") + "…" + String(control.maximum.value || "?")
            : (control.kind.value === "enum"
              ? String(control.values.value || "?").split(/\r?\n/).filter(Boolean).join("|")
              : (control.kind.value === "string"
                ? "string " + String(control.minimum.value || "?") + "…" + String(control.maximum.value || "?")
                : "boolean"));
          return control.source_name + " → " + fieldName + " [" + domain + "]" +
            (boundedString ? "" : " = " + String(control.example.value || "?"));
        });
        parts.push(String(resultField.value || "result") + " = " +
          (boundedString ? resultEnumValues().join("|") || "?" : String(expected.value || "?")));
        preview.textContent = formatText("adapterMappingPreview", { mapping: parts.join("；") });
      }
      argumentControls.forEach(function (control) {
        [control.field, control.kind, control.minimum, control.maximum, control.values, control.example].forEach(function (input) {
          input.addEventListener("input", updatePreview);
          input.addEventListener("change", updatePreview);
        });
      });
      [resultField, expected].forEach(function (input) { input.addEventListener("input", updatePreview); });
      argumentControls.forEach(function (control) {
        control.kind.addEventListener("change", function () {
          syncCaptureMode();
          updatePreview();
        });
      });
      resultEnum.addEventListener("input", function () {
        renderWitnessRows();
        updatePreview();
      });
      syncCaptureMode();
      updatePreview();

      var confirmationLabel = document.createElement("label");
      confirmationLabel.className = "warehouse-project-choice";
      confirmationLabel.title = t("adapterMappingConfirmation");
      var confirmation = document.createElement("input");
      confirmation.type = "checkbox";
      confirmation.required = true;
      confirmation.title = t("adapterMappingConfirmation");
      confirmationLabel.appendChild(confirmation);
      confirmationLabel.appendChild(document.createTextNode(" " + t("adapterMappingConfirmShort")));
      details.appendChild(confirmationLabel);

      var offerStatus = document.createElement("p");
      offerStatus.className = "warehouse-status";
      offerStatus.setAttribute("aria-live", "polite");
      details.appendChild(offerStatus);
      var create = controlHelp(document.createElement("button"), "createComputationAdapter");
      create.type = "button";
      create.className = "btn-ghost";
      create.setAttribute("data-action", "create-javascript-computation-capture");
      function syncCreateLabel() {
        create.textContent = resumeReview.value ? t("continueCaptureValidation") : t("createComputationAdapter");
        create.dataset.resumeReviewId = String(resumeReview.value || "");
        var selectedReview = resumableReviews.find(function (item) {
          return String(item.review_id || "") === String(resumeReview.value || "");
        });
        var decisionsRemaining = selectedReview && Array.isArray(selectedReview.allowed_decisions)
          ? selectedReview.allowed_decisions.length > 0
          : false;
        create.disabled = Boolean(resumeReview.value && decisionsRemaining);
        if (selectedReview) {
          var resumeStatus = decisionsRemaining ? "captureNeedsDecision" : "captureResubmitRequired";
          offerStatus.textContent = t(resumeStatus);
          offerStatus.classList.add("is-waiting");
          offerStatus.classList.remove("is-error");
        }
        if (resumeReview.value) {
          ingestionManagement.captureResume[resumeKey] = String(resumeReview.value);
          ingestionManagement.captureReviewContext[String(resumeReview.value)] = {
            offer_name: String(offer.export_name || "function") + "(" + parameters.map(function (item) {
              return String(item.name || "parameter");
            }).join(", ") + ")",
          };
        }
      }
      resumeReview.addEventListener("change", function () {
        syncCreateLabel();
        renderManagementReviews();
      });
      syncCreateLabel();
      create.addEventListener("click", function () {
        if (!confirmation.checked) {
          confirmation.reportValidity();
          return;
        }
        var argumentsPayload = [];
        var exampleInput = {};
        var fields = {};
        var boundedString = captureUsesBoundedString();
        for (var index = 0; index < argumentControls.length; index += 1) {
          var control = argumentControls[index];
          var fieldName = String(control.field.value || "").trim();
          var kindName = String(control.kind.value || "");
          if (!control.field.checkValidity() || fields[fieldName]) {
            setManagementStatus("adapterMappingInvalid");
            return;
          }
          var argument = {
            parameter_binding_id: control.parameter_binding_id,
            input_field: fieldName,
            kind: kindName,
          };
          var exampleValue;
          if (kindName === "integer") {
            var minimumValue = adapterSafeInteger(control.minimum);
            var maximumValue = adapterSafeInteger(control.maximum);
            var integerExample = Number(String(control.example.value || "").trim());
            if (minimumValue === null || maximumValue === null || !Number.isSafeInteger(integerExample) || minimumValue > maximumValue || integerExample < minimumValue || integerExample > maximumValue) {
              setManagementStatus("adapterMappingInvalid");
              return;
            }
            argument.minimum = minimumValue;
            argument.maximum = maximumValue;
            exampleValue = integerExample;
          } else if (kindName === "boolean") {
            if (!["true", "false"].includes(String(control.example.value).trim())) {
              setManagementStatus("adapterMappingInvalid");
              return;
            }
            exampleValue = String(control.example.value).trim() === "true";
          } else if (kindName === "enum") {
            var enumValues = String(control.values.value || "").split(/\r?\n/).filter(function (value) { return value !== ""; });
            exampleValue = String(control.example.value || "");
            if (!enumValues.length || enumValues.indexOf(exampleValue) < 0) {
              setManagementStatus("adapterMappingInvalid");
              return;
            }
            argument.values = enumValues;
          } else if (kindName === "string" && boundedString) {
            var minimumLength = adapterSafeInteger(control.minimum);
            var maximumLength = adapterSafeInteger(control.maximum);
            if (
              minimumLength === null ||
              maximumLength === null ||
              minimumLength < 0 ||
              minimumLength > maximumLength ||
              maximumLength > 10000
            ) {
              setManagementStatus("adapterMappingInvalid");
              return;
            }
            argument.min_length = minimumLength;
            argument.max_length = maximumLength;
          } else {
            setManagementStatus("adapterMappingInvalid");
            return;
          }
          fields[fieldName] = true;
          argumentsPayload.push(argument);
          if (!boundedString) exampleInput[fieldName] = exampleValue;
        }
        var resultName = String(resultField.value || "").trim();
        if (!resultField.checkValidity() || fields[resultName]) {
          setManagementStatus("adapterMappingInvalid");
          return;
        }
        var capturePayload = {
          project_id: String(inspection.project_id || project.project_id || ""),
          offer_id: String(offer.offer_id || ""),
          review_id: String(resumeReview.value || "") || null,
          arguments: argumentsPayload,
          result_field: resultName,
        };
        if (boundedString) {
          var enumResults = resultEnumValues();
          var uniqueResults = new Set(enumResults);
          var argumentField = argumentsPayload[0] && argumentsPayload[0].input_field;
          var minimumWitnessLength = argumentsPayload[0] && argumentsPayload[0].min_length;
          var maximumWitnessLength = argumentsPayload[0] && argumentsPayload[0].max_length;
          if (
            !resultEnum.checkValidity() ||
            !enumResults.length ||
            enumResults.length > 32 ||
            uniqueResults.size !== enumResults.length ||
            witnessControls.length !== enumResults.length ||
            witnessControls.some(function (control, witnessIndex) {
              var text = String(control.input.value || "");
              return control.result !== enumResults[witnessIndex] ||
                text.length < minimumWitnessLength ||
                text.length > maximumWitnessLength;
            })
          ) {
            setManagementStatus("adapterMappingInvalid");
            return;
          }
          capturePayload.schema = "computation_capture_mapping.v5";
          capturePayload.result_enum = enumResults;
          capturePayload.proof_schema = "source_graph_proof.v3";
          capturePayload.examples = witnessControls.map(function (control) {
            var input = {};
            var output = {};
            input[argumentField] = String(control.input.value || "");
            output[resultName] = control.result;
            return { input: input, expected: output };
          });
        } else {
          var expectedValue = adapterSafeInteger(expected);
          if (expectedValue === null) {
            setManagementStatus("adapterMappingInvalid");
            return;
          }
          capturePayload.examples = [{ input: exampleInput, expected: expectedValue }];
        }
        startManagementRun("start_create_computation_adapter", capturePayload, function (run) {
          var outcome = run && run.data && typeof run.data === "object" ? run.data : {};
          var statusKey = captureOutcomeStatusKey(outcome);
          offerStatus.textContent = t(statusKey);
          offerStatus.classList.toggle("is-waiting", captureStatusIsWaiting(statusKey));
          offerStatus.classList.toggle("is-error", ["captureRejected", "captureOutcomeUnknown"].indexOf(statusKey) >= 0);
          if (outcome.status === "waiting_user" && outcome.review_id) {
            ingestionManagement.captureResume[resumeKey] = String(outcome.review_id);
            ingestionManagement.captureReviewContext[String(outcome.review_id)] = {
              offer_name: String(offer.export_name || "function") + "(" + parameters.map(function (item) {
                return String(item.name || "parameter");
              }).join(", ") + ")",
            };
            if (!Array.prototype.some.call(resumeReview.options, function (option) { return option.value === String(outcome.review_id); })) {
              var resumeOption = document.createElement("option");
              resumeOption.value = String(outcome.review_id);
              resumeOption.textContent = t("captureReview") + " · " + String(outcome.review_id).slice(0, 8);
              resumeOption.title = String(outcome.review_id);
              resumeReview.appendChild(resumeOption);
            }
            resumeReview.value = String(outcome.review_id);
            syncCreateLabel();
            create.disabled = true;
            setManagementStatus("captureNeedsDecision");
          } else {
            delete ingestionManagement.captureResume[resumeKey];
            resumeReview.value = "";
            syncCreateLabel();
            setManagementStatus(statusKey);
          }
          refreshAdapterReviewItems();
        }, false);
      });
      details.appendChild(create);
      panel.appendChild(details);
    });
    projectBlock.appendChild(panel);
  }

  function computationScanEligibility(project) {
    var sourceType = String(project && project.source_type || "");
    var status = String(project && project.project_state || "");
    var knownType = sourceType === "javascript_computation_source" || sourceType === "static_web";
    if (!project || !project.project_id) {
      return { enabled: false, messageKey: "projectScanIncomplete" };
    }
    if (!knownType) {
      return { enabled: false, messageKey: "projectScanUnknownType" };
    }
    if (["source_platform_unsupported_v1", "platform_unsupported"].indexOf(status) >= 0) {
      return { enabled: false, messageKey: "projectScanPlatformUnsupported" };
    }
    if (status === "source_missing") {
      return { enabled: false, messageKey: "projectScanSourceMissing" };
    }
    if (["discovered_unconfirmed", "pending_confirmation"].indexOf(status) >= 0) {
      return { enabled: false, messageKey: "projectScanPending" };
    }
    if (status === "ready") {
      return { enabled: true, messageKey: "projectScanReady" };
    }
    if (sourceType === "static_web" && status === "unsupported_v1") {
      return { enabled: true, messageKey: "projectScanStaticUnsupported" };
    }
    return { enabled: false, messageKey: "projectScanUnknownState" };
  }

  function sourceHandoffStatusProjection(value) {
    var raw = value && typeof value === "object" && !Array.isArray(value)
      ? (value.source_handoff && typeof value.source_handoff === "object"
        ? value.source_handoff
        : value)
      : null;
    if (!raw) return null;
    var statuses = ["none", "active", "revoked", "stale", "conflict"];
    if (
      raw.schema_version !== "source_handoff_status.v1" ||
      statuses.indexOf(String(raw.status || "")) < 0
    ) {
      return {
        schema_version: "source_handoff_status.v1",
        status: "conflict",
        created_at: null,
        revoked_at: null,
        run_id: null,
        run_status: null,
      };
    }
    return {
      schema_version: "source_handoff_status.v1",
      status: String(raw.status),
      created_at: typeof raw.created_at === "string" ? raw.created_at : null,
      revoked_at: typeof raw.revoked_at === "string" ? raw.revoked_at : null,
      run_id: typeof raw.run_id === "string" ? raw.run_id : null,
      run_status: typeof raw.run_status === "string" ? raw.run_status : null,
    };
  }

  function updateProjectSourceHandoff(projectId, value, fallbackStatus) {
    var projection = sourceHandoffStatusProjection(value);
    if (!projection && fallbackStatus) {
      projection = sourceHandoffStatusProjection({
        schema_version: "source_handoff_status.v1",
        status: fallbackStatus,
      });
    }
    ingestionManagement.projects.forEach(function (project) {
      if (String(project.project_id || "") === String(projectId || "")) {
        project.source_handoff = projection;
      }
    });
  }

  function sourceHandoffStatusKey(status) {
    return {
      active: "sourceAgentActive",
      revoked: "sourceAgentRevoked",
      stale: "sourceAgentStale",
      conflict: "sourceAgentConflict",
    }[String(status || "")] || "";
  }

  function sourceDerivedHandoffProjection(value) {
    var raw = value && typeof value === "object" && !Array.isArray(value)
      ? value
      : null;
    var statuses = ["none", "active", "revoked", "stale", "conflict"];
    var proposalStatuses = ["none", "pending", "approved", "rejected"];
    if (
      !raw ||
      raw.schema_version !== "source_derived_handoff_status.v1" ||
      statuses.indexOf(String(raw.status || "")) < 0 ||
      proposalStatuses.indexOf(String(raw.proposal_status || "")) < 0
    ) {
      return {
        schema_version: "source_derived_handoff_status.v1",
        status: raw ? "conflict" : "none",
        proposal_status: "none",
        proposal: null,
      };
    }
    return {
      schema_version: "source_derived_handoff_status.v1",
      status: String(raw.status),
      proposal_status: String(raw.proposal_status),
      proposal: raw.proposal && typeof raw.proposal === "object"
        ? raw.proposal
        : null,
    };
  }

  function renderManagementProjects() {
    var container = $("warehouse-projects");
    if (!container) return;
    container.innerHTML = "";
    if (ingestionManagement.sourceRoots.length) {
      var boundSourceRoots = ingestionManagement.sourceRoots.filter(function (root) {
        return String(root.status || "") === "bound" && String(root.root_id || "") !== "";
      });
      var sourceRootControls = [];
      var sourceRootActions = [];
      function selectedSourceRoot() {
        return boundSourceRoots.find(function (root) {
          return String(root.root_id || "") === ingestionManagement.selectedSourceRootId;
        }) || null;
      }
      function syncSourceRootControls() {
        var selected = selectedSourceRoot();
        sourceRootControls.forEach(function (select) {
          var index = selected ? boundSourceRoots.indexOf(selected) : -1;
          select.value = index >= 0 ? String(index) : "";
        });
        sourceRootActions.forEach(function (button) {
          button.disabled = !selected;
        });
      }
      function sourceRootSelect() {
        var select = controlHelp(document.createElement("select"), "javascriptSourceRootHelp");
        select.dataset.sourceRootSelector = "session";
        var placeholder = document.createElement("option");
        placeholder.value = "";
        placeholder.textContent = t("sourceRootSelectionRequired");
        select.appendChild(placeholder);
        boundSourceRoots.forEach(function (root, index) {
          var option = document.createElement("option");
          option.value = String(index);
          option.textContent = sourceRootDisplayLabel(root);
          select.appendChild(option);
        });
        select.addEventListener("change", function () {
          var index = Number(select.value);
          var root = Number.isInteger(index) ? boundSourceRoots[index] : null;
          ingestionManagement.selectedSourceRootId = root ? String(root.root_id) : "";
          ingestionManagement.sourceRootSelectionStale = false;
          if (
            ingestionManagement.errorKey === "sourceRootSelectionRequired" ||
            ingestionManagement.errorKey === "sourceRootSelectionStale"
          ) {
            setManagementStatus("");
          }
          syncSourceRootControls();
        });
        sourceRootControls.push(select);
        return select;
      }
      var registration = document.createElement("div");
      registration.className = "warehouse-project-config";
      var rootSelect = sourceRootSelect();
      var rootLabel = document.createElement("label");
      rootLabel.className = "warehouse-field";
      rootLabel.textContent = t("javascriptSourceRoot");
      rootLabel.title = t("javascriptSourceRootHelp");
      rootLabel.appendChild(rootSelect);
      var relpath = controlHelp(document.createElement("input"), "javascriptProjectRelpathHelp");
      relpath.type = "text";
      relpath.value = ".";
      relpath.placeholder = t("javascriptProjectRelpath");
      var relpathLabel = document.createElement("label");
      relpathLabel.className = "warehouse-field warehouse-developer-only";
      relpathLabel.textContent = t("javascriptProjectRelpath");
      relpathLabel.title = t("javascriptProjectRelpathHelp");
      relpathLabel.appendChild(relpath);
      var displayName = controlHelp(document.createElement("input"), "javascriptDisplayNameHelp");
      displayName.type = "text";
      displayName.placeholder = t("javascriptDisplayName");
      displayName.maxLength = 200;
      var displayNameLabel = document.createElement("label");
      displayNameLabel.className = "warehouse-field warehouse-developer-only";
      displayNameLabel.textContent = t("javascriptDisplayName");
      displayNameLabel.title = t("javascriptDisplayNameHelp");
      displayNameLabel.appendChild(displayName);
      var register = controlHelp(document.createElement("button"), "registerJavascriptSourceHelp");
      register.type = "button";
      register.className = "btn-ghost";
      register.setAttribute("data-action", "register-javascript-computation-source");
      register.textContent = t("registerJavascriptSource");
      register.addEventListener("click", function () {
        var selected = selectedSourceRoot();
        if (!selected) {
          setManagementStatus("sourceRootSelectionRequired");
          syncSourceRootControls();
          return;
        }
        var relpathValue = String(relpath.value || ".").trim() || ".";
        var rootName = sourceRootDisplayLabel(selected).split(" · ")[0];
        var inferredName = relpathValue === "."
          ? rootName.split(/[\\/]/).filter(Boolean).pop()
          : relpathValue.split("/").filter(Boolean).pop();
        var name = String(displayName.value || inferredName || "source").trim();
        bridgeCall("register_javascript_computation_source", JSON.stringify({
          source_root_id: String(selected.root_id),
          project_relpath: relpathValue,
          display_name: name,
        })).then(function (raw) {
          var result = parseBridgeJson(raw);
          if (!managementPayload(result)) {
            setManagementStatus(managementError(result));
            return;
          }
          refreshIngestionManagement();
        });
      });
      registration.appendChild(rootLabel);
      registration.appendChild(relpathLabel);
      registration.appendChild(displayNameLabel);
      registration.appendChild(register);
      sourceRootActions.push(register);
      container.appendChild(registration);

      var sourceDerivedAgent = document.createElement("fieldset");
      sourceDerivedAgent.className = "warehouse-project-config";
      var sourceDerivedAgentLegend = document.createElement("legend");
      sourceDerivedAgentLegend.textContent = t("sourceDerivedAgentTitle");
      sourceDerivedAgent.appendChild(sourceDerivedAgentLegend);
      boundSourceRoots.forEach(function (root) {
        var rootId = String(root.root_id || "");
        var projection = sourceDerivedHandoffProjection(
          root.source_derived_handoff
        );
        var row = document.createElement("div");
        row.className = "warehouse-project-config";
        var name = document.createElement("strong");
        name.textContent = sourceRootDisplayLabel(root);
        row.appendChild(name);
        var status = document.createElement("p");
        status.className = "warehouse-meta";
        var statusKey = {
          active: "sourceDerivedAgentActive",
          revoked: "sourceDerivedAgentRevoked",
          stale: "sourceDerivedAgentStale",
          conflict: "sourceDerivedAgentConflict",
        }[projection.status] || "";
        if (
          projection.status === "active" &&
          projection.proposal_status === "none"
        ) {
          statusKey = "sourceDerivedAgentWaiting";
        } else if (projection.proposal_status === "approved") {
          statusKey = "sourceDerivedAgentApproved";
        } else if (projection.proposal_status === "rejected") {
          statusKey = "sourceDerivedAgentRejected";
        }
        status.textContent = statusKey ? t(statusKey) : "";
        row.appendChild(status);

        if (
          projection.status === "active" &&
          projection.proposal_status === "pending" &&
          projection.proposal
        ) {
          var proposal = projection.proposal;
          var summary = document.createElement("dl");
          [
            [t("sourceDerivedRelpath"), proposal.source_relpath],
            [t("sourceDerivedBehavior"), proposal.behavior_intent],
            [
              t("sourceDerivedInputMin") + "–" + t("sourceDerivedInputMax"),
              proposal.input
                ? String(proposal.input.min_length) + "–" +
                  String(proposal.input.max_length)
                : "",
            ],
            [
              t("sourceDerivedEnum"),
              Array.isArray(proposal.result_enum)
                ? proposal.result_enum.join("、")
                : "",
            ],
            [
              t("sourceDerivedCases"),
              Array.isArray(proposal.acceptance_cases)
                ? proposal.acceptance_cases.map(function (item) {
                    return String(item.input_text || "") + " → " +
                      String(item.expected_result || "");
                  }).join("；")
                : "",
            ],
          ].forEach(function (item) {
            var term = document.createElement("dt");
            term.textContent = String(item[0] || "");
            var description = document.createElement("dd");
            description.textContent = String(item[1] || "");
            summary.appendChild(term);
            summary.appendChild(description);
          });
          row.appendChild(summary);
          var notice = document.createElement("p");
          notice.className = "warehouse-meta";
          notice.textContent = t("sourceDerivedAgentModelNotice");
          row.appendChild(notice);
          ["approve", "reject"].forEach(function (decision) {
            var decide = document.createElement("button");
            decide.type = "button";
            decide.className = decision === "approve"
              ? "btn-primary"
              : "btn-ghost";
            decide.dataset.action = "decide-source-derived-agent-" + decision;
            decide.textContent = t(
              decision === "approve"
                ? "sourceDerivedAgentApprove"
                : "sourceDerivedAgentReject"
            );
            decide.addEventListener("click", function () {
              bridgeCall(
                "decide_local_source_derived_handoff_proposal",
                JSON.stringify({
                  source_root_id: rootId,
                  decision: decision,
                })
              ).then(function (raw) {
                var result = parseBridgeJson(raw);
                if (!managementPayload(result)) {
                  setManagementStatus(managementError(result));
                  return;
                }
                refreshIngestionManagement();
              });
            });
            row.appendChild(decide);
          });
        }

        if (projection.status === "none" || projection.status === "revoked") {
          var authorizeAgent = document.createElement("button");
          authorizeAgent.type = "button";
          authorizeAgent.className = "btn-ghost";
          authorizeAgent.dataset.action = "authorize-source-derived-agent";
          authorizeAgent.textContent = t("sourceDerivedAgentAuthorize");
          authorizeAgent.addEventListener("click", function () {
            authorizeAgent.disabled = true;
            bridgeCall(
              "copy_local_source_derived_handoff_binding",
              JSON.stringify({ source_root_id: rootId })
            ).then(function (raw) {
              var result = parseBridgeJson(raw);
              if (!managementPayload(result)) {
                authorizeAgent.disabled = false;
                authorizeAgent.textContent = t("sourceDerivedAgentAuthorize");
                setManagementStatus(managementError(result));
                return;
              }
              authorizeAgent.textContent = t("sourceDerivedAgentCopiedClose");
              setManagementStatus("sourceDerivedAgentActive");
            });
          });
          row.appendChild(authorizeAgent);
        } else {
          var revokeAgent = document.createElement("button");
          revokeAgent.type = "button";
          revokeAgent.className = "btn-ghost";
          revokeAgent.dataset.action = "revoke-source-derived-agent";
          revokeAgent.textContent = t("sourceDerivedAgentRevoke");
          revokeAgent.addEventListener("click", function () {
            if (!window.confirm(t("sourceDerivedAgentRevokeConfirm"))) return;
            revokeAgent.disabled = true;
            bridgeCall(
              "revoke_local_source_derived_handoff",
              JSON.stringify({ source_root_id: rootId })
            ).then(function (raw) {
              var result = parseBridgeJson(raw);
              if (!managementPayload(result)) {
                revokeAgent.disabled = false;
                setManagementStatus(managementError(result));
                return;
              }
              refreshIngestionManagement();
            });
          });
          row.appendChild(revokeAgent);
        }
        sourceDerivedAgent.appendChild(row);
      });
      container.appendChild(sourceDerivedAgent);

      var sourceDerived = document.createElement("fieldset");
      sourceDerived.className = "warehouse-project-config warehouse-developer-only";
      var sourceDerivedLegend = document.createElement("legend");
      sourceDerivedLegend.textContent = t("sourceDerivedTitle");
      sourceDerived.appendChild(sourceDerivedLegend);
      var sourceDerivedNotice = document.createElement("p");
      sourceDerivedNotice.className = "warehouse-meta";
      sourceDerivedNotice.textContent = t("sourceDerivedNotice");
      sourceDerived.appendChild(sourceDerivedNotice);

      function sourceDerivedField(labelKey, element) {
        var label = document.createElement("label");
        label.className = "warehouse-field";
        label.textContent = t(labelKey);
        label.appendChild(element);
        sourceDerived.appendChild(label);
        return element;
      }

      var derivedRootSelect = sourceRootSelect();
      sourceDerivedField("javascriptSourceRoot", derivedRootSelect);
      var derivedRelpath = sourceDerivedField(
        "sourceDerivedRelpath",
        document.createElement("input")
      );
      derivedRelpath.type = "text";
      derivedRelpath.maxLength = 1024;
      derivedRelpath.placeholder = "src/utils/extractor.ts";
      var derivedBehavior = sourceDerivedField(
        "sourceDerivedBehavior",
        document.createElement("textarea")
      );
      derivedBehavior.maxLength = 2000;
      var derivedInputField = sourceDerivedField(
        "sourceDerivedInputField",
        document.createElement("input")
      );
      derivedInputField.type = "text";
      derivedInputField.maxLength = 64;
      derivedInputField.value = "message";
      var derivedMinimum = sourceDerivedField(
        "sourceDerivedInputMin",
        document.createElement("input")
      );
      derivedMinimum.type = "number";
      derivedMinimum.min = "0";
      derivedMinimum.max = "10000";
      derivedMinimum.value = "1";
      var derivedMaximum = sourceDerivedField(
        "sourceDerivedInputMax",
        document.createElement("input")
      );
      derivedMaximum.type = "number";
      derivedMaximum.min = "0";
      derivedMaximum.max = "10000";
      derivedMaximum.value = "1000";
      var derivedResultField = sourceDerivedField(
        "sourceDerivedResultField",
        document.createElement("input")
      );
      derivedResultField.type = "text";
      derivedResultField.maxLength = 64;
      derivedResultField.value = "result";
      var derivedEnum = sourceDerivedField(
        "sourceDerivedEnum",
        document.createElement("textarea")
      );
      var caseHeading = document.createElement("p");
      caseHeading.className = "warehouse-meta";
      caseHeading.textContent = t("sourceDerivedCases");
      sourceDerived.appendChild(caseHeading);
      var caseRows = document.createElement("div");
      sourceDerived.appendChild(caseRows);

      function addSourceDerivedCase() {
        if (caseRows.children.length >= 16) return;
        var row = document.createElement("div");
        row.className = "warehouse-row";
        var inputLabel = document.createElement("label");
        inputLabel.className = "warehouse-field";
        inputLabel.textContent = t("sourceDerivedCaseInput");
        var input = document.createElement("input");
        input.type = "text";
        input.maxLength = 10000;
        inputLabel.appendChild(input);
        row.appendChild(inputLabel);
        var expectedLabel = document.createElement("label");
        expectedLabel.className = "warehouse-field";
        expectedLabel.textContent = t("sourceDerivedCaseExpected");
        var expected = document.createElement("input");
        expected.type = "text";
        expected.maxLength = 10000;
        expectedLabel.appendChild(expected);
        row.appendChild(expectedLabel);
        var remove = document.createElement("button");
        remove.type = "button";
        remove.className = "btn-ghost";
        remove.textContent = t("sourceDerivedRemoveCase");
        remove.addEventListener("click", function () {
          if (caseRows.children.length > 1) row.remove();
        });
        row.appendChild(remove);
        caseRows.appendChild(row);
      }
      addSourceDerivedCase();
      var addCase = document.createElement("button");
      addCase.type = "button";
      addCase.className = "btn-ghost";
      addCase.textContent = t("sourceDerivedAddCase");
      addCase.addEventListener("click", addSourceDerivedCase);
      sourceDerived.appendChild(addCase);
      var startDerived = document.createElement("button");
      startDerived.type = "button";
      startDerived.className = "btn-primary";
      startDerived.dataset.action = "authorize-source-derived";
      startDerived.textContent = t("sourceDerivedStart");
      startDerived.addEventListener("click", function () {
        var selected = selectedSourceRoot();
        if (!selected) {
          setManagementStatus("sourceRootSelectionRequired");
          syncSourceRootControls();
          return;
        }
        var acceptanceCases = Array.prototype.slice.call(
          caseRows.children
        ).map(function (row) {
          var fields = row.querySelectorAll("input");
          return {
            input_text: String(fields[0] ? fields[0].value : ""),
            expected_result: String(fields[1] ? fields[1].value : ""),
          };
        });
        startDerived.disabled = true;
        startManagementRun(
          "authorize_and_start_source_derived_computation",
          {
            source_root_id: String(selected.root_id),
            source_relpath: String(derivedRelpath.value || "").trim(),
            behavior_intent: String(derivedBehavior.value || "").trim(),
            input_field: String(derivedInputField.value || "").trim(),
            input_min_length: Number(derivedMinimum.value),
            input_max_length: Number(derivedMaximum.value),
            result_field: String(derivedResultField.value || "").trim(),
            result_enum: String(derivedEnum.value || "")
              .split(/\r?\n/)
              .map(function (value) { return value.trim(); })
              .filter(Boolean),
            acceptance_cases: acceptanceCases,
          },
          function (run) {
            startDerived.disabled = false;
            if (run.status === "review_required") {
              setManagementStatus("sourceDerivedReviewReady");
            }
          },
          false,
          function () {
            startDerived.disabled = false;
          }
        );
      });
      sourceDerived.appendChild(startDerived);
      sourceRootActions.push(startDerived);
      container.appendChild(sourceDerived);
      syncSourceRootControls();
    }
    var discovery = ingestionManagement.discovery;
    var discovered = discovery && Array.isArray(discovery.projects) ? discovery.projects : [];
    if (discovered.length) {
      var form = document.createElement("div");
      form.className = "warehouse-discovery";
      discovered.forEach(function (project) {
        var projectConfig = document.createElement("div");
        projectConfig.className = "warehouse-project-config";
        var label = document.createElement("label");
        label.className = "warehouse-project-choice";
        var input = document.createElement("input");
        input.type = "checkbox";
        input.checked = project.selected === true ||
          (project.selected == null && discovered.length === 1);
        input.value = String(project.project_id || project.id || "");
        input.title = t("confirmProjects");
        label.appendChild(input);
        label.appendChild(document.createTextNode(" " + managementDisplayLabel(
          project.display_name || project.name || project.root_relpath,
          input.value,
          "sourceProjects"
        )));
        projectConfig.appendChild(label);
        var brandEditor = createBrandEditor(project);
        brandEditor.element.classList.add("warehouse-developer-only");
        input._brandEditor = brandEditor;
        projectConfig.appendChild(brandEditor.element);
        form.appendChild(projectConfig);
      });
      var confirm = document.createElement("button");
      confirm.type = "button";
      confirm.className = "btn-ghost";
      confirm.textContent = t("confirmProjects");
      confirm.title = t("confirmProjects");
      confirm.addEventListener("click", function () {
        var entries = [];
        var checked = Array.prototype.slice.call(form.querySelectorAll('input[type="checkbox"]:checked'));
        for (var index = 0; index < checked.length; index += 1) {
          var brand = checked[index]._brandEditor.read();
          if (!brand) return;
          entries.push(Object.assign({ project_id: checked[index].value }, brand));
        }
        submitProjectConfirmations(entries, function (errors) {
          if (!errors.length) ingestionManagement.discovery = null;
        });
      });
      form.appendChild(confirm);
      container.appendChild(form);
    }
    var scanHelp = document.createElement("p");
    scanHelp.id = "javascript-computation-scan-help";
    scanHelp.className = "warehouse-meta warehouse-project-scan-help";
    scanHelp.textContent = t("scanJavascriptComputationsHelp");
    if (ingestionManagement.projects.length) container.appendChild(scanHelp);
    ingestionManagement.projects.slice().sort(function (left, right) {
      function rank(project) {
        return project.source_type === "javascript_computation_source" && project.project_state === "ready" ? 0 : 1;
      }
      return rank(left) - rank(right) || String(left.display_name || left.project_id || "").localeCompare(String(right.display_name || right.project_id || ""));
    }).forEach(function (project) {
      var row = document.createElement("div");
      row.className = "warehouse-row";
      var projectStatus = project.project_state || project.status || "";
      var text = document.createElement("span");
      var sourceType = project.source_type === "javascript_computation_source"
        ? t("javascriptSourceType")
        : (project.source_type === "static_web" ? t("staticWebSourceType") : t("unknownSourceType"));
      var rawSourceRelpath = String(project.project_relpath || project.root_relpath || ".");
      var sourceRelpath = looksPrivateManagementValue(rawSourceRelpath) ? "" : rawSourceRelpath;
      var projectName = managementDisplayLabel(
        project.display_name || project.name || project.project_key || sourceRelpath,
        project.project_id,
        "sourceProjects"
      );
      text.textContent = projectName + " · " + sourceType;
      text.title = [projectName, sourceType, sourceRelpath, String(projectStatus)].filter(Boolean).join(" · ");
      row.appendChild(text);
      var inspect = document.createElement("button");
      inspect.type = "button";
      inspect.className = "btn-ghost warehouse-specimen-select";
      inspect.textContent = t("inspectSource");
      inspect.dataset.specimenProjectId = String(project.project_id || "");
      inspect.setAttribute("aria-pressed", "false");
      inspect.disabled = !project.project_id;
      inspect.addEventListener("click", function () {
        ingestionNavigation.specimen = {
          project_id: project.project_id || null,
          project_key: String(project.project_key || ""),
          display_name: projectName,
          exact_source: false,
          formal_capsule_count: 0,
          capsule_counts: null,
          capsule_id: null,
          capsule_name: null,
          capability_kind: null,
          version_id: null,
          canonical_hash: null,
        };
        syncIngestionSpecimen();
      });
      row.appendChild(inspect);
      var projectMeta = document.createElement("span");
      projectMeta.className = "warehouse-meta warehouse-developer-only";
      projectMeta.textContent = " · " + sourceRelpath + " · " + String(projectStatus);
      row.appendChild(projectMeta);
      var refresh = document.createElement("button");
      refresh.type = "button";
      refresh.className = "btn-ghost";
      refresh.setAttribute("data-action", "refresh-project");
      refresh.textContent = t("refreshProject");
      refresh.title = t("refreshProjectHelp");
      refresh.classList.add("warehouse-developer-only");
      refresh.disabled = !project.project_id || projectStatus !== "ready" || project.source_type === "javascript_computation_source";
      refresh.addEventListener("click", function () {
        startManagementRun("start_refresh_project", { project_id: project.project_id });
      });
      row.appendChild(refresh);
      var sourceHandoff = sourceHandoffStatusProjection(project.source_handoff);
      var sourceHandoffEligible =
        String(project.source_type || "") === "static_web" &&
        projectStatus === "ready";
      if (sourceHandoffEligible) {
        var sourceHandoffStatus = sourceHandoff
          ? String(sourceHandoff.status || "none")
          : "none";
        var sourceHandoffNote = document.createElement("span");
        sourceHandoffNote.className = "warehouse-meta warehouse-developer-only";
        sourceHandoffNote.setAttribute("role", "status");
        sourceHandoffNote.textContent = t(
          sourceHandoffStatusKey(sourceHandoffStatus) ||
          "authorizeSourceAgentHelp"
        );
        row.appendChild(sourceHandoffNote);
        if (
          sourceHandoffStatus === "none" ||
          sourceHandoffStatus === "revoked"
        ) {
          var authorizeSourceAgent = document.createElement("button");
          authorizeSourceAgent.type = "button";
          authorizeSourceAgent.className = "btn-ghost warehouse-developer-only";
          authorizeSourceAgent.dataset.action = "authorize-source-agent";
          authorizeSourceAgent.textContent = t("authorizeSourceAgent");
          authorizeSourceAgent.title = t("authorizeSourceAgentHelp");
          authorizeSourceAgent.addEventListener("click", function () {
            authorizeSourceAgent.disabled = true;
            bridgeCall(
              "copy_local_source_handoff_binding",
              JSON.stringify({ project_id: project.project_id })
            ).then(function (raw) {
              var result = parseBridgeJson(raw);
              var payload = managementPayload(result);
              if (!payload) {
                var errorKey = managementError(result);
                if (errorKey === "source_handoff_clipboard_failed") {
                  updateProjectSourceHandoff(
                    project.project_id,
                    null,
                    "revoked"
                  );
                  renderManagementProjects();
                } else {
                  authorizeSourceAgent.disabled = false;
                }
                setManagementStatus(errorKey);
                return;
              }
              updateProjectSourceHandoff(
                project.project_id,
                payload,
                "active"
              );
              setManagementStatus("sourceAgentBindingCopied");
              renderManagementProjects();
            });
          });
          row.appendChild(authorizeSourceAgent);
        }
        if (
          ["active", "stale", "conflict"].indexOf(sourceHandoffStatus) >= 0
        ) {
          var revokeSourceAgent = document.createElement("button");
          revokeSourceAgent.type = "button";
          revokeSourceAgent.className = "btn-ghost warehouse-developer-only";
          revokeSourceAgent.dataset.action = "revoke-source-agent";
          revokeSourceAgent.textContent = t("revokeSourceAgent");
          revokeSourceAgent.addEventListener("click", function () {
            revokeSourceAgent.disabled = true;
            bridgeCall(
              "revoke_local_source_handoff",
              JSON.stringify({ project_id: project.project_id })
            ).then(function (raw) {
              var result = parseBridgeJson(raw);
              var payload = managementPayload(result);
              if (!payload) {
                revokeSourceAgent.disabled = false;
                setManagementStatus(managementError(result));
                return;
              }
              updateProjectSourceHandoff(
                project.project_id,
                payload,
                "revoked"
              );
              setManagementStatus("sourceAgentRevoked");
              renderManagementProjects();
            });
          });
          row.appendChild(revokeSourceAgent);
        }
        if (
          sourceHandoff &&
          sourceHandoff.run_id &&
          [
            "completed",
            "completed_with_pending",
            "no_change",
            "failed",
            "cancelled",
            "interrupted",
          ].indexOf(sourceHandoff.run_status) >= 0
        ) {
          var reviewSourceAgent = document.createElement("button");
          reviewSourceAgent.type = "button";
          reviewSourceAgent.className = "btn-ghost warehouse-developer-only";
          reviewSourceAgent.dataset.action = "review-source-agent";
          reviewSourceAgent.textContent = t("reviewSourceAgent");
          reviewSourceAgent.addEventListener("click", function () {
            ingestionNavigation.productReview = null;
            ingestionNavigation.sourceHandoffReview = {
              project_id: String(project.project_id || ""),
              run_id: String(sourceHandoff.run_id || ""),
            };
            ingestionNavigation.station = "review";
            renderManagementReviews();
            syncIngestionStation();
          });
          row.appendChild(reviewSourceAgent);
        }
      }
      var scanJavascript = document.createElement("button");
      scanJavascript.type = "button";
      scanJavascript.className = "btn-ghost";
      scanJavascript.setAttribute("data-action", "scan-javascript-computations");
      scanJavascript.textContent = t("scanJavascriptComputations");
      scanJavascript.title = t("scanJavascriptComputationsHelp");
      var scanEligibility = computationScanEligibility(project);
      scanJavascript.disabled = !scanEligibility.enabled;
      var scanStatus = document.createElement("span");
      scanStatus.id = "project-scan-status-" + String(project.project_id || "unknown").replace(/[^a-zA-Z0-9_-]/g, "");
      scanStatus.className = "warehouse-meta warehouse-project-scan-status";
      var existingInspection = ingestionManagement.adapterOffers[String(project.project_id || "")];
      if (!scanEligibility.enabled) {
        scanStatus.textContent = t(scanEligibility.messageKey);
      } else if (existingInspection && existingInspection.schema === "computation_capture_offers.v2") {
        var existingOffers = Array.isArray(existingInspection.offers) ? existingInspection.offers : [];
        scanStatus.textContent = existingOffers.length
          ? formatText("scanJavascriptFound", { count: existingOffers.length })
          : t("noJavascriptComputations");
      } else {
        scanStatus.textContent = t(scanEligibility.messageKey);
      }
      scanJavascript.setAttribute("aria-describedby", scanHelp.id + " " + scanStatus.id);
      scanJavascript.addEventListener("click", function () {
        scanStatus.textContent = t("scanJavascriptRunning");
        startManagementRun(
          "start_scan_javascript_computations",
          { project_id: project.project_id },
          function (run) {
            var inspection = run && run.data;
            if (!inspection || inspection.schema !== "computation_capture_offers.v2") {
              scanStatus.textContent = t("managementOperationFailed");
              return;
            }
            ingestionManagement.adapterOffers[String(project.project_id)] = inspection;
            setManagementStatus("adapterInspectionComplete");
            renderManagementProjects();
            renderManagementReviews();
          },
          false,
          function (errorKey) {
            scanStatus.textContent = t(errorKey || "managementOperationFailed");
          }
        );
      });
      row.appendChild(scanJavascript);
      row.appendChild(scanStatus);
      var projectBlock = document.createElement("div");
      projectBlock.className = "warehouse-project-config";
      projectBlock.appendChild(row);
      if (project.source_type !== "javascript_computation_source") {
        var existingBrand = createBrandEditor(project);
        existingBrand.element.classList.add("warehouse-developer-only");
        var saveBrand = document.createElement("button");
        saveBrand.type = "button";
        saveBrand.className = "btn-ghost";
        saveBrand.textContent = t("save");
        saveBrand.title = t("saveBrandHelp");
        saveBrand.addEventListener("click", function () {
          var brand = existingBrand.read();
          if (!brand) return;
          submitProjectConfirmations([
            Object.assign({ project_id: project.project_id }, brand),
          ]);
        });
        existingBrand.element.appendChild(saveBrand);
        projectBlock.appendChild(existingBrand.element);
      }
      renderJavascriptComputationOffers(
        projectBlock,
        project,
        ingestionManagement.adapterOffers[String(project.project_id)]
      );
      container.appendChild(projectBlock);
    });
    if (!discovered.length && !ingestionManagement.projects.length) emptyManagementList(container, "noItems");
  }

  function renderManagementModels() {
    var select = $("supervision-model-select");
    if (!select) return;
    select.innerHTML = "";
    var empty = document.createElement("option");
    empty.value = "";
    empty.textContent = t("selectModel");
    select.appendChild(empty);
    ingestionManagement.models.forEach(function (model, index) {
      var option = document.createElement("option");
      option.value = String(index);
      option.textContent = String(model.name || "") + (model.digest ? " · " + String(model.digest).slice(0, 12) : "");
      if (
        ingestionManagement.selectedModel &&
        model.name === ingestionManagement.selectedModel.name &&
        model.digest === ingestionManagement.selectedModel.digest
      ) option.selected = true;
      select.appendChild(option);
    });
  }

  function managementReviewDecisionPayload(reviewId, decision, controls) {
    var payload = { review_id: reviewId, decision: decision };
    var identityDecisions = ["publish_general", "publish_brand_limited", "create_variant", "semantic_split"];
    var names = identityDecisions.indexOf(decision) >= 0
      ? ["capability_key", "role_key", "variant_key", "display_name"]
      : [];
    if (decision === "merge_existing") names.push("retained_version_id");
    if (decision === "replace_current" || decision === "semantic_split") names.push("target_capsule_id");
    for (var i = 0; i < names.length; i += 1) {
      var control = controls[names[i]];
      var value = control ? String(control.value || "").trim() : "";
      if (!value || (typeof control.checkValidity === "function" && !control.checkValidity())) {
        if (control && typeof control.reportValidity === "function") control.reportValidity();
        return null;
      }
      payload[names[i]] = value;
    }
    return payload;
  }

  function productReviewBinding(item, candidate) {
    var context = ingestionNavigation.productReview;
    var receipt = candidate && candidate.frozen_review_admission;
    if (
      !context ||
      String(item.review_id || "") !== context.review_id ||
      !receipt ||
      receipt.schema !== "frozen_stage3_review_admission.v2" ||
      String(receipt.projection_digest || "") !==
        context.projection_digest
    ) {
      return null;
    }
    var capabilityKey = String(
      receipt.authorized_capability_key || ""
    );
    var group = ingestionManagement.capabilityGroups.find(function (item) {
      return String(item.capability_key || "") === capabilityKey;
    });
    if (!capabilityKey || !group) return null;
    return {
      capability_key: capabilityKey,
      role_key: "",
      variant_key: "default",
      display_name: String(group.display_name || ""),
    };
  }

  function renderManagementReviews() {
    var container = $("warehouse-review-items");
    var count = $("warehouse-review-count");
    if (!container || !count) return;
    var productContext = ingestionNavigation.productReview;
    var sourceHandoffContext = ingestionNavigation.sourceHandoffReview;
    var reviewItems = ingestionManagement.reviewItems;
    if (productContext) {
      reviewItems = reviewItems.filter(function (item) {
        return String(item.review_id || "") === productContext.review_id;
      });
    } else if (sourceHandoffContext) {
      reviewItems = reviewItems.filter(function (item) {
        return (
          String(item.project_id || "") ===
            sourceHandoffContext.project_id &&
          String(item.run_id || "") === sourceHandoffContext.run_id
        );
      });
    }
    count.textContent = String(reviewItems.length);
    container.innerHTML = "";
    if (!reviewItems.length) {
      if (productContext) {
        var missing = document.createElement("p");
        missing.className = "warehouse-status is-error";
        missing.setAttribute("role", "status");
        missing.dataset.errorCode = "target_review_missing";
        missing.textContent = "target_review_missing";
        container.appendChild(missing);
      } else if (sourceHandoffContext) {
        var sourceMissing = document.createElement("p");
        sourceMissing.className = "warehouse-status is-error";
        sourceMissing.setAttribute("role", "status");
        sourceMissing.dataset.errorCode = "source_handoff_review_missing";
        sourceMissing.textContent = t("sourceAgentReviewMissing");
        container.appendChild(sourceMissing);
      } else {
        emptyManagementList(container, "noReviews");
      }
      return;
    }
    reviewItems.forEach(function (item) {
      var candidate = item.candidate && typeof item.candidate === "object" ? item.candidate : {};
      var productIdentity = productReviewBinding(item, candidate);
      var adapterContractExpired = item.adapter_contract_version_expired === true;
      var reviewContext = ingestionManagement.captureReviewContext[String(item.review_id || "")] || {};
      var details = document.createElement("details");
      details.className = "warehouse-review";
      details.title = t("reviewItems");
      var summary = document.createElement("summary");
      if (productContext) {
        summary.id = "target-review-summary-" + String(item.review_id || "");
      } else if (sourceHandoffContext) {
        summary.dataset.sourceHandoffReview = "true";
      }
      var reviewName = reviewContext.offer_name || item.display_name || item.suggested_name || candidate.suggested_display_name || t("captureReview");
      var hasServerDecisions = Array.isArray(item.allowed_decisions) && item.allowed_decisions.length > 0;
      var reviewState = adapterContractExpired
        ? t("adapterContractVersionExpired")
        : (item.candidate_status === "waiting_user" &&
          item.resume_contract === "resubmit_ephemeral_capture.v1" && !hasServerDecisions
          ? t("captureResubmitRequired")
          : reviewStatusLabel(item.candidate_status || item.status));
      summary.appendChild(document.createTextNode(String(reviewName) + " · " + reviewState));
      var reviewId = document.createElement("span");
      reviewId.className = "warehouse-developer-only warehouse-meta";
      reviewId.textContent = " · " + String(item.review_id || "");
      summary.appendChild(reviewId);
      details.appendChild(summary);
      details.open = !!productContext || !!sourceHandoffContext;
      var meta = document.createElement("p");
      meta.className = "warehouse-meta warehouse-developer-only";
      meta.textContent = [item.capability_kind || candidate.capability_kind, item.reason_code || item.error_code].filter(Boolean).join(" · ");
      details.appendChild(meta);
      if (adapterContractExpired) {
        var expiredStatus = document.createElement("p");
        expiredStatus.className = "warehouse-status is-error";
        expiredStatus.textContent = t("adapterContractVersionExpired");
        details.appendChild(expiredStatus);
      }
      var captureSummary = item.capture_summary && typeof item.capture_summary === "object" ? item.capture_summary : null;
      if (captureSummary) {
        var safeSummary = document.createElement("p");
        safeSummary.className = "warehouse-meta";
        safeSummary.textContent = formatText("captureSafetySummary", {
          ambiguous: Number(captureSummary.ambiguous_count || 0),
          brand: Number(captureSummary.brand_count || 0),
          enums: Number(captureSummary.enumeration_parameter_count || 0),
        });
        safeSummary.title = safeSummary.textContent;
        details.appendChild(safeSummary);
      }
      var decisions = adapterContractExpired ? [] :
        (Array.isArray(item.allowed_decisions) ? item.allowed_decisions :
          (Array.isArray(item.decisions) ? item.decisions : []));
      if (productContext) {
        decisions = productIdentity
          ? decisions.filter(function (decision) {
              return decision === "publish_general" || decision === "reject";
            })
          : [];
      }
      if (!adapterContractExpired && !decisions.length && item.candidate_status === "waiting_user") {
        var codes = item.redaction && Array.isArray(item.redaction.codes) ? item.redaction.codes : [];
        var stage3Code = candidate.stage3_failure && candidate.stage3_failure.error_code;
        if (
          item.sensitivity_decision == null &&
          (codes.indexOf("sensitivity_confirmation_required") >= 0 || stage3Code === "sensitivity_confirmation_required_stage3")
        ) {
          decisions = decisions.concat([
            "confirm_fictional_fixture",
            "confirm_safe_redaction",
            "confirm_real_record_reject",
          ]);
        }
        if (item.brand_decision == null && codes.indexOf("brand_confirmation_required") >= 0) {
          decisions = decisions.concat(["remove_brand", "retain_brand_limited"]);
        }
        if (item.asset_decision == null && stage3Code === "asset_content_confirmation_required_stage3") {
          decisions.push("confirm_assets_contain_no_real_records");
        }
      }
      var controls = {};
      var identityDecisions = ["publish_general", "publish_brand_limited", "create_variant", "semantic_split"];
      if (decisions.some(function (decision) { return identityDecisions.indexOf(decision) >= 0; })) {
        var identityDefaults =
          productIdentity ||
          reviewIdentityDefaults(item, candidate, reviewName);
        var identityFields = document.createElement("div");
        identityFields.className = "warehouse-actions";
        ["capability_key", "role_key", "variant_key", "display_name"].forEach(function (name) {
          var labelKey = {
            capability_key: "capabilityKeyLabel",
            role_key: "roleKeyLabel",
            variant_key: "variantKeyLabel",
            display_name: "displayNameLabel",
          }[name];
          var helpKey = {
            capability_key: "capabilityKeyHelp",
            role_key: "roleKeyHelp",
            variant_key: "variantKeyHelp",
            display_name: "displayNameHelp",
          }[name];
          var label = document.createElement("label");
          label.className = "warehouse-field" + (name === "variant_key" ? " warehouse-developer-only" : "");
          label.textContent = t(labelKey);
          label.title = t(helpKey);
          var input = controlHelp(document.createElement("input"), helpKey);
          input.type = "text";
          input.name = name;
          input.required = true;
          input.autocomplete = "off";
          input.spellcheck = false;
          if (name !== "display_name") input.pattern = "[a-z_][a-z0-9_]*";
          input.value = String(identityDefaults[name] || "");
          if (
            productIdentity &&
            (name === "capability_key" || name === "display_name")
          ) {
            input.readOnly = true;
            input.setAttribute("aria-readonly", "true");
          }
          if (name === "display_name") input.maxLength = 200;
          controls[name] = input;
          label.appendChild(input);
          identityFields.appendChild(label);
        });
        details.appendChild(identityFields);
      }
      var comparison = item.comparison && typeof item.comparison === "object" ? item.comparison : {};
      var comparisonCandidates = Array.isArray(comparison.candidates) ? comparison.candidates : [];
      [
        { name: "retained_version_id", enabled: decisions.indexOf("merge_existing") >= 0, value: "version_id" },
        {
          name: "target_capsule_id",
          enabled: decisions.indexOf("replace_current") >= 0 || decisions.indexOf("semantic_split") >= 0,
          value: "capsule_id",
        },
      ].forEach(function (definition) {
        if (!definition.enabled) return;
        var labelKey = definition.name === "retained_version_id" ? "retainedVersionLabel" : "targetCapsuleLabel";
        var helpKey = definition.name === "retained_version_id" ? "retainedVersionHelp" : "targetCapsuleHelp";
        var label = document.createElement("label");
        label.className = "warehouse-field";
        label.textContent = t(labelKey);
        label.title = t(helpKey);
        var select = controlHelp(document.createElement("select"), helpKey);
        select.name = definition.name;
        select.required = true;
        var empty = document.createElement("option");
        empty.value = "";
        empty.textContent = definition.name;
        select.appendChild(empty);
        var seen = {};
        comparisonCandidates.forEach(function (candidateOption) {
          var value = candidateOption && candidateOption[definition.value];
          if (!value || seen[value]) return;
          seen[value] = true;
          var option = document.createElement("option");
          option.value = String(value);
          option.textContent = [
            candidateOption.capability_key,
            candidateOption.role_key,
            candidateOption.variant_key,
            candidateOption.version_id,
          ].filter(Boolean).join(" · ") || String(value);
          select.appendChild(option);
        });
        controls[definition.name] = select;
        label.appendChild(select);
        details.appendChild(label);
      });
      var actions = document.createElement("div");
      actions.className = "warehouse-actions warehouse-review-decision";
      var decisionSelect = document.createElement("select");
      decisionSelect.setAttribute("aria-label", t("reviewItems"));
      var decisionEmpty = document.createElement("option");
      decisionEmpty.value = "";
      decisionEmpty.textContent = t("reviewItems");
      decisionSelect.appendChild(decisionEmpty);
      decisions.forEach(function (decision) {
        var copy = reviewDecisionCopy(decision);
        var option = document.createElement("option");
        option.value = String(decision);
        option.textContent = copy ? t(copy[0]) : String(decision);
        decisionSelect.appendChild(option);
      });
      var submitDecision = document.createElement("button");
      submitDecision.type = "button";
      submitDecision.className = "btn-primary";
      submitDecision.textContent = t("save");
      submitDecision.disabled = true;
      decisionSelect.addEventListener("change", function () {
        submitDecision.disabled = !decisionSelect.value;
        submitDecision.dataset.decision = decisionSelect.value;
      });
      submitDecision.addEventListener("click", function () {
        var decision = String(decisionSelect.value || "");
        if (!decision) return;
        var decisionPayload = managementReviewDecisionPayload(item.review_id, decision, controls);
        if (!decisionPayload) return;
        bridgeCall("decide_review_item", JSON.stringify(decisionPayload)).then(function (raw) {
            var result = parseBridgeJson(raw);
            var decided = managementPayload(result);
            if (!decided) {
              setManagementStatus(managementError(result));
              return;
            }
            if (
              decided.capture_resubmission_required === true &&
              decided.resume_contract === "resubmit_ephemeral_capture.v1"
            ) {
              refreshAdapterReviewItems(function (items) {
                var current = items.find(function (candidateItem) {
                  return String(candidateItem.review_id || "") === String(item.review_id || "");
                });
                var decisionsRemaining = current && Array.isArray(current.allowed_decisions)
                  ? current.allowed_decisions.length > 0
                  : false;
                var nextStatus = decisionsRemaining ? "captureNeedsDecision" : "captureResubmitRequired";
                Array.prototype.forEach.call(
                  document.querySelectorAll("[data-resume-review-id]"),
                  function (captureButton) {
                    if (String(captureButton.dataset.resumeReviewId || "") !== String(item.review_id || "")) return;
                    captureButton.disabled = decisionsRemaining;
                    captureButton.textContent = t("continueCaptureValidation");
                    var card = captureButton.closest(".warehouse-review");
                    var cardStatus = card && card.querySelector(".warehouse-status");
                    if (cardStatus) {
                      cardStatus.textContent = t(nextStatus);
                      cardStatus.classList.add("is-waiting");
                      cardStatus.classList.remove("is-error");
                    }
                  }
                );
                setManagementStatus(nextStatus);
              });
              return;
            }
            if (productContext) {
              closeIngestionScene();
              return;
            }
            if (!trackManagementRuns(result, function () {
              setManagementStatus("decisionSaved");
            })) {
              setManagementStatus("decisionSaved");
              refreshIngestionManagement();
            }
        });
      });
      actions.appendChild(decisionSelect);
      actions.appendChild(submitDecision);
      details.appendChild(actions);
      if (productContext && !productIdentity) {
        var invalid = document.createElement("p");
        invalid.className = "warehouse-status is-error";
        invalid.dataset.errorCode = "target_review_binding_invalid";
        invalid.textContent = "target_review_binding_invalid";
        details.appendChild(invalid);
      }
      container.appendChild(details);
    });
    if (productContext) {
      window.setTimeout(function () {
        var summary = $(
          "target-review-summary-" + productContext.review_id
        );
        if (summary) summary.focus({ preventScroll: true });
      }, 0);
    } else if (sourceHandoffContext) {
      window.setTimeout(function () {
        var summary = container.querySelector(
          "[data-source-handoff-review]"
        );
        if (summary) summary.focus({ preventScroll: true });
      }, 0);
    }
  }

  function managementJson(value) {
    if (value && typeof value === "object" && !Array.isArray(value)) return value;
    if (typeof value !== "string" || !value.trim()) return {};
    try {
      var parsed = JSON.parse(value);
      return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : {};
    } catch (_error) {
      return {};
    }
  }

  function managementFields(contract) {
    var properties = managementJson(contract).properties;
    return properties && typeof properties === "object" && !Array.isArray(properties)
      ? Object.keys(properties).sort()
      : [];
  }

  function managementContractSummary(kind, version) {
    var activation = managementJson(version.activation_json || version.activation);
    var input = managementJson(version.input_contract_json || version.input_contract);
    var output = managementJson(version.output_contract_json || version.output_contract);
    var parts = [t("contractEntrypoint") + ": " + String(activation.entrypoint || "—")];
    if (kind === "interaction") {
      var events = managementJson(output.events);
      var names = Object.keys(events).sort().map(function (name) {
        return name + "(" + managementFields(events[name]).join(", ") + ")";
      });
      parts.push(t("contractProduces") + ": " + (names.length ? names.join(" · ") : t("contractNoOutput")));
      return parts.join(" · ");
    }
    var inputs = managementFields(input);
    var outputs = managementFields(output);
    parts.push(t("contractReceives") + ": " + (inputs.length ? inputs.join(", ") : t("contractNoInput")));
    parts.push(t("contractProduces") + ": " + (outputs.length ? outputs.join(", ") : t("contractNoOutput")));
    return parts.join(" · ");
  }

  function renderFormalCapsuleDetail(panel, capsule, detail) {
    panel.replaceChildren();
    var detailCapsule = detail.capsule || detail;
    var versions = Array.isArray(detail.versions) ? detail.versions : [];
    var currentVersionId = String(detailCapsule.current_version_id || capsule.version_id || "");
    var version = versions.find(function (item) {
      return String(item.version_id || "") === currentVersionId;
    }) || versions[0] || {};
    var identity = document.createElement("p");
    identity.className = "ingestion-formal-identity";
    identity.textContent = [
      String(detailCapsule.capability_kind || capsule.capability_kind || ""),
      version.version_number != null ? "v" + String(version.version_number) : "",
      String(version.version_id || currentVersionId || ""),
      String(detailCapsule.status || capsule.status || ""),
    ].filter(Boolean).join(" · ");
    panel.appendChild(identity);
    var contract = document.createElement("p");
    contract.className = "ingestion-formal-contract";
    contract.textContent = managementContractSummary(
      String(detailCapsule.capability_kind || capsule.capability_kind || ""),
      version
    );
    panel.appendChild(contract);
    panel.dataset.loaded = "true";
  }

  function renderManagementGroups() {
    var container = $("warehouse-capability-groups");
    if (!container) return;
    container.innerHTML = "";
    if (!ingestionManagement.capabilityGroups.length) {
      emptyManagementList(container, "noCapabilities");
      return;
    }
    ingestionManagement.capabilityGroups.forEach(function (group) {
      var details = document.createElement("details");
      details.className = "warehouse-capability";
      details.title = t("capabilityGroups");
      var summary = document.createElement("summary");
      summary.textContent = String(group.display_name || group.capability_key || "capability");
      details.appendChild(summary);
      var rename = document.createElement("button");
      rename.type = "button";
      rename.className = "btn-ghost";
      rename.textContent = t("renameCapability");
      rename.title = t("renameCapabilityHelp");
      rename.addEventListener("click", function () {
        var next = window.prompt(
          t("renameCapabilityPrompt"),
          String(group.display_name || group.capability_key || "")
        );
        if (next === null) return;
        bridgeCall(
          "rename_capability_group",
          JSON.stringify({ capability_key: group.capability_key, display_name: next })
        ).then(function (raw) {
          var result = parseBridgeJson(raw);
          var renamed = managementPayload(result);
          if (!renamed) {
            setManagementStatus(managementError(result));
            return;
          }
          group.display_name = renamed.display_name;
          summary.textContent = renamed.display_name;
          refreshIngestionManagement();
        });
      });
      details.appendChild(rename);
      var capsules = Array.isArray(group.capsules) ? group.capsules : (Array.isArray(group.roles) ? group.roles : []);
      capsules.forEach(function (capsule) {
        var unit = document.createElement("article");
        unit.className = "ingestion-formal-capsule";
        unit.dataset.capsuleId = String(capsule.capsule_id || "");
        var panelId = "ingestion-formal-detail-" + String(capsule.capsule_id || "").replace(/[^a-zA-Z0-9_-]/g, "_");
        var seal = document.createElement("button");
        seal.type = "button";
        seal.className = "warehouse-capsule-seal is-management";
        seal.setAttribute("aria-expanded", "false");
        seal.setAttribute("aria-controls", panelId);
        var kind = String(capsule.capability_kind || "");
        var kindSide = document.createElement("span");
        kindSide.className = "warehouse-capsule-kind";
        var mark = document.createElement("i");
        mark.className = "warehouse-capsule-core is-" + kind;
        mark.setAttribute("aria-hidden", "true");
        kindSide.appendChild(mark);
        var kindText = document.createElement("span");
        kindText.textContent = t({
          presentation: "presentationCapability",
          interaction: "interactionCapability",
          computation: "computationCapability",
        }[kind] || kind);
        kindSide.appendChild(kindText);
        seal.appendChild(kindSide);
        var capsuleIdentity = document.createElement("span");
        capsuleIdentity.className = "warehouse-capsule-identity";
        var capsuleName = document.createElement("strong");
        capsuleName.textContent = String(group.display_name || group.capability_key || "capability");
        capsuleIdentity.appendChild(capsuleName);
        var capsuleMeta = document.createElement("p");
        capsuleMeta.textContent = [
          capsule.role_key,
          capsule.variant_key,
          capsule.status,
          t("exactVersion") + " —",
        ].filter(Boolean).join(" · ");
        capsuleIdentity.appendChild(capsuleMeta);
        seal.appendChild(capsuleIdentity);
        unit.appendChild(seal);
        var panel = document.createElement("section");
        panel.id = panelId;
        panel.className = "ingestion-formal-detail";
        panel.hidden = true;
        unit.appendChild(panel);
        seal.addEventListener("click", function () {
          var open = seal.getAttribute("aria-expanded") === "true";
          container.querySelectorAll(".warehouse-capsule-seal.is-management").forEach(function (item) {
            item.setAttribute("aria-expanded", "false");
          });
          container.querySelectorAll(".ingestion-formal-detail").forEach(function (item) {
            item.hidden = true;
          });
          if (open) return;
          seal.setAttribute("aria-expanded", "true");
          panel.hidden = false;
          if (panel.dataset.loaded === "true") return;
          panel.textContent = t("warehouseLoadingRelations");
          bridgeCall("get_capsule_detail", JSON.stringify({ capsule_id: capsule.capsule_id })).then(function (raw) {
            var result = parseBridgeJson(raw);
            var detail = managementPayload(result);
            if (!detail) {
              panel.textContent = t("contractUnavailable");
              setManagementStatus(managementError(result));
              return;
            }
            renderFormalCapsuleDetail(panel, capsule, detail);
            var detailCapsule = detail.capsule || detail;
            var versions = Array.isArray(detail.versions) ? detail.versions : [];
            var latestVersion = versions.find(function (item) {
              return String(item.version_id || "") === String(detailCapsule.current_version_id || "");
            }) || versions[0] || {};
            capsuleMeta.textContent = [
              capsule.role_key,
              capsule.variant_key,
              latestVersion.version_number != null ? "v" + latestVersion.version_number : "",
              latestVersion.version_id ? String(latestVersion.version_id).slice(0, 15) + "…" : "",
              detailCapsule.status || capsule.status,
            ].filter(Boolean).join(" · ");
          });
        });
        var actions = document.createElement("div");
        actions.className = "ingestion-formal-actions";
        if (capsule.capsule_id) {
          var statusButton = document.createElement("button");
          statusButton.type = "button";
          statusButton.className = "btn-ghost";
          statusButton.textContent = capsule.status === "active" ? t("disableCapsule") : t("enableCapsule");
          statusButton.title = capsule.status === "active" ? t("disableCapsuleHelp") : t("enableCapsuleHelp");
          statusButton.addEventListener("click", function () {
            var status = capsule.status === "active" ? "disabled" : "active";
            bridgeCall("set_capsule_status", JSON.stringify({ capsule_id: capsule.capsule_id, status: status })).then(function (raw) {
              var result = parseBridgeJson(raw);
              if (!managementPayload(result)) setManagementStatus(managementError(result));
              else refreshIngestionManagement();
            });
          });
          actions.appendChild(statusButton);
        }
        unit.appendChild(actions);
        details.appendChild(unit);
      });
      container.appendChild(details);
    });
  }

  function renderManagementLegacy() {
    var container = $("warehouse-legacy");
    var importButton = $("btn-warehouse-import");
    if (!container) return;
    container.innerHTML = "";
    var legacy = ingestionManagement.legacy;
    if (importButton) importButton.disabled = !(legacy && legacy.present);
    if (!legacy || !legacy.present) {
      emptyManagementList(container, "legacyNotFound");
      return;
    }
    var summary = document.createElement("p");
    summary.className = "warehouse-meta";
    summary.textContent = [
      t("legacyWarehouse"),
      legacy.status,
      String(legacy.recognizableEntries || 0),
    ].filter(Boolean).join(" · ");
    container.appendChild(summary);
    var aliases = Array.isArray(legacy.aliases) ? legacy.aliases : [];
    if (!aliases.length) return;
    aliases.forEach(function (alias) {
      var row = document.createElement("div");
      row.className = "warehouse-legacy-alias";
      var label = document.createElement("span");
      label.textContent = [
        alias.legacy_capsule_id,
        alias.relationship === "pending" ? t("legacyPending") : alias.relationship,
        alias.reason_code,
      ].filter(Boolean).join(" · ");
      row.appendChild(label);
      var targets = Array.isArray(alias.eligible_targets) ? alias.eligible_targets : [];
      if (alias.relationship === "pending" && targets.length) {
        var controls = document.createElement("div");
        controls.className = "warehouse-actions";
        var relationship = document.createElement("select");
        relationship.setAttribute("aria-label", t("legacyRelationship"));
        relationship.title = t("legacyRelationship");
        ["cleaned_successor", "merged", "variant"].forEach(function (value) {
          var option = document.createElement("option");
          option.value = value;
          option.textContent = value;
          relationship.appendChild(option);
        });
        var target = document.createElement("select");
        target.setAttribute("aria-label", t("legacyTarget"));
        target.title = t("legacyTarget");
        targets.forEach(function (value, index) {
          var option = document.createElement("option");
          option.value = String(index);
          option.textContent = [
            value.display_name || value.capability_key,
            value.role_key,
            value.variant_key,
          ].filter(Boolean).join(" · ");
          target.appendChild(option);
        });
        var map = document.createElement("button");
        map.type = "button";
        map.className = "btn-ghost";
        map.textContent = t("mapLegacy");
        map.title = t("mapLegacyHelp");
        map.addEventListener("click", function () {
          var selected = targets[Number(target.value)];
          if (!selected) return;
          startManagementRun("start_legacy_import", {
            links: [
              {
                legacy_capsule_id: alias.legacy_capsule_id,
                relationship: relationship.value,
                capsule_id: selected.capsule_id,
                version_id: selected.version_id,
              },
            ],
          });
        });
        controls.appendChild(relationship);
        controls.appendChild(target);
        controls.appendChild(map);
        row.appendChild(controls);
      }
      container.appendChild(row);
    });
  }

  function renderManagementBackups() {
    var container = $("warehouse-backups");
    if (!container) return;
    container.innerHTML = "";
    if (
      !ingestionManagement.backups.length &&
      !ingestionManagement.recoverableProducts.length &&
      !ingestionManagement.historicalProducts.length
    ) {
      emptyManagementList(container, "noBackups");
      return;
    }
    ingestionManagement.backups.forEach(function (backup) {
      var row = document.createElement("div");
      row.className = "warehouse-row";
      var label = document.createElement("span");
      label.textContent = [backup.created_at, backup.kind, backup.sha256 ? String(backup.sha256).slice(0, 12) : ""].filter(Boolean).join(" · ");
      row.appendChild(label);
      var restore = document.createElement("button");
      restore.type = "button";
      restore.className = "btn-ghost";
      restore.textContent = t("restore");
      restore.title = t("restoreHelp");
      restore.disabled = backup.valid === false || !backup.path || !backup.sha256;
      restore.addEventListener("click", function () {
        inspectAndRestoreBackup(backup);
      });
      row.appendChild(restore);
      container.appendChild(row);
    });
    ingestionManagement.recoverableProducts.forEach(function (product) {
      var row = document.createElement("div");
      row.className = "warehouse-row";
      var label = document.createElement("span");
      label.textContent = String(product.product_id) + " · " + String(product.status);
      row.appendChild(label);
      var retry = document.createElement("button");
      retry.type = "button";
      retry.className = "btn-ghost";
      retry.textContent = t("retryUsage");
      retry.title = t("retryUsageHelp");
      retry.addEventListener("click", function () {
        bridgeCall(
          "retry_product_usage_registration",
          JSON.stringify({ product_id: product.product_id })
        ).then(function (raw) {
          var result = parseBridgeJson(raw);
          if (!managementPayload(result)) setManagementStatus(managementError(result));
          else {
            setManagementStatus("usageRetryComplete");
            refreshIngestionManagement();
          }
        });
      });
      row.appendChild(retry);
      container.appendChild(row);
    });
    ingestionManagement.historicalProducts.forEach(function (product) {
      var details = document.createElement("details");
      details.className = "warehouse-capability";
      details.dataset.historicalProductId = String(product.product_id || "");
      var summary = document.createElement("summary");
      summary.textContent = String(product.product_id) + " · " + String(product.status);
      details.appendChild(summary);
      var digest = document.createElement("p");
      digest.className = "warehouse-meta";
      digest.textContent = t("manifestDigest") + ": " + String(product.manifest_digest || "");
      details.appendChild(digest);
      var backup = document.createElement("p");
      backup.className = "warehouse-meta";
      backup.textContent =
        t("preRestoreBackup") + ": " +
        (product.pre_restore_backup_path ? t("backupAvailable") : t("backupUnavailable"));
      details.appendChild(backup);
      container.appendChild(details);
    });
  }

  function renderManagementRuns() {
    var container = $("warehouse-runs");
    if (!container) return;
    container.innerHTML = "";
    var runIds = Object.keys(ingestionManagement.runs);
    if (!runIds.length) {
      emptyManagementList(container, "noRuns");
      return;
    }
    runIds.forEach(function (runId) {
      var run = ingestionManagement.runs[runId] || {};
      var row = document.createElement("div");
      row.className = "warehouse-row";
      var label = document.createElement("span");
      label.textContent = String(runId) + " · " + String(run.status || "queued");
      row.appendChild(label);
      if (run.status === "queued" || run.status === "running") {
        var cancel = document.createElement("button");
        cancel.type = "button";
        cancel.className = "btn-ghost";
        cancel.textContent = t("cancelRun");
        cancel.title = t("cancelRunHelp");
        cancel.addEventListener("click", function () {
          bridgeCall("cancel_intake_run", JSON.stringify({ run_id: runId }));
        });
        row.appendChild(cancel);
      }
      container.appendChild(row);
    });
  }

  function renderIngestionManagement() {
    if (!$("capsule-warehouse-popover")) return;
    syncWarehouseMode();
    renderManagementProjects();
    renderManagementModels();
    renderManagementReviews();
    renderManagementGroups();
    renderManagementLegacy();
    renderManagementBackups();
    renderManagementRuns();
    syncIngestionStation();
    setManagementStatus(ingestionManagement.errorKey);
  }

  function refreshIngestionManagement() {
    if (!hasDesktopBridge()) {
      setManagementStatus("managementUnavailable");
      return Promise.resolve();
    }
    if (ingestionManagement.loading) {
      ingestionManagement.refreshPending = true;
      return Promise.resolve();
    }
    ingestionManagement.loading = true;
    setManagementStatus("managementLoading");
    return Promise.all([
      bridgeCall("get_initial_state"),
      bridgeCall("list_supervision_models", JSON.stringify({})),
      bridgeCall("list_review_items", JSON.stringify({})),
      bridgeCall("list_capability_groups", JSON.stringify({})),
      bridgeCall("list_backups", JSON.stringify({})),
    ]).then(function (rawResults) {
      var results = rawResults.map(parseBridgeJson);
      if (results[0] && results[0].ok !== false) {
        desktopShellState = results[0];
        applyDesktopInitialState(desktopShellState);
      }
      ingestionManagement.reviewItems = managementList(results[2], ["review_items", "items"]);
      ingestionManagement.capabilityGroups = managementList(results[3], ["capability_groups", "groups", "items"]);
      ingestionManagement.backups = managementList(results[4], ["backups", "items"]);
      var modelPayload = managementPayload(results[1]);
      if (modelPayload && modelPayload.run_id) {
        trackManagementRuns(results[1], function (run) {
          ingestionManagement.models = managementList({ ok: true, data: run.data || {} }, ["models", "items"]);
          renderManagementModels();
        }, false);
      } else {
        ingestionManagement.models = managementList(results[1], ["models", "items"]);
      }
      ingestionManagement.loading = false;
      ingestionManagement.loaded = true;
      var failed = results.slice(2).find(function (result) {
        return !result || result.ok === false;
      });
      ingestionManagement.errorKey = failed
        ? managementError(failed)
        : (ingestionManagement.sourceRootSelectionStale
          ? "sourceRootSelectionStale"
          : "");
      renderIngestionManagement();
      if (ingestionManagement.refreshPending) {
        ingestionManagement.refreshPending = false;
        return refreshIngestionManagement();
      }
    });
  }

  function collectRunIds(result) {
    var payload = managementPayload(result);
    if (!payload) return [];
    var ids = [];
    if (payload.run_id) ids.push(String(payload.run_id));
    (payload.run_ids || []).forEach(function (id) {
      if (id) ids.push(String(id));
    });
    return ids;
  }

  function rememberManagementRun(runId, run) {
    delete ingestionManagement.runs[runId];
    ingestionManagement.runs[runId] = run;
    // ponytail: UI receipts only; persist them if users ever need older history.
    var terminal = Object.keys(ingestionManagement.runs).filter(function (id) {
      var status = ingestionManagement.runs[id].status;
      return status !== "queued" && status !== "running";
    });
    terminal.slice(0, -100).forEach(function (id) {
      delete ingestionManagement.runs[id];
    });
  }

  function pollManagementRun(runId, onComplete, refreshAfter, onFailure) {
    bridgeCall("get_intake_run", JSON.stringify({ run_id: runId })).then(function (raw) {
      var result = parseBridgeJson(raw);
      var payload = managementPayload(result);
      if (!payload) {
        var missingPayloadKey = managementError(result);
        rememberManagementRun(runId, { status: "failed" });
        setManagementStatus(
          ingestionManagement.sourceRootSelectionStale
            ? "sourceRootSelectionStale"
            : missingPayloadKey
        );
        if (typeof onFailure === "function") onFailure(missingPayloadKey);
        renderManagementRuns();
        return;
      }
      var run = payload.run && typeof payload.run === "object" ? payload.run : payload;
      rememberManagementRun(runId, run);
      renderManagementRuns();
      if (run.status === "queued" || run.status === "running") {
        setTimeout(function () { pollManagementRun(runId, onComplete, refreshAfter, onFailure); }, 750);
      } else {
        if (
          run.status === "completed" ||
          run.status === "review_required"
        ) {
          if (typeof onComplete === "function") onComplete(run);
        } else {
          var failureKey = run.error
            ? managementError({ error: run.error })
            : run.error_code
              ? managementError({ error: { code: run.error_code } })
            : "managementOperationFailed";
          setManagementStatus(
            ingestionManagement.sourceRootSelectionStale
              ? "sourceRootSelectionStale"
              : failureKey
          );
          if (typeof onFailure === "function") onFailure(failureKey);
        }
        if (refreshAfter !== false) refreshIngestionManagement();
      }
    });
  }

  function trackManagementRuns(result, onComplete, refreshAfter, onFailure) {
    var ids = collectRunIds(result);
    ids.forEach(function (runId) {
      rememberManagementRun(runId, { status: "queued" });
      pollManagementRun(runId, onComplete, refreshAfter, onFailure);
    });
    renderManagementRuns();
    return ids.length > 0;
  }

  function startManagementRun(method, payload, onComplete, refreshAfter, onFailure) {
    return bridgeCall(method, JSON.stringify(payload || {})).then(function (raw) {
      var result = parseBridgeJson(raw);
      if (!trackManagementRuns(result, onComplete, refreshAfter, onFailure)) {
        var errorKey = managementError(result);
        setManagementStatus(errorKey);
        if (typeof onFailure === "function") onFailure(errorKey);
      }
      return result;
    });
  }

  function inspectAndRestoreBackup(backup) {
    bridgeCall("inspect_backup", JSON.stringify({ path: backup.path })).then(function (raw) {
      var result = parseBridgeJson(raw);
      if (!managementPayload(result)) {
        setManagementStatus(managementError(result));
        return;
      }
      var inspection = managementPayload(result);
      var counts = inspection.counts && typeof inspection.counts === "object" ? inspection.counts : inspection;
      var impact = Object.keys(counts).filter(function (key) {
        return typeof counts[key] === "number";
      }).map(function (key) {
        return key + ": " + counts[key];
      }).join(" · ");
      if (!window.confirm(t("restoreConfirm") + (impact ? "\n" + impact : ""))) return;
      startManagementRun("restore_backup", {
        path: inspection.path || backup.path,
        expected_sha256: inspection.sha256 || backup.sha256,
      }, function () {
        setManagementStatus("restoreComplete");
      });
    });
  }

  function bindIngestionManagementEvents() {
    document.querySelectorAll("[data-ingestion-station]").forEach(function (button) {
      button.addEventListener("click", function () {
        ingestionNavigation.sourceHandoffReview = null;
        ingestionNavigation.station = String(button.dataset.ingestionStation || "source");
        renderManagementReviews();
        syncIngestionStation();
        window.requestAnimationFrame(function () {
          window.scrollTo(0, 0);
          button.focus({ preventScroll: true });
        });
      });
      button.addEventListener("keydown", function (event) {
        if (["ArrowLeft", "ArrowRight", "Home", "End"].indexOf(event.key) < 0) return;
        event.preventDefault();
        var tabs = Array.prototype.slice.call(document.querySelectorAll("[data-ingestion-station]"));
        var index = tabs.indexOf(button);
        if (event.key === "Home") index = 0;
        else if (event.key === "End") index = tabs.length - 1;
        else if (event.key === "ArrowLeft") index = (index - 1 + tabs.length) % tabs.length;
        else index = (index + 1) % tabs.length;
        var next = tabs[index];
        ingestionNavigation.sourceHandoffReview = null;
        ingestionNavigation.station = String(next.dataset.ingestionStation || "source");
        renderManagementReviews();
        syncIngestionStation();
        next.focus({ preventScroll: true });
      });
    });
    var ingestionBack = $("btn-ingestion-back");
    if (ingestionBack) ingestionBack.addEventListener("click", closeIngestionScene);
    var ingestionProduct = $("btn-ingestion-product-nav");
    if (ingestionProduct) ingestionProduct.addEventListener("click", function () {
      productPlanScene.open();
    });
    var ingestionTarget = $("btn-ingestion-target-nav");
    if (ingestionTarget) ingestionTarget.addEventListener("click", function () {
      var targetEntry = $("btn-open-target");
      if (targetEntry && !targetEntry.disabled) targetEntry.click();
    });
    var ingestionWarehouse = $("btn-ingestion-warehouse-nav");
    if (ingestionWarehouse) ingestionWarehouse.addEventListener("click", function () {
      if (ingestionNavigation.returnScene === "warehouse") {
        capsuleWarehouseScene.resume();
        return;
      }
      var productWarehouse = $("btn-product-open-warehouse");
      if (productWarehouse) productWarehouse.click();
      else capsuleWarehouseScene.open(null);
    });
    var ingestionCompatibility = $("btn-ingestion-compat-nav");
    if (ingestionCompatibility) ingestionCompatibility.addEventListener("click", function () {
      var productBack = $("btn-product-plan-back");
      if (productBack) productBack.click();
      else {
        showScreen("screen-main");
        syncAppState();
      }
    });
    var ingestionLanguage = $("btn-ingestion-lang");
    if (ingestionLanguage) ingestionLanguage.addEventListener("click", toggleLocale);
    var developerMode = $("warehouse-developer-mode");
    if (developerMode) developerMode.addEventListener("change", function () {
      ingestionManagement.developerMode = developerMode.checked === true;
      syncWarehouseMode();
    });
    syncWarehouseMode();
    var discover = $("btn-warehouse-discover");
    if (discover) discover.addEventListener("click", function () {
      bridgeCall("choose_source_root").then(function (raw) {
        var result = parseBridgeJson(raw);
        var payload = managementPayload(result);
        if (!payload) {
          if (!(result && result.cancelled)) setManagementStatus(managementError(result));
          return;
        }
        if (!trackManagementRuns(result, function (run) {
          selectDiscoveredSourceRoot(run.data);
          ingestionManagement.discovery = run.data || null;
          renderManagementProjects();
        }, false)) {
          ingestionManagement.discovery = payload.discovery || payload;
          selectDiscoveredSourceRoot(ingestionManagement.discovery);
          renderManagementProjects();
        }
      });
    });
    var refreshAll = $("btn-warehouse-refresh-all");
    if (refreshAll) refreshAll.addEventListener("click", function () {
      startManagementRun("start_refresh_all", {});
    });
    var refreshModels = $("btn-supervision-model-refresh");
    if (refreshModels) refreshModels.addEventListener("click", refreshIngestionManagement);
    var saveModel = $("btn-supervision-model-save");
    if (saveModel) saveModel.addEventListener("click", function () {
      var select = $("supervision-model-select");
      var model = select && select.value !== "" ? ingestionManagement.models[Number(select.value)] : null;
      if (!model) return;
      bridgeCall("select_supervision_model", JSON.stringify({ name: model.name, digest: model.digest })).then(function (raw) {
        var result = parseBridgeJson(raw);
        if (!managementPayload(result)) setManagementStatus(managementError(result));
        else if (!trackManagementRuns(result, function () {
          ingestionManagement.selectedModel = { name: model.name, digest: model.digest };
          renderManagementModels();
          setManagementStatus("modelSaved");
        }, false)) {
          ingestionManagement.selectedModel = { name: model.name, digest: model.digest };
          renderManagementModels();
          setManagementStatus("modelSaved");
        }
      });
    });
    var backup = $("btn-warehouse-backup");
    if (backup) backup.addEventListener("click", function () {
      startManagementRun("create_backup", { kind: "manual" }, function () {
        setManagementStatus("backupCreated");
      });
    });
    var legacyImport = $("btn-warehouse-import");
    if (legacyImport) legacyImport.addEventListener("click", function () {
      startManagementRun("start_legacy_import", {}, function () {
        setManagementStatus("importStarted");
      });
    });
  }

  function applyVerificationResult(sourceId, result) {
    if (!result || !result.ok || !result.summary) return;
    if (!data.verificationBySource) data.verificationBySource = {};
    data.verificationBySource[sourceId] = {
      verified: result.summary.verified || 0,
      watch: result.summary.watch || 0,
      rejected: result.summary.rejected || 0,
      total: result.summary.total || 0,
    };
    console.log(
      "[Reweave] suggestion verification:",
      data.verificationBySource[sourceId].verified,
      "verified /",
      data.verificationBySource[sourceId].watch,
      "watch /",
      data.verificationBySource[sourceId].rejected,
      "rejected"
    );
  }

  function applyGovernancePreviewResult(sourceId, result) {
    if (!result || !result.ok || !result.summary) return;
    if (!data.governancePreviewBySource) data.governancePreviewBySource = {};
    data.governancePreviewBySource[sourceId] = {
      keep: result.summary.keep || 0,
      watch: result.summary.watch || 0,
      prune: result.summary.prune || 0,
      needs_manual_review: result.summary.needs_manual_review || 0,
      total: result.summary.total || 0,
    };
    if (result.warnings && result.warnings.length) {
      console.warn("[Reweave] governance preview warnings:", result.warnings.join(", "));
    }
    console.log(
      "[Reweave] governance preview:",
      data.governancePreviewBySource[sourceId].keep,
      "keep /",
      data.governancePreviewBySource[sourceId].watch,
      "watch /",
      data.governancePreviewBySource[sourceId].prune,
      "prune /",
      data.governancePreviewBySource[sourceId].needs_manual_review,
      "review"
    );
  }

  function applyReviewQueueResult(sourceId, result) {
    if (!result || !result.ok || !result.summary) return;
    if (!data.reviewQueueBySource) data.reviewQueueBySource = {};
    var items = (result.queue && result.queue.items) || [];
    data.reviewQueueBySource[sourceId] = {
      summary: result.summary,
      items: items,
    };
    console.log("[Reweave] review queue:", result.summary);
  }

  function handleCreateReviewQueue(sourceId) {
    if (!hasDesktopBridge() || !sourceId || isLumoLiteReadOnly()) return;
    reviewingSourceIds[sourceId] = true;
    renderSources();
    bridgeCall("create_review_queue_for_source", sourceId).then(function (raw) {
      delete reviewingSourceIds[sourceId];
      var result = parseBridgeJson(raw);
      if (result && result.ok) {
        applyReviewQueueResult(sourceId, result);
      } else if (result && result.error) {
        console.warn("[Reweave] review queue failed:", result.error);
      }
      renderSources();
    });
  }

  function handlePromoteReviewItem(sourceId, reviewId) {
    if (!hasDesktopBridge() || !sourceId || !reviewId) return;
    if (isLumoLiteReadOnly() || !desktopCapability("canPromoteDrafts")) return;
    bridgeCall(
      "promote_review_item",
      JSON.stringify({
        source_id: sourceId,
        review_id: reviewId,
      })
    ).then(function (raw) {
      var result = parseBridgeJson(raw);
      if (!result || !result.ok) {
        if (result && result.error) {
          console.warn("[Reweave] promote failed:", result.error);
        }
        return;
      }
      if (data.reviewQueueBySource && data.reviewQueueBySource[sourceId]) {
        var items = data.reviewQueueBySource[sourceId].items;
        if (Array.isArray(items)) {
          items.forEach(function (item) {
            if (item.review_id === reviewId) {
              item.promoted = true;
              item.capsule_id = result.capsule_id;
              item.warehouse_action = result.warehouse_action || "promoted";
            }
          });
        }
      }
      if (!data.promotedCountBySource) data.promotedCountBySource = {};
      var prev = data.promotedCountBySource[sourceId] || 0;
      if (!result.already_promoted) {
        data.promotedCountBySource[sourceId] = prev + 1;
      }
      if (Array.isArray(result.capsules)) {
        applyWarehouseCapsules(result.capsules);
      } else if (Array.isArray(result.warehouseCapsules)) {
        applyWarehouseCapsules(result.warehouseCapsules);
      }
      renderSources();
    });
  }

  function handleEnrichCapsuleContent(capsuleId) {
    if (!hasDesktopBridge() || !capsuleId) return;
    bridgeCall("enrich_capsule_content", capsuleId).then(function (raw) {
      var result = parseBridgeJson(raw);
      if (result && result.ok) {
        if (Array.isArray(result.capsules)) {
          applyWarehouseCapsules(result.capsules);
        }
        var cap = findCapsule(capsuleId);
        if (cap && result.content_path) {
          cap.content_enrichment = {
            status: "enriched",
            content_path: result.content_path,
            snippet_count: result.snippet_count,
          };
        }
        clearReaderContentPanel();
        if (cap) showCapsuleReader(cap);
      } else if (result && result.error) {
        console.warn("[Reweave] enrich failed:", result.error);
      }
    });
  }

  function clearReaderContentPanel() {
    var panel = document.getElementById("reader-content-panel");
    if (panel) panel.remove();
  }

  function renderReaderContentPanel(cap, contentPayload) {
    clearReaderContentPanel();
    if (!contentPayload || !els.reader) return;
    var panel = document.createElement("div");
    panel.id = "reader-content-panel";
    panel.className = "reader-content-panel";

    var safety = contentPayload.safety || {};
    var safetyEl = document.createElement("p");
    safetyEl.className = "reader-content-safety";
    var safetyBits = ["preview only"];
    if (safety.source_folder_written === false) safetyBits.unshift("source folder not modified");
    if ((contentPayload.limits || {}).secret_redaction) safetyBits.push("secrets redacted");
    safetyEl.textContent = safetyBits.join(" · ");
    panel.appendChild(safetyEl);

    var warnings = Array.isArray(contentPayload.warnings) ? contentPayload.warnings : [];
    if (warnings.length) {
      var warnBtn = document.createElement("button");
      warnBtn.type = "button";
      warnBtn.className = "btn-ghost btn-content-warnings";
      warnBtn.textContent = t("warnings") + " " + warnings.length;
      var warnList = document.createElement("ul");
      warnList.className = "reader-content-warnings hidden";
      warnings.forEach(function (w) {
        var li = document.createElement("li");
        li.textContent = String(w);
        warnList.appendChild(li);
      });
      warnBtn.addEventListener("click", function (e) {
        e.preventDefault();
        e.stopPropagation();
        warnList.classList.toggle("hidden");
      });
      panel.appendChild(warnBtn);
      panel.appendChild(warnList);
    }

    var snippets = Array.isArray(contentPayload.snippets) ? contentPayload.snippets.slice(0, 2) : [];
    snippets.forEach(function (snip) {
      var block = document.createElement("div");
      block.className = "reader-snippet-block";
      var head = document.createElement("div");
      head.className = "reader-snippet-head";
      head.textContent =
        (snip.relative_path || "file") +
        " · " +
        (snip.language_hint || "text") +
        " · " +
        (snip.bytes_read != null ? snip.bytes_read + " bytes" : "");
      block.appendChild(head);
      var badges = document.createElement("div");
      badges.className = "reader-snippet-badges";
      if (snip.truncated) {
        var tBadge = document.createElement("span");
        tBadge.className = "reader-snippet-badge";
        tBadge.textContent = t("truncated");
        badges.appendChild(tBadge);
      }
      if (snip.redacted) {
        var rBadge = document.createElement("span");
        rBadge.className = "reader-snippet-badge reader-snippet-badge-redacted";
        rBadge.textContent = t("redacted");
        badges.appendChild(rBadge);
      }
      if (badges.childNodes.length) block.appendChild(badges);
      var pre = document.createElement("pre");
      pre.className = "reader-snippet-preview";
      pre.textContent = String(snip.preview || "");
      block.appendChild(pre);
      panel.appendChild(block);
    });

    var previewEl = $("reader-preview");
    if (previewEl && previewEl.parentNode === els.reader) {
      var actions = document.querySelector(".reader-actions");
      if (actions && actions.parentNode === els.reader) {
        els.reader.insertBefore(panel, actions);
      } else {
        els.reader.appendChild(panel);
      }
    } else {
      els.reader.appendChild(panel);
    }
  }

  function handleViewCapsuleContent(capsuleId) {
    if (!hasDesktopBridge() || !capsuleId) return;
    bridgeCall("get_capsule_content", capsuleId).then(function (raw) {
      var result = parseBridgeJson(raw);
      if (!result || !result.ok || !result.content) {
        if (result && result.error) {
          console.warn("[Reweave] view content failed:", result.error);
        }
        return;
      }
      var cap = findCapsule(capsuleId);
      if (cap) renderReaderContentPanel(cap, result.content);
    });
  }

  function handleUpdateCapsuleStatus(capsuleId, status) {
    if (!hasDesktopBridge() || !capsuleId || !status) return;
    bridgeCall(
      "update_capsule_status",
      JSON.stringify({ capsule_id: capsuleId, status: status })
    ).then(function (raw) {
      var result = parseBridgeJson(raw);
      if (result && result.ok && Array.isArray(result.capsules)) {
        applyWarehouseCapsules(result.capsules);
        if (selectedCapsuleId === capsuleId) {
          var cap = findCapsule(capsuleId);
          if (cap) showCapsuleReader(cap);
        }
      } else if (result && result.error) {
        console.warn("[Reweave] capsule status update failed:", result.error);
      }
    });
  }

  function handleReviewDecision(sourceId, reviewId, decision) {
    if (!hasDesktopBridge() || !sourceId || !reviewId) return;
    bridgeCall(
      "update_review_decision",
      JSON.stringify({
        source_id: sourceId,
        review_id: reviewId,
        decision: decision,
        reason: "",
      })
    ).then(function (raw) {
      var result = parseBridgeJson(raw);
      if (result && result.ok && result.summary && data.reviewQueueBySource && data.reviewQueueBySource[sourceId]) {
        data.reviewQueueBySource[sourceId].summary = result.summary;
        if (result.item && Array.isArray(data.reviewQueueBySource[sourceId].items)) {
          data.reviewQueueBySource[sourceId].items.forEach(function (item) {
            if (item.review_id === result.item.review_id) {
              item.decision = result.item.decision;
            }
          });
        }
        renderSources();
      }
    });
  }

  function appendReviewMiniPanel(li, sourceId, queueData) {
    if (!queueData || !Array.isArray(queueData.items) || !queueData.items.length) return;
    var panel = document.createElement("div");
    panel.className = "source-review-mini";
    queueData.items.slice(0, 3).forEach(function (item) {
      var row = document.createElement("div");
      row.className = "source-review-row";
      var score = item.verification_score != null ? Number(item.verification_score).toFixed(2) : "—";
      row.innerHTML =
        '<span class="source-review-name">' +
        escapeHtml(item.name || item.review_id) +
        "</span>" +
        '<span class="source-review-meta">' +
        escapeHtml(item.governance_action || "") +
        " · " +
        escapeHtml(String(score)) +
        "</span>";
      if (item.decision === "pending" || item.decision === "deferred") {
        ["approved", "rejected", "deferred"].forEach(function (decision) {
          var btn = document.createElement("button");
          btn.type = "button";
          btn.className = "btn-ghost btn-source-scan btn-review-decision";
          btn.textContent = decision === "approved" ? t("approve") : decision === "rejected" ? t("reject") : t("defer");
          btn.addEventListener("click", function (e) {
            e.preventDefault();
            e.stopPropagation();
            handleReviewDecision(sourceId, item.review_id, decision);
          });
          row.appendChild(btn);
        });
      } else if (item.decision === "approved" && !item.promoted) {
        if (hasDesktopBridge() && !isLumoLiteReadOnly() && desktopCapability("canPromoteDrafts")) {
          var promoteBtn = document.createElement("button");
          promoteBtn.type = "button";
          promoteBtn.className = "btn-ghost btn-source-scan btn-review-promote";
          promoteBtn.textContent = t("promote");
          promoteBtn.addEventListener("click", function (e) {
            e.preventDefault();
            e.stopPropagation();
            handlePromoteReviewItem(sourceId, item.review_id);
          });
          row.appendChild(promoteBtn);
        }
      } else {
        var tag = document.createElement("span");
        tag.className = "source-review-decision";
        tag.textContent = item.promoted ? t("promoted") : t(item.decision);
        row.appendChild(tag);
      }
      panel.appendChild(row);
    });
    li.appendChild(panel);
  }

  function handleGovernancePreview(sourceId) {
    if (!hasDesktopBridge() || !sourceId || isLumoLiteReadOnly()) return;
    previewingSourceIds[sourceId] = true;
    renderSources();
    bridgeCall("preview_governance_for_source", sourceId).then(function (raw) {
      delete previewingSourceIds[sourceId];
      var result = parseBridgeJson(raw);
      if (result && result.ok) {
        applyGovernancePreviewResult(sourceId, result);
      } else if (result && result.error) {
        console.warn("[Reweave] governance preview failed:", result.error);
      }
      renderSources();
    });
  }

  function handleVerifySource(sourceId) {
    if (!hasDesktopBridge() || !sourceId || isLumoLiteReadOnly()) return;
    verifyingSourceIds[sourceId] = true;
    renderSources();
    bridgeCall("verify_source_suggestions", sourceId).then(function (raw) {
      delete verifyingSourceIds[sourceId];
      var result = parseBridgeJson(raw);
      if (result && result.ok) {
        applyVerificationResult(sourceId, result);
      } else if (result && result.error) {
        console.warn("[Reweave] verify failed:", result.error);
      }
      renderSources();
    });
  }

  function sourceScanLabel(src) {
    if (sourceWorkflow.sourceScanLabel) {
      return sourceWorkflow.sourceScanLabel(src, {
        verifying: !!verifyingSourceIds[src.id],
        previewing: !!previewingSourceIds[src.id],
        reviewing: !!reviewingSourceIds[src.id],
        lunaReuse: !!(data.lunaReuseBySource && data.lunaReuseBySource[src.id]),
        locale: locale,
      });
    }
    return src.scan_status || "not_scanned";
  }

  function getGenerateCandidateIds() {
    return usedCapsuleIds.slice();
  }

  function anyEnrichedInIds(ids) {
    return (ids || []).some(function (id) {
      var cap = findCapsule(id);
      return !!(cap && cap.content_enrichment && cap.content_enrichment.status === "enriched");
    });
  }

  function updateEnrichedContentToggle() {
    var wrap = $("enriched-content-toggle-wrap");
    var checkbox = $("use-enriched-content");
    if (!wrap || !checkbox) return;
    var canUse = hasDesktopBridge() && anyEnrichedInIds(getGenerateCandidateIds());
    wrap.classList.toggle("hidden", !canUse);
    if (!canUse) {
      useEnrichedContentPreview = false;
      checkbox.checked = false;
    }
  }

  function failedProductResult(code) {
    return {
      ok: false,
      error: { code: code || "product_generation_failed", message_key: "generationFailed" },
    };
  }

  function pollProductRun(runId) {
    return new Promise(function (resolve) {
      function poll() {
        bridgeCall("get_intake_run", JSON.stringify({ run_id: runId })).then(function (raw) {
          var result = parseBridgeJson(raw);
          var payload = managementPayload(result);
          var task = payload && payload.run && typeof payload.run === "object" ? payload.run : payload;
          if (!task || !task.status) {
            resolve(result || failedProductResult("product_run_unavailable"));
            return;
          }
          if (task.status === "queued" || task.status === "running") {
            setTimeout(poll, 750);
            return;
          }
          if (task.status === "completed" && task.data && typeof task.data === "object") {
            resolve(task.data);
            return;
          }
          var code = task.error && (task.error.code || task.error.message_key);
          resolve(failedProductResult(code || "product_generation_failed"));
        }).catch(function () {
          resolve(failedProductResult("product_run_unavailable"));
        });
      }
      poll();
    });
  }

  function notifyDesktopGenerate(text, ids) {
    if (!hasDesktopBridge()) {
      pendingGeneratePromise = null;
      return Promise.resolve(null);
    }
    var payload = {
      task: text,
      capsule_ids: ids,
      selection_mode: "manual",
    };
    pendingGeneratePromise = bridgeCall("generate_product", JSON.stringify(payload)).then(function (raw) {
      var result = parseBridgeJson(raw);
      var started = managementPayload(result);
      if (!started || !started.run_id) return result || failedProductResult("product_run_unavailable");
      return pollProductRun(String(started.run_id));
    });
    return pendingGeneratePromise;
  }

  function applyGenerateResult(result) {
    if (!result || !result.ok) return;
    lastPreviewAcceptance = result.previewAcceptance || null;
    var reactPreview = result.taskPack && result.taskPack.react_preview;
    var runtimeValidation = result.runtimeValidation || {};
    lastReactPreview =
      reactPreview &&
      reactPreview.status === "passed" &&
      runtimeValidation.status === "passed" &&
      runtimeValidation.preview_image === "react_project/dist/preview.png"
        ? { image: runtimeValidation.preview_image }
        : null;
    if (result.generatedPackage) {
      data.generatedPackage = result.generatedPackage;
      data.generatedPackage.mode = result.mode || "";
    }
    data.qualityGate = result.taskPack && result.taskPack.quality_gate ? result.taskPack.quality_gate : null;
    data.generatedTraceVerified = !!(
      result.provenance &&
      result.provenance.source_project_write === false &&
      (Array.isArray(result.provenance.outputs) || result.provenance.file_provenance)
    );
    if (result.productEntry && data.generatedPackage) {
      data.generatedPackage.productEntry = result.productEntry;
    }
    if (result.previewPath) {
      lastPreviewPath = result.previewPath;
    }
    if (result.lunaPack && result.lunaPack.pack_id) {
      console.log("[Reweave] Luna pack indexed:", result.lunaPack.pack_id);
      data.lunaPack = result.lunaPack;
    }
    if (result.warnings && result.warnings.length) {
      console.warn("[Reweave] generate warnings:", result.warnings.join(", "));
    }
    if (result.contentAwareGenerate) {
      data.contentAwareGenerate = result.contentAwareGenerate;
    }
    if (Array.isArray(result.capsulesUsed)) {
      usedCapsuleIds = result.capsulesUsed.map(function (cap) {
        return cap.id || cap.capsule_id;
      }).filter(Boolean);
      usedCapsuleSelectionMode = "manual";
      renderUsedChips();
    }
  }

  function previewAcceptanceText(acceptance) {
    if (!acceptance) return "";
    if (acceptance.reason === "real_qwebengine_product_bootstrap") {
      return t("acceptanceRealBootstrap");
    }
    if (
      acceptance.verdict === "usable" &&
      (acceptance.reason === "runtime_behavior_verified" || acceptance.reason === "react_runtime_verified")
    ) {
      return t("acceptanceUsable");
    }
    if (
      acceptance.reason === "runtime_behavior_failed" ||
      acceptance.reason === "react_runtime_failed"
    ) return t("acceptanceRejectedRuntime");
    if (acceptance.verdict === "rejected") return t("acceptanceRejected");
    if (acceptance.reason === "quality_gate_not_reported") return t("acceptanceNeedsQuality");
    if (
      acceptance.reason === "runtime_validation_required" ||
      acceptance.reason === "desktop_runtime_validation_required" ||
      acceptance.reason === "react_runtime_not_verified" ||
      acceptance.reason === "react_compile_not_verified"
    ) return t("acceptanceNeedsRuntime");
    return t("acceptanceNeedsBehavior");
  }

  function showScreen(id) {
    if (id === "screen-main" && productPlanScene.consumeWarehouseReturn()) {
      id = "screen-product-plan";
    }
    ["screen-welcome", "screen-cleaning", "screen-main", "screen-product-plan", "screen-capsule-warehouse", "screen-capsule-ingestion", "screen-target"].forEach(function (sid) {
      $(sid).classList.toggle("hidden", sid !== id);
    });
  }

  function loadMockData(callback) {
    var embed = document.getElementById("mock-data-embed");

    function apply(raw) {
      data = JSON.parse(raw);
      normalizeMockFallback();
      callback(null);
    }

    function useEmbed() {
      if (!embed || !embed.textContent.trim()) {
        callback(new Error("Failed to load mock-data.json"));
        return;
      }
      try {
        apply(embed.textContent);
      } catch (e) {
        callback(e);
      }
    }

    if (new URLSearchParams(window.location.search).get("desktop") === "1") {
      useEmbed();
      return;
    }

    var xhr = new XMLHttpRequest();
    xhr.open("GET", "mock-data.json", true);
    xhr.onload = function () {
      if ((xhr.status >= 200 && xhr.status < 300) || xhr.status === 0) {
        try {
          apply(xhr.responseText);
          return;
        } catch (e) {
          useEmbed();
          return;
        }
      }
      useEmbed();
    };
    xhr.onerror = useEmbed;
    xhr.send();
  }

  function t(key) {
    return (STR[locale] && STR[locale][key]) || STR.en[key] || key;
  }

  function formatText(key, values) {
    var text = t(key);
    Object.keys(values || {}).forEach(function (name) {
      text = text.split("{" + name + "}").join(String(values[name]));
    });
    return text;
  }

  function prefersReducedMotion() {
    return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  }

  function setAppState(state) {
    appState = state;
    if (els.screenMain) {
      els.screenMain.setAttribute("data-app-state", state);
    }
  }

  function syncAppState() {
    if (isGenerating) {
      setAppState("invoking");
      return;
    }
    if (usedCapsuleIds.length > 0 && els.reweaveResponse && els.reweaveResponse.textContent) {
      setAppState("ready");
      return;
    }
    if (selectedCapsuleId) {
      setAppState("selected");
      return;
    }
    setAppState("idle");
  }

  function getCapsuleSerial(cap) {
    return capsuleReader.serial ? capsuleReader.serial(cap) : "00";
  }

  function applyLocale() {
    document.documentElement.lang = locale === "zh" ? "zh-CN" : "en";
    document.querySelectorAll("[data-i18n]").forEach(function (el) {
      var key = el.getAttribute("data-i18n");
      if (key && t(key)) el.textContent = t(key);
    });
    document.querySelectorAll("[data-i18n-aria-label]").forEach(function (el) {
      var key = el.getAttribute("data-i18n-aria-label");
      if (key && t(key)) {
        el.setAttribute("aria-label", t(key));
        el.title = t(key);
      }
    });
    document.querySelectorAll("[data-i18n-title]").forEach(function (el) {
      var key = el.getAttribute("data-i18n-title");
      controlHelp(el, key);
    });
    document.querySelectorAll("[data-i18n-placeholder]").forEach(function (el) {
      var key = el.getAttribute("data-i18n-placeholder");
      if (key && t(key)) el.placeholder = t(key);
    });
    syncWarehouseMode();
    var input = $("task-input");
    if (input) input.placeholder = t("taskPlaceholder");
    var langBtn = $("btn-lang");
    if (langBtn) langBtn.textContent = locale === "zh" ? "中·EN" : "EN·中";
    var wl = $("btn-welcome-lang");
    if (wl) wl.textContent = locale === "zh" ? "中·EN" : "EN·中";
    if (els.usedCapsuleDock && usedCapsuleIds.length === 0) {
      els.usedCapsuleDock.innerHTML =
        '<span class="used-placeholder">' + escapeHtml(t("usedPlaceholder")) + "</span>";
    }
    if (els.generationInputNote) {
      els.generationInputNote.textContent =
        usedCapsuleIds.length > 0
          ? formatText("generationManual", { count: usedCapsuleIds.length })
          : t("generationAuto");
    }
    var useBtn = $("btn-use-in-task");
    if (useBtn) useBtn.textContent = t("useInTask");
    var readerLabel = document.querySelector(".reader-slot-label");
    if (readerLabel) readerLabel.textContent = t("readerLabel").toUpperCase();
    syncWelcomeSourceBoxMode();
    if (data) {
      renderHistory();
      renderSources();
    }
    renderIngestionManagement();
    if (selectedCapsuleId && els.reader && !els.reader.classList.contains("hidden")) {
      var selected = findCapsule(selectedCapsuleId);
      if (selected) showCapsuleReader(selected);
    }
    applyLumoLiteRuntimeView();
    if (data && !isLumoLiteReadOnly()) {
      syncGeneratedPackageView();
    }
    capsuleWarehouseScene.sync();
    productPlanScene.sync();
    targetIntegration.sync();
    syncFormalNavigation();
  }

  function toggleLocale() {
    locale = locale === "zh" ? "en" : "zh";
    localStorage.setItem("reweave_locale", locale);
    applyLocale();
    if (els.usedCount && els.usedCapsuleDock) renderUsedChips();
    if (appState === "ready" && usedCapsuleIds.length > 0) {
      finishGenerate(els.taskInput.value.trim() || data.sampleTask || t("smallProjectPack"), usedCapsuleIds.length, true);
    }
  }

  function initWelcome() {
    cacheElements();
    bindMainEvents();
    applyLocale();
    syncWelcomeSourceBoxMode();
    var vr = $("btn-view-runtime");
    if (vr) {
      vr.addEventListener("click", function () {
        initMain({ compatibility: true });
      });
    }
    var wl = $("btn-welcome-lang");
    if (wl) wl.addEventListener("click", toggleLocale);
  }

  function startCleaning() {
    showScreen("screen-cleaning");
    var stepsEl = $("cleaning-steps");
    var bar = $("progress-bar");
    stepsEl.innerHTML = "";
    var steps = data.cleaningSteps || [];
    steps.forEach(function (text) {
      var li = document.createElement("li");
      li.textContent = text;
      stepsEl.appendChild(li);
    });

    var index = 0;
    function tick() {
      var items = stepsEl.querySelectorAll("li");
      items.forEach(function (li, i) {
        li.classList.remove("active", "done");
        if (i < index) li.classList.add("done");
        if (i === index) li.classList.add("active");
      });
      bar.style.width = ((index + 1) / steps.length) * 100 + "%";
      index += 1;
      if (index <= steps.length) {
        setTimeout(tick, 650);
      } else {
        setTimeout(function () {
          initMain({ compatibility: true });
        }, 400);
      }
    }
    tick();
  }

  function initMain(options) {
    options = options || {};
    showScreen("screen-main");
    cacheElements();
    usedCapsuleIds = [];
    selectedCapsuleId = null;
    isGenerating = false;
    applyLocale();
    renderCapsuleStrip();
    syncGeneratedPackageView();
    renderHistory();
    renderSources();
    bindMainEvents();
    if (data.sampleTask && els.taskInput) {
      els.taskInput.value = data.sampleTask;
    }
    if (els.reweaveResponse) els.reweaveResponse.textContent = "";
    setAppState("idle");
    applyLumoLiteRuntimeView();
    capsuleWarehouseScene.sync();
    productPlanScene.sync();
    targetIntegration.sync();
    if (
      options.compatibility !== true &&
      desktopShellState &&
      desktopShellState.canPlanProduct === true
    ) {
      productPlanScene.open();
    }
  }

  function cacheElements() {
    els.screenMain = $("screen-main");
    els.capsuleDock = $("capsule-dock");
    els.capsuleStrip = $("capsule-strip");
    els.capsuleCount = $("capsule-count");
    els.taskBay = $("task-bay");
    els.usedCapsuleDock = $("used-capsule-dock");
    els.generationInputNote = $("generation-input-note");
    els.usedCount = $("used-count");
    els.taskInput = $("task-input");
    els.btnGenerate = $("btn-generate");
    els.reweaveResponse = $("reweave-response");
    els.generatedTree = $("generated-tree");
    els.generatedPreview = $("generated-preview");
    els.workflowStatus = $("workflow-status");
    els.genCapsulesUsed = $("gen-capsules-used");
    els.reader = $("capsule-reader");
    els.historyPopover = $("history-popover");
    els.sourcesPopover = $("sources-popover");
    els.backdrop = $("backdrop");
    els.readerConnector = $("reader-connector");
    els.generatedPackage = $("generated-package");
    els.previewPackageActions = $("preview-package-actions");
    els.previewPackageViewer = $("preview-package-viewer");
    els.previewViewerBody = $("preview-viewer-body");
    els.previewViewerTitle = $("preview-viewer-title");
    els.btnLumoArtifacts = $("btn-lumo-artifacts");
    els.lumoArtifactsPopover = $("lumo-artifacts-popover");
    els.lumoArtifactsBody = $("lumo-artifacts-body");
    els.btnCapsuleWarehouse = $("btn-capsule-warehouse");
    els.capsuleWarehousePopover = $("capsule-warehouse-popover");
    els.runtimeSidecarMode = $("runtime-sidecar-mode");
    els.runtimeSidecarSource = $("runtime-sidecar-source");
    els.runtimeSidecarStatus = $("runtime-sidecar-status");
  }

  function shortName(name) {
    if (!name) return name;
    if (name.length <= 18) return name;
    return name.slice(0, 17) + "…";
  }

  function getVisibleCapsules() {
    return (data.capsules || []).slice();
  }

  function capsuleSourceLabel(cap) {
    return capsuleReader.sourceLabel ? capsuleReader.sourceLabel(cap) : "";
  }

  function renderCapsuleStrip() {
    if (!els.capsuleCount || !els.capsuleStrip) return;
    els.capsuleCount.textContent = String((data.capsules || []).length);
    els.capsuleStrip.innerHTML = "";
    getVisibleCapsules().forEach(function (cap) {
      var btn = document.createElement("button");
      var inactive = !isCapsuleGenerateEligible(cap);
      btn.type = "button";
      btn.className =
        "capsule-cartridge" +
        (cap.id === selectedCapsuleId ? " selected" : "") +
        (inactive ? " cartridge-inactive" : "") +
        (isMetadataCapsule(cap) ? " cartridge-metadata" : "");
      btn.dataset.capsuleId = cap.id;
      btn.dataset.capsuleType = cap.type;
      btn.dataset.source = capsuleSourceLabel(cap);
      btn.dataset.capsuleSerial = getCapsuleSerial(cap);
      btn.setAttribute("role", "listitem");
      btn.setAttribute("aria-label", cap.name + " (" + cap.type + ")");
      btn.setAttribute("aria-pressed", cap.id === selectedCapsuleId ? "true" : "false");
      var metaBadge = isMetadataCapsule(cap)
        ? '<span class="cartridge-meta-badge">META</span>'
        : "";
      var statusBadge =
        cap.status && cap.status !== "active" && cap.status !== "ready"
          ? '<span class="cartridge-status-badge">' + escapeHtml(cap.status) + "</span>"
          : "";
      btn.innerHTML =
        '<span class="cartridge-notch" aria-hidden="true"></span>' +
        '<span class="cartridge-seam" aria-hidden="true"></span>' +
        '<span class="cartridge-pattern" aria-hidden="true"></span>' +
        metaBadge +
        statusBadge +
        '<span class="cartridge-face">' +
        '<span class="cartridge-icon">' + escapeHtml(cap.icon) + "</span>" +
        '<span class="cartridge-name">' + escapeHtml(shortName(cap.name)) + "</span>" +
        '<span class="cartridge-type">' + escapeHtml(cap.type) + "</span>" +
        "</span>" +
        '<span class="cartridge-serial" aria-hidden="true">' +
        escapeHtml(getCapsuleSerial(cap)) +
        "</span>";
      btn.addEventListener("click", function () {
        selectCapsule(cap.id);
      });
      els.capsuleStrip.appendChild(btn);
    });
  }

  function findCapsule(id) {
    return (data.capsules || []).find(function (c) {
      return c.id === id;
    });
  }

  function selectCapsule(id) {
    selectedCapsuleId = id;
    renderCapsuleStrip();
    var cap = findCapsule(id);
    if (!cap) return;
    showCapsuleReader(cap);
    setAppState("selected");
  }

  function showCapsuleReader(cap) {
    clearReaderContentPanel();
    setRuntimeSidecarVisible(false);
    var readerIcon = $("reader-icon");
    var readerName = $("reader-name");
    var readerType = $("reader-type");
    var readerSource = $("reader-source");
    var readerTags = $("reader-tags");
    var readerRole = $("reader-role");
    var readerPreview = $("reader-preview");
    if (!readerIcon || !readerName || !readerType || !readerSource || !readerTags || !readerRole || !readerPreview) return;
    readerIcon.textContent = cap.icon;
    readerName.textContent = cap.name;
    readerType.textContent = cap.type;
    readerSource.textContent = t("fromSource") + " " + capsuleSourceLabel(cap);
    var tagBits = capsuleReader.tagBits ? capsuleReader.tagBits(cap) : (cap.tags || []).slice();
    readerTags.textContent = t("tagsPrefix") + " " + tagBits.join(" · ");
    readerRole.textContent = t("rolePrefix") + " " + (cap.role || "");
    readerPreview.textContent = capsuleReader.previewText
      ? capsuleReader.previewText(cap)
      : (cap.preview || []).join("\n");
    var actions = document.querySelector(".reader-actions");
    if (actions) {
      var useBtn = $("btn-use-in-task");
      if (useBtn) {
        var eligible = isCapsuleGenerateEligible(cap);
        useBtn.disabled = !eligible;
        useBtn.textContent = eligible ? t("useInTask") : t("readOnly");
      }
      var existingStatus = actions.querySelector(".reader-status-actions");
      if (existingStatus) existingStatus.remove();
      var existingEnrich = actions.querySelector(".reader-enrich-actions");
      if (existingEnrich) existingEnrich.remove();
      var existingView = actions.querySelector(".reader-view-content-actions");
      if (existingView) existingView.remove();
      if (
        hasDesktopBridge() &&
        cap.id &&
        isMetadataCapsule(cap) &&
        isCapsuleManageEligible(cap) &&
        !(cap.content_enrichment && cap.content_enrichment.status === "enriched")
      ) {
        var enrichWrap = document.createElement("div");
        enrichWrap.className = "reader-enrich-actions";
        var enrichBtn = document.createElement("button");
        enrichBtn.type = "button";
        enrichBtn.className = "btn-ghost btn-capsule-enrich";
        enrichBtn.textContent = t("enrichContent");
        enrichBtn.addEventListener("click", function (e) {
          e.preventDefault();
          e.stopPropagation();
          handleEnrichCapsuleContent(cap.id);
        });
        enrichWrap.appendChild(enrichBtn);
        actions.appendChild(enrichWrap);
      } else if (
        hasDesktopBridge() &&
        cap.id &&
        isCapsuleManageEligible(cap) &&
        cap.content_enrichment &&
        cap.content_enrichment.status === "enriched"
      ) {
        var viewWrap = document.createElement("div");
        viewWrap.className = "reader-view-content-actions";
        var viewBtn = document.createElement("button");
        viewBtn.type = "button";
        viewBtn.className = "btn-ghost btn-capsule-view-content";
        viewBtn.textContent = t("viewContent");
        viewBtn.addEventListener("click", function (e) {
          e.preventDefault();
          e.stopPropagation();
          handleViewCapsuleContent(cap.id);
        });
        viewWrap.appendChild(viewBtn);
        actions.appendChild(viewWrap);
      }
      if (hasDesktopBridge() && cap.id && isCapsuleManageEligible(cap)) {
        var statusWrap = document.createElement("div");
        statusWrap.className = "reader-status-actions";
        ["disabled", "deprecated"].forEach(function (status) {
          var btn = document.createElement("button");
          btn.type = "button";
          btn.className = "btn-ghost btn-capsule-status";
          btn.textContent = status === "disabled" ? "Disable" : "Deprecate";
          btn.addEventListener("click", function (e) {
            e.preventDefault();
            e.stopPropagation();
            handleUpdateCapsuleStatus(cap.id, status);
          });
          statusWrap.appendChild(btn);
        });
        actions.appendChild(statusWrap);
      }
    }
    els.reader.classList.remove("hidden");
    els.reader.classList.add("is-open");
    els.reader.setAttribute("data-capsule-id", cap.id);
    requestAnimationFrame(function () {
      requestAnimationFrame(function () {
        positionReaderNearCapsule(cap.id);
      });
    });
  }

  function positionReaderNearCapsule(id) {
    var chip = els.capsuleStrip.querySelector('[data-capsule-id="' + id + '"]');
    var bay = els.taskBay;
    if (!bay) return;

    var bayRect = bay.getBoundingClientRect();
    var chipRect = chip ? chip.getBoundingClientRect() : bayRect;
    var readerW = 248;
    var gap = 14;
    var top = Math.max(72, chipRect.top - 8);
    var left = bayRect.right + gap;

    if (left + readerW > window.innerWidth - 16) {
      left = Math.max(16, chipRect.right + gap);
      top = chipRect.top;
    }

    els.reader.style.top = top + "px";
    els.reader.style.left = left + "px";
    els.reader.style.right = "auto";

    if (els.readerConnector && chip) {
      var readerRect = els.reader.getBoundingClientRect();
      var path = els.readerConnector.querySelector("path");
      if (path) {
        var x1 = chipRect.right;
        var y1 = chipRect.top + chipRect.height * 0.5;
        var x2 = readerRect.left + 2;
        var y2 = readerRect.top + 28;
        var midX = (x1 + x2) * 0.5;
        path.setAttribute(
          "d",
          "M" + x1 + " " + y1 + " C " + midX + " " + y1 + ", " + midX + " " + y2 + ", " + x2 + " " + y2
        );
        els.readerConnector.classList.remove("hidden");
      }
    }
  }

  function hideCapsuleReader() {
    clearReaderContentPanel();
    setRuntimeSidecarVisible(true);
    els.reader.classList.add("hidden");
    els.reader.classList.remove("is-open");
    els.reader.removeAttribute("data-capsule-id");
    if (els.readerConnector) els.readerConnector.classList.add("hidden");
    syncAppState();
  }

  function setRuntimeSidecarVisible(visible) {
    var sidecar = document.querySelector(".runtime-sidecar");
    if (sidecar) sidecar.style.visibility = visible ? "" : "hidden";
  }

  function setRuntimeSidecarAvailable(available) {
    var sidecar = document.querySelector(".runtime-sidecar");
    var machine = document.querySelector(".machine-core");
    if (sidecar) sidecar.classList.toggle("runtime-sidecar-unavailable", !available);
    if (machine) machine.classList.toggle("sidecar-collapsed", !available);
  }

  function renderUsedChips() {
    els.usedCount.textContent = String(usedCapsuleIds.length);
    if (usedCapsuleIds.length === 0) {
      els.usedCapsuleDock.innerHTML =
        '<span class="used-placeholder">' + escapeHtml(t("usedPlaceholder")) + "</span>";
      if (els.generationInputNote) els.generationInputNote.textContent = t("generationAuto");
      return;
    }
    els.usedCapsuleDock.innerHTML = "";
    usedCapsuleIds.forEach(function (id) {
      var cap = findCapsule(id);
      if (!cap) return;
      var chip = document.createElement("span");
      chip.className = "reuse-chip";
      chip.dataset.capsuleId = id;
      chip.title = cap.name;
      chip.innerHTML =
        '<span class="reuse-chip-serial">' +
        escapeHtml(getCapsuleSerial(cap)) +
        "</span>" +
        '<span class="reuse-chip-name">' +
        escapeHtml(shortName(cap.name)) +
        "</span>";
      var remove = document.createElement("button");
      remove.type = "button";
      remove.className = "reuse-chip-remove";
      remove.textContent = "×";
      remove.setAttribute("aria-label", formatText("removeCapsule", { name: cap.name }));
      remove.addEventListener("click", function () {
        usedCapsuleIds = usedCapsuleIds.filter(function (selectedId) {
          return selectedId !== id;
        });
        renderUsedChips();
      });
      chip.appendChild(remove);
      els.usedCapsuleDock.appendChild(chip);
    });
    if (els.generationInputNote) {
      els.generationInputNote.textContent = formatText("generationManual", {
        count: usedCapsuleIds.length,
      });
    }
    updateEnrichedContentToggle();
  }

  function renderGeneratedPackage(showPreview) {
    var pkg = data.generatedPackage || { folder: "Current Runtime", files: [] };
    var folder = pkg.folder || "new_project/";
    var folderParts = String(folder).split(/[/\\]/).filter(Boolean);
    var folderLabel = folderParts.length ? folderParts[folderParts.length - 1] + "/" : folder;
    var files = pkg.files || [];
    var visibleFiles = userFacingFiles(files);
    if (!visibleFiles.length) visibleFiles = files;
    var productEntry = pkg.productEntry && pkg.productEntry.path;
    if (productEntry) {
      visibleFiles = [productEntry].concat(visibleFiles.filter(function (path) { return path !== productEntry; }));
    }
    els.generatedTree.innerHTML = renderers.renderFileTree
      ? renderers.renderFileTree(folderLabel, visibleFiles, escapeHtml)
      : '<div class="folder">' + escapeHtml(folderLabel) + "</div>";
    els.generatedPreview.classList.remove("hidden");
    renderGeneratedPreview();
    if (els.generatedPackage) {
      els.generatedPackage.classList.remove("runtime-read-only");
      els.generatedPackage.classList.toggle("is-ready", !!showPreview);
    }
    var packageCount = pkg.stats && Number(pkg.stats.capsulesUsed);
    var count = Number.isInteger(packageCount) && packageCount >= 0
      ? packageCount
      : usedCapsuleIds.length;
    els.genCapsulesUsed.innerHTML =
      '<span class="meta-icon" aria-hidden="true">◫</span> ' + count + " " + t("capsulesUsed");
    if (data.lunaPack && data.lunaPack.pack_id && els.genCapsulesUsed) {
      els.genCapsulesUsed.innerHTML +=
        ' · <span class="luna-pack-note" title="' +
        escapeHtml(data.lunaPack.pack_id) +
        '">' +
        escapeHtml(t("lunaPackIndexed")) +
        "</span>";
    }
    if (data.contentAwareGenerate && data.contentAwareGenerate.enabled && els.genCapsulesUsed) {
      var sn = data.contentAwareGenerate.snippetsUsed || 0;
      els.genCapsulesUsed.innerHTML +=
        ' · <span class="content-aware-note">' +
        escapeHtml(t("contentAwarePreview")) +
        " · " +
        escapeHtml(t("snippets")) +
        " " +
        sn +
        "</span>";
    }
    if (els.workflowStatus) {
      els.workflowStatus.innerHTML =
        '<span class="meta-icon" aria-hidden="true">↳</span> ' +
        escapeHtml(t("workflow")) +
        ": " +
        escapeHtml(currentWorkflowStep(!!showPreview));
    }
    var metaLines = document.querySelectorAll(".generated-meta .meta-line");
    if (metaLines[2]) {
      metaLines[2].innerHTML =
        '<span class="meta-icon" aria-hidden="true">◎</span> ' +
        escapeHtml(t(showPreview ? "previewReady" : "previewNotReady"));
    }
    if (metaLines[3]) {
      metaLines[3].innerHTML =
        '<span class="meta-icon" aria-hidden="true">⛓</span> ' +
        escapeHtml(t(showPreview ? "traceAvailable" : "traceUnavailable"));
    }
    updatePreviewPackageActions(!!showPreview);
    applyLumoLiteRuntimeView();
  }

  function syncGeneratedPackageView() {
    if (!data) return;
    if (data.generatedPackage) {
      renderGeneratedPackage(!!lastPreviewPath);
      return;
    }
    if (els.generatedTree) els.generatedTree.innerHTML = "";
    if (els.generatedPreview) els.generatedPreview.classList.add("hidden");
    if (els.generatedPackage) els.generatedPackage.classList.remove("is-ready");
    if (els.workflowStatus) {
      els.workflowStatus.innerHTML =
        '<span class="meta-icon" aria-hidden="true">↳</span> ' +
        escapeHtml(t("workflow")) +
        ": " +
        escapeHtml(currentWorkflowStep(false));
    }
    if (els.genCapsulesUsed) {
      els.genCapsulesUsed.innerHTML =
        '<span class="meta-icon" aria-hidden="true">◫</span> 0 ' +
        escapeHtml(t("capsulesUsed"));
    }
    var metaLines = document.querySelectorAll(".generated-meta .meta-line");
    if (metaLines[2]) {
      metaLines[2].innerHTML =
        '<span class="meta-icon" aria-hidden="true">◎</span> ' +
        escapeHtml(t("previewNotReady"));
    }
    if (metaLines[3]) {
      metaLines[3].innerHTML =
        '<span class="meta-icon" aria-hidden="true">⛓</span> ' +
        escapeHtml(t("traceUnavailable"));
    }
    if (els.reweaveResponse) els.reweaveResponse.textContent = "";
    updatePreviewPackageActions(false);
  }

  function localPreviewFileUrl(relativePath) {
    if (!lastPreviewPath || relativePath !== "react_project/dist/preview.png") return "";
    var root = String(lastPreviewPath).replace(/\\/g, "/").replace(/\/$/, "");
    if (/^[A-Za-z]:\//.test(root)) root = "/" + root;
    return "file://" + encodeURI(root + "/" + relativePath);
  }

  function renderGeneratedPreview() {
    if (!els.generatedPreview) return;
    var imageUrl = lastReactPreview ? localPreviewFileUrl(lastReactPreview.image) : "";
    els.generatedPreview.classList.toggle("react-preview-ready", !!imageUrl);
    if (imageUrl) {
      els.generatedPreview.innerHTML =
        '<p class="preview-label">' + escapeHtml(t("reactRuntimeVerified")) + "</p>" +
        '<img class="react-preview-image" src="' + escapeHtml(imageUrl) + '" alt="' +
        escapeHtml(t("reactPreviewAlt")) + '">';
      return;
    }
    els.generatedPreview.innerHTML =
      '<p class="preview-label">' + escapeHtml(t("previewStatus")) + "</p>" +
      '<div class="preview-wire"><div class="wire-bar"></div><div class="wire-row"></div>' +
      '<div class="wire-row short"></div><div class="wire-block"></div></div>';
  }

  function updatePreviewPackageActions(show) {
    if (!els.previewPackageActions) return;
    var visible = !!(show && hasDesktopBridge() && canGenerateProduct());
    els.previewPackageActions.classList.toggle("hidden", !visible);
  }

  function closePreviewPackageViewer() {
    if (els.previewPackageViewer) els.previewPackageViewer.classList.add("hidden");
    previewViewerMode = "view";
  }

  function renderLumoLiteArtifacts(payload) {
    if (!els.lumoArtifactsBody) return;
    var artifacts = payload && Array.isArray(payload.artifacts) ? payload.artifacts : lumoLiteArtifacts;
    lumoLiteArtifacts = artifacts.slice();
    els.lumoArtifactsBody.innerHTML = artifactRenderers.renderArtifactList
      ? artifactRenderers.renderArtifactList(artifacts, shortExportPath, escapeHtml)
      : "";
  }

  function renderLumoLiteArtifactDetail(payload) {
    if (!els.lumoArtifactsBody || !payload || !payload.ok) return;
    els.lumoArtifactsBody.innerHTML = artifactRenderers.renderArtifactDetail
      ? artifactRenderers.renderArtifactDetail(payload, escapeHtml)
      : "";
  }

  function openLumoArtifactsPopover() {
    if (!els.lumoArtifactsPopover) return;
    els.lumoArtifactsPopover.classList.remove("hidden");
    if (hasDesktopBridge() && desktopBridge && typeof desktopBridge.list_lumo_lite_artifacts === "function") {
      bridgeCall("list_lumo_lite_artifacts").then(function (raw) {
        var result = parseBridgeJson(raw);
        if (result && result.ok) renderLumoLiteArtifacts(result);
        else renderLumoLiteArtifacts({ artifacts: lumoLiteArtifacts });
      });
      return;
    }
    renderLumoLiteArtifacts({ artifacts: lumoLiteArtifacts });
  }

  function handleLumoArtifactAction(target) {
    if (!target) return;
    var viewBtn = target.closest(".btn-artifact-view");
    var copyBtn = target.closest(".btn-artifact-copy");
    var backBtn = target.closest(".btn-artifacts-back");
    if (backBtn) {
      renderLumoLiteArtifacts({ artifacts: lumoLiteArtifacts });
      return;
    }
    if (copyBtn) {
      var path = copyBtn.getAttribute("data-artifact-path") || "";
      if (navigator.clipboard && path) navigator.clipboard.writeText(path);
      if (els.reweaveResponse) els.reweaveResponse.textContent = t("artifactCopied");
      return;
    }
    if (viewBtn && hasDesktopBridge()) {
      bridgeCall("get_lumo_lite_artifact", viewBtn.getAttribute("data-artifact-id") || "").then(function (raw) {
        var result = parseBridgeJson(raw);
        if (result && result.ok) renderLumoLiteArtifactDetail(result);
      });
      return;
    }
  }

  function shortExportPath(path) {
    if (!path) return "";
    var parts = String(path).split(/[/\\]/);
    if (parts.length <= 2) return path;
    return "…/" + parts.slice(-2).join("/");
  }

  function openPreviewPackageViewer(title) {
    if (!els.previewPackageViewer) return;
    if (els.previewViewerTitle) els.previewViewerTitle.textContent = title || "Preview package";
    els.previewPackageViewer.classList.remove("hidden");
  }

  function renderSafetyBadges(safety) {
    safety = safety || {};
    var badges = [];
    if (safety.source_folder_read_at_view_time === false) badges.push("no source read");
    if (safety.source_folder_written === false) badges.push("no source write");
    if (safety.llm_called === false) badges.push("no LLM");
    if (safety.dispatch_called === false) badges.push("no dispatch");
    return badges.map(function (b) {
      return '<span class="preview-safety-badge">' + escapeHtml(b) + "</span>";
    }).join("");
  }

  function renderPreviewViewerPayload(payload) {
    if (!els.previewViewerBody || !payload || !payload.ok) return;
    previewViewerMode = "view";
    var pkg = payload.package || {};
    var cag = (payload.provenance && payload.provenance.content_aware_generate) || {};
    var luna = (payload.provenance && payload.provenance.luna) || {};
    var snippets = payload.snippetsUsed || {};
    var exports = payload.exports || [];
    var html = "";
    html += '<p class="preview-viewer-mode"><strong>Mode:</strong> ' + escapeHtml(pkg.mode || "metadata_only") + "</p>";
    if (payload.previewAcceptance) {
      html += '<p class="preview-viewer-meta">' + escapeHtml(previewAcceptanceText(payload.previewAcceptance)) + "</p>";
    }
    if (pkg.created_at) {
      html += '<p class="preview-viewer-meta">' + escapeHtml(pkg.created_at) + "</p>";
    }
    html += '<p class="preview-viewer-label">Files</p><ul class="preview-viewer-list">';
    (pkg.files || []).forEach(function (f) {
      html += "<li>" + escapeHtml(f) + "</li>";
    });
    html += "</ul>";
    html += '<p class="preview-viewer-label">Capsules used (' + (payload.capsulesUsed || []).length + ")</p>";
    html += '<ul class="preview-viewer-list">';
    (payload.capsulesUsed || []).slice(0, 6).forEach(function (cap) {
      html += "<li>" + escapeHtml(cap.name || cap.capsule_id || cap.id || "capsule") + "</li>";
    });
    html += "</ul>";
    html += '<p class="preview-viewer-label">Snippets used</p>';
    if (snippets.enabled) {
      html += '<p class="preview-viewer-meta">' + (snippets.count || 0) + " manifest entries</p>";
      html += '<ul class="preview-viewer-list">';
      (snippets.items || []).slice(0, 4).forEach(function (sn) {
        html += "<li>" + escapeHtml((sn.relative_path || "file") + " · " + (sn.excerpt_chars || 0) + " chars") + "</li>";
      });
      html += "</ul>";
    } else {
      html += '<p class="preview-viewer-meta">Not used</p>';
    }
    html += '<p class="preview-viewer-label">Provenance</p>';
    html += '<p class="preview-viewer-meta">Content-aware: ' + (cag.enabled ? "enabled" : "off") + "</p>";
    if (luna && luna.pack_id) {
      html += '<p class="preview-viewer-meta">Luna pack: ' + escapeHtml(String(luna.pack_id)) + "</p>";
    } else if (luna && luna.ok === false) {
      html += '<p class="preview-viewer-meta">Luna pack: failed</p>';
    } else {
      html += '<p class="preview-viewer-meta">Luna pack: —</p>';
    }
    if (exports.length) {
      html += '<p class="preview-viewer-label">Exports</p>';
      html += '<ul class="preview-viewer-list">';
      exports.slice(0, 3).forEach(function (ex) {
        html +=
          "<li>" +
          escapeHtml((ex.mode || "export") + " · " + shortExportPath(ex.export_path)) +
          "</li>";
      });
      html += "</ul>";
    }
    html += '<div class="preview-safety-badges">' + renderSafetyBadges(payload.safety) + "</div>";
    els.previewViewerBody.innerHTML = html;
  }

  function renderPreviewCompareResult(result) {
    if (!els.previewViewerBody || !result || !result.ok) return;
    previewViewerMode = "compare";
    var diff = result.diff || {};
    var html = "";
    html += '<p class="preview-viewer-mode"><strong>Compare</strong></p>';
    html += '<p class="preview-viewer-meta">' + escapeHtml(result.left.id) + " → " + escapeHtml(result.right.id) + "</p>";
    html += '<p class="preview-viewer-meta">' + escapeHtml(result.left.mode) + " → " + escapeHtml(result.right.mode) + "</p>";
    if ((diff.files_added || []).length) {
      html += '<p class="preview-viewer-label">Files added</p><ul class="preview-viewer-list">';
      diff.files_added.forEach(function (f) {
        html += "<li>" + escapeHtml(f) + "</li>";
      });
      html += "</ul>";
    }
    if ((diff.files_removed || []).length) {
      html += '<p class="preview-viewer-label">Files removed</p><ul class="preview-viewer-list">';
      diff.files_removed.forEach(function (f) {
        html += "<li>" + escapeHtml(f) + "</li>";
      });
      html += "</ul>";
    }
    if (diff.content_aware_changed) {
      html += '<p class="preview-viewer-meta content-aware-note">Content-aware changed</p>';
    }
    html += '<p class="preview-viewer-meta">Snippets Δ ' + (diff.snippets_used_delta || 0) + " · Capsules Δ " + (diff.capsules_used_delta || 0) + "</p>";
    if (diff.luna_pack_changed) {
      html += '<p class="preview-viewer-meta">Luna pack reference changed</p>';
    }
    html += '<p class="preview-viewer-meta">Metadata compare only — no code diff</p>';
    els.previewViewerBody.innerHTML = html;
  }

  function handleViewPreviewPackage() {
    if (!hasDesktopBridge()) return;
    bridgeCall("open_generated_product").then(function (raw) {
      var opened = parseBridgeJson(raw);
      if ((!opened || !opened.ok) && els.reweaveResponse) {
        els.reweaveResponse.textContent = t("noPreviewPackage");
      }
    });
  }

  function handleComparePreviewPackages() {
    if (!hasDesktopBridge()) return;
    bridgeCall("compare_preview_packages", JSON.stringify({})).then(function (raw) {
      var result = parseBridgeJson(raw);
      if (!result || !result.ok) {
        if (els.reweaveResponse) {
          els.reweaveResponse.textContent = (result && result.error) || t("noPreviousPackage");
        }
        return;
      }
      renderPreviewCompareResult(result);
      openPreviewPackageViewer("Compare last");
    });
  }

  function renderHistory(extra) {
    var list = $("history-list");
    list.innerHTML = "";
    var items = (data.history || []).slice();
    if (extra) items.unshift(extra);
    if (items.length === 0) {
      var empty = document.createElement("li");
      empty.className = "history-empty";
      empty.textContent = isLumoLiteReadOnly() ? t("noHistoryReadOnly") : t("noHistory");
      list.appendChild(empty);
      return;
    }
    items.forEach(function (item) {
      var li = document.createElement("li");
      li.innerHTML =
        '<span class="hist-title">' + escapeHtml(item.title) + "</span>" +
        '<span class="hist-meta">' +
        escapeHtml(formatText("historyMeta", { count: item.capsulesUsed, note: item.note })) +
        "</span>";
      list.appendChild(li);
    });
  }

  function renderSources() {
    var count = $("sources-count");
    var list = $("sources-list");
    if (!count || !list) return;
    count.textContent = String((data.sourceBoxes || []).length);
    list.innerHTML = "";
    (data.sourceBoxes || []).forEach(function (src) {
      var li = document.createElement("li");
      var left = document.createElement("span");
      left.textContent = src.label;

      var right = document.createElement("span");
      right.className = "source-status";

      if (hasDesktopBridge()) {
        if (verifyingSourceIds[src.id] || previewingSourceIds[src.id] || reviewingSourceIds[src.id]) {
          right.textContent = sourceScanLabel(src);
        } else {
          var lunaReuse = data.lunaReuseBySource && data.lunaReuseBySource[src.id];
          var verification = data.verificationBySource && data.verificationBySource[src.id];
          if (lunaReuse && lunaReuse.count > 0 && !verification && !isLumoLiteReadOnly()) {
            var verifyBtn = document.createElement("button");
            verifyBtn.type = "button";
            verifyBtn.className = "btn-ghost btn-source-scan";
            verifyBtn.textContent = t("verify");
            verifyBtn.addEventListener("click", function (e) {
              e.preventDefault();
              e.stopPropagation();
              handleVerifySource(src.id);
            });
            right.appendChild(verifyBtn);
          } else if (verification) {
            var governance = data.governancePreviewBySource && data.governancePreviewBySource[src.id];
            if (!governance && !isLumoLiteReadOnly()) {
              var previewBtn = document.createElement("button");
              previewBtn.type = "button";
              previewBtn.className = "btn-ghost btn-source-scan";
              previewBtn.textContent = t("preview");
              previewBtn.addEventListener("click", function (e) {
                e.preventDefault();
                e.stopPropagation();
                handleGovernancePreview(src.id);
              });
              right.appendChild(previewBtn);
            } else {
              var reviewQueue = data.reviewQueueBySource && data.reviewQueueBySource[src.id];
              if (!reviewQueue && !isLumoLiteReadOnly()) {
                var reviewBtn = document.createElement("button");
                reviewBtn.type = "button";
                reviewBtn.className = "btn-ghost btn-source-scan";
                reviewBtn.textContent = t("review");
                reviewBtn.addEventListener("click", function (e) {
                  e.preventDefault();
                  e.stopPropagation();
                  handleCreateReviewQueue(src.id);
                });
                right.appendChild(reviewBtn);
              } else {
                var s = reviewQueue.summary || {};
                var promotedN = 0;
                if (Array.isArray(reviewQueue.items)) {
                  reviewQueue.items.forEach(function (item) {
                    if (item && item.promoted) promotedN += 1;
                  });
                }
                if (data.promotedCountBySource && data.promotedCountBySource[src.id]) {
                  promotedN = Math.max(promotedN, data.promotedCountBySource[src.id]);
                }
                right.textContent =
                  t("review") +
                  ": " +
                  t("pending") +
                  " " +
                  (s.pending || 0) +
                  " / " +
                  t("approved") +
                  " " +
                  (s.approved || 0) +
                  " / " +
                  t("rejected") +
                  " " +
                  (s.rejected || 0) +
                  " / " +
                  t("deferred") +
                  " " +
                  (s.deferred || 0) +
                  (promotedN ? " · " + t("promoted") + " " + promotedN : "");
                appendReviewMiniPanel(li, src.id, reviewQueue);
              }
            }
          } else {
            right.textContent = sourceScanLabel(src);
          }
        }
      } else {
        right.textContent = src.status || t("bound");
      }

      li.appendChild(left);
      li.appendChild(right);
      list.appendChild(li);
    });
  }

  function bindMainEvents() {
    if (mainEventsBound) return;
    mainEventsBound = true;
    capsuleWarehouseScene.bind();
    productPlanScene.bind();
    targetIntegration.bind();

    var compatTargetNav = $("btn-compat-target-nav");
    if (compatTargetNav) {
      compatTargetNav.addEventListener("click", function () {
        var targetEntry = $("btn-open-target");
        if (targetEntry && !targetEntry.disabled) targetEntry.click();
      });
    }
    var compatWarehouseNav = $("btn-compat-warehouse-nav");
    if (compatWarehouseNav) {
      compatWarehouseNav.addEventListener("click", function () {
        capsuleWarehouseScene.open(null);
      });
    }
    var compatIngestionNav = $("btn-compat-ingestion-nav");
    if (compatIngestionNav) {
      compatIngestionNav.addEventListener("click", function () {
        openIngestionScene("product", null);
      });
    }

    $("btn-generate").addEventListener("click", runGenerate);
    var enrichedCheckbox = $("use-enriched-content");
    if (enrichedCheckbox) {
      enrichedCheckbox.addEventListener("change", function () {
        useEnrichedContentPreview = !!enrichedCheckbox.checked;
      });
    }
    els.taskInput.addEventListener("keydown", function (e) {
      if (e.key === "Enter") {
        e.preventDefault();
        runGenerate();
      }
    });

    $("btn-use-in-task").addEventListener("click", function () {
      if (!selectedCapsuleId || usedCapsuleIds.indexOf(selectedCapsuleId) !== -1) return;
      var cap = findCapsule(selectedCapsuleId);
      if (!cap) return;
      if (!isCapsuleGenerateEligible(cap)) {
        els.reweaveResponse.textContent = t("capsuleReadOnlyMessage");
        return;
      }
      var capEl = ensureCapsuleElement(selectedCapsuleId);
      if (!capEl) return;
      setAppState("invoking");
      capEl.classList.add("scan-match");
      emitReuseTrace(capEl, function () {
        if (capEl.parentNode) capEl.classList.remove("scan-match");
        dockCapsule(selectedCapsuleId, true);
        syncAppState();
      });
    });

    $("reader-close").addEventListener("click", hideCapsuleReader);

    $("btn-history").addEventListener("click", function (e) {
      e.stopPropagation();
      togglePopover("history");
    });

    $("btn-sources").addEventListener("click", function (e) {
      e.stopPropagation();
      togglePopover("sources");
    });
    if (els.btnLumoArtifacts) {
      els.btnLumoArtifacts.addEventListener("click", function (e) {
        e.stopPropagation();
        togglePopover("lumo-artifacts");
      });
    }
    if (els.lumoArtifactsBody) {
      els.lumoArtifactsBody.addEventListener("click", function (e) {
        handleLumoArtifactAction(e.target);
      });
    }
    bindIngestionManagementEvents();

    document.querySelectorAll(".popover-close[data-close]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        closeAllPopovers();
      });
    });

    els.backdrop.addEventListener("click", closeAllPopovers);

    document.addEventListener("click", function (e) {
      if (
        !els.reader.classList.contains("hidden") &&
        !els.reader.contains(e.target) &&
        !e.target.closest(".capsule-cartridge")
      ) {
        hideCapsuleReader();
      }
    });

    document.addEventListener("keydown", function (e) {
      if (e.key !== "Escape") return;
      if (els.reader && !els.reader.classList.contains("hidden")) hideCapsuleReader();
      closeAllPopovers();
    });

    syncSourceControls();

    var btnViewPackage = $("btn-view-package");
    if (btnViewPackage) {
      btnViewPackage.addEventListener("click", function (e) {
        e.preventDefault();
        handleViewPreviewPackage();
      });
    }
    var btnCompareLast = $("btn-compare-last");
    if (btnCompareLast) {
      btnCompareLast.addEventListener("click", function (e) {
        e.preventDefault();
        handleComparePreviewPackages();
      });
    }
    var previewViewerClose = $("preview-viewer-close");
    if (previewViewerClose) {
      previewViewerClose.addEventListener("click", function (e) {
        e.preventDefault();
        closePreviewPackageViewer();
      });
    }
    var langBtn = $("btn-lang");
    if (langBtn) langBtn.addEventListener("click", toggleLocale);

    window.addEventListener("resize", function () {
      if (selectedCapsuleId && !els.reader.classList.contains("hidden")) {
        positionReaderNearCapsule(selectedCapsuleId);
      }
    });
  }

  function togglePopover(which) {
    var historyOpen = !els.historyPopover.classList.contains("hidden");
    var sourcesOpen = !els.sourcesPopover.classList.contains("hidden");
    var artifactsOpen = els.lumoArtifactsPopover && !els.lumoArtifactsPopover.classList.contains("hidden");
    if (els.reader && !els.reader.classList.contains("hidden")) hideCapsuleReader();
    closeAllPopovers();
    if (which === "history" && !historyOpen) {
      els.historyPopover.classList.remove("hidden");
      els.backdrop.classList.remove("hidden");
      $("btn-history").setAttribute("aria-expanded", "true");
    } else if (which === "sources" && !sourcesOpen) {
      els.sourcesPopover.classList.remove("hidden");
      els.backdrop.classList.remove("hidden");
      $("btn-sources").setAttribute("aria-expanded", "true");
    } else if (which === "lumo-artifacts" && !artifactsOpen) {
      openLumoArtifactsPopover();
      els.backdrop.classList.remove("hidden");
      if (els.btnLumoArtifacts) els.btnLumoArtifacts.setAttribute("aria-expanded", "true");
    }
  }

  function closeAllPopovers() {
    els.historyPopover.classList.add("hidden");
    els.sourcesPopover.classList.add("hidden");
    if (els.lumoArtifactsPopover) els.lumoArtifactsPopover.classList.add("hidden");
    els.backdrop.classList.add("hidden");
    $("btn-history").setAttribute("aria-expanded", "false");
    $("btn-sources").setAttribute("aria-expanded", "false");
    if (els.btnLumoArtifacts) els.btnLumoArtifacts.setAttribute("aria-expanded", "false");
  }

  function ensureCapsuleElement(id) {
    var chipEl = els.capsuleStrip.querySelector('[data-capsule-id="' + id + '"]');
    if (chipEl) return chipEl;

    var cap = findCapsule(id);
    if (!cap) return null;

    var visible = getVisibleCapsules();
    var onScreen = visible.some(function (c) {
      return c.id === id;
    });
    if (!onScreen) return null;

    return els.capsuleStrip.querySelector('[data-capsule-id="' + id + '"]');
  }

  function runGenerate() {
    if (isGenerating) return;
    if (!canGenerateProduct()) {
      els.reweaveResponse.textContent = t("runtimeReadOnlyMessage");
      return;
    }
    if (usedCapsuleIds.length === 0) {
      els.reweaveResponse.textContent = t("generationAuto");
      return;
    }
    var selectionError = formalSelectionError(usedCapsuleIds, true);
    if (selectionError) {
      els.reweaveResponse.textContent = t(selectionError);
      return;
    }
    var text = els.taskInput.value.trim() || data.sampleTask || t("newTask");
    usedCapsuleSelectionMode = "manual";
    var ids = usedCapsuleIds.slice();

    notifyDesktopGenerate(text, ids);

    isGenerating = true;
    setAppState("invoking");
    els.btnGenerate.disabled = true;
    usedCapsuleIds = [];
    renderUsedChips();
    els.reweaveResponse.textContent = t("selecting");
    if (els.taskBay) els.taskBay.classList.add("is-invoking");

    var dockFrame = document.querySelector(".capsule-window-frame");
    if (dockFrame) dockFrame.classList.add("dock-scanning");

    function finishBatch() {
      renderCapsuleStrip();
      if (dockFrame) dockFrame.classList.remove("dock-scanning");
      if (els.taskBay) els.taskBay.classList.remove("is-invoking");
      finishGenerate(text, usedCapsuleIds.length);
    }

    function processNext(index) {
      if (index >= ids.length) {
        finishBatch();
        return;
      }
      invokeCapsule(ids[index], function () {
        setTimeout(function () {
          processNext(index + 1);
        }, 120);
      });
    }

    setTimeout(function () {
      processNext(0);
    }, 420);
  }

  function invokeCapsule(id, done) {
    var cap = findCapsule(id);
    if (!cap) {
      done();
      return;
    }

    var chipEl = ensureCapsuleElement(id);
    if (!chipEl) {
      dockCapsule(id, false);
      done();
      return;
    }

    chipEl.classList.add("scan-match");
    setTimeout(function () {
      var liveEl = els.capsuleStrip.querySelector('[data-capsule-id="' + id + '"]') || chipEl;
      emitReuseTrace(liveEl, function () {
        if (liveEl.parentNode) liveEl.classList.remove("scan-match");
        dockCapsule(id, false);
        done();
      });
    }, 200);
  }

  function emitReuseTrace(fromEl, callback) {
    if (prefersReducedMotion()) {
      callback();
      return;
    }
    var fromRect = fromEl.getBoundingClientRect();
    var dockRect = els.usedCapsuleDock.getBoundingClientRect();
    var slotIndex = usedCapsuleIds.length;
    var targetX = dockRect.left + 10 + slotIndex * 72;
    var targetY = dockRect.top + dockRect.height * 0.5;
    var startX = fromRect.left + fromRect.width * 0.5;
    var startY = fromRect.bottom - 2;
    var svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    var path = document.createElementNS(svg.namespaceURI, "path");
    var midY = Math.min(startY + 36, targetY);
    svg.setAttribute("class", "reuse-trace-svg");
    path.setAttribute("pathLength", "1");
    path.setAttribute(
      "d",
      "M" + startX + " " + startY + " C " + startX + " " + midY + ", " + targetX + " " + midY + ", " + targetX + " " + targetY
    );
    svg.appendChild(path);
    document.body.appendChild(svg);

    setTimeout(function () {
      svg.remove();
      callback();
    }, 300);
  }

  function dockCapsule(id, single) {
    var cap = findCapsule(id);
    if (!isCapsuleGenerateEligible(cap)) {
      return false;
    }
    var nextIds = usedCapsuleIds.slice();
    if (nextIds.indexOf(id) === -1) {
      nextIds.push(id);
    }
    var selectionError = formalSelectionError(nextIds, false);
    if (selectionError) {
      els.reweaveResponse.textContent = t(selectionError);
      return false;
    }
    usedCapsuleIds = nextIds;
    usedCapsuleSelectionMode = "manual";
    renderUsedChips();
    if (single) {
      var cap = findCapsule(id);
      if (cap) {
        els.reweaveResponse.textContent =
          getCapsuleSerial(cap) +
          " " +
          cap.name +
          " " +
          t("docked") +
          " " +
          t("generationManual").replace("{count}", String(usedCapsuleIds.length));
      }
    }
    return true;
  }

  function formalSelectionError(ids, requireDomRole) {
    var capsules = ids.map(findCapsule).filter(Boolean);
    var formalCapsules = capsules.filter(function (cap) {
      return cap.formal_version === true;
    });
    if (formalCapsules.length === 0) return "";
    if (
      capsules.length !== ids.length ||
      formalCapsules.length !== capsules.length ||
      formalCapsules.length > 3
    ) {
      return "formalSelectionInvalid";
    }
    var capabilityKey = "";
    var seenKinds = {};
    for (var i = 0; i < formalCapsules.length; i += 1) {
      var current = formalCapsules[i];
      var currentCapability = Array.isArray(current.tags) ? String(current.tags[0] || "") : "";
      var kind = String(current.type || "");
      if (
        !currentCapability ||
        ["presentation", "interaction", "computation"].indexOf(kind) === -1 ||
        (capabilityKey && currentCapability !== capabilityKey) ||
        seenKinds[kind]
      ) {
        return "formalSelectionInvalid";
      }
      capabilityKey = currentCapability;
      seenKinds[kind] = true;
    }
    if (requireDomRole && !seenKinds.presentation && !seenKinds.interaction) {
      return "formalSelectionNeedsDomRole";
    }
    return "";
  }

  function finishGenerate(taskText, count, localeOnly) {
    function blockReadyRender(message) {
      isGenerating = false;
      pendingGeneratePromise = null;
      if (els.taskBay) els.taskBay.classList.remove("is-invoking");
      if (isLumoLiteReadOnly()) applyLumoLiteRuntimeView();
      if (els.btnGenerate) els.btnGenerate.disabled = !canGenerateProduct();
      if (els.reweaveResponse) els.reweaveResponse.textContent = message;
      setAppState("error");
    }

    function finalize() {
      renderGeneratedPackage(true);
      if (els.generatedPackage && !prefersReducedMotion()) {
        els.generatedPackage.classList.remove("result-reveal");
        void els.generatedPackage.offsetWidth;
        els.generatedPackage.classList.add("result-reveal");
        setTimeout(function () {
          els.generatedPackage.classList.remove("result-reveal");
        }, 300);
      }
      els.reweaveResponse.textContent = previewAcceptanceText(lastPreviewAcceptance) || formatText("readyResponse", { count: count });
      if (!localeOnly) {
        renderHistory({
          title: taskText.length > 28 ? taskText.slice(0, 28) + "…" : taskText,
          capsulesUsed: count,
          note: lastPreviewPath ? t("localPreview") : t("previewPackage"),
        });
      }
      isGenerating = false;
      els.btnGenerate.disabled = false;
      setAppState("ready");
      pendingGeneratePromise = null;
    }

    if (pendingGeneratePromise) {
      pendingGeneratePromise.then(function (raw) {
        var result = parseBridgeJson(raw);
        if (!result || result.ok === false) {
          blockReadyRender(
            result && result.previewAcceptance
              ? previewAcceptanceText(result.previewAcceptance)
              : t("generationFailed")
          );
          return;
        }
        applyGenerateResult(result);
        count = usedCapsuleIds.length;
        finalize();
      }).catch(function () {
        blockReadyRender(t("generationFailed"));
      });
      return;
    }
    if (!canGenerateProduct()) {
      blockReadyRender(t("runtimeReadOnlyMessage"));
      return;
    }
    finalize();
  }

  function escapeHtml(str) {
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function getIntegrationState() {
    return {
      appState: appState,
      selectedCapsuleId: selectedCapsuleId,
      usedCapsuleIds: usedCapsuleIds.slice(),
      taskText: els.taskInput ? els.taskInput.value : "",
      isGenerating: isGenerating,
      bridge: {
        available: hasDesktopBridge(),
        ready: bridgeReady,
        shell: desktopShellState
          ? {
              canGenerateProduct: desktopShellState.canGenerateProduct === true,
              canPlanProduct: desktopShellState.canPlanProduct === true,
              planningWorkspaceCount:
                desktopShellState.productPlanning &&
                Array.isArray(desktopShellState.productPlanning.workspaces)
                  ? desktopShellState.productPlanning.workspaces.length
                  : 0,
            }
          : null,
        previewAvailable: !!lastPreviewPath,
      },
      warehouse: capsuleWarehouseScene.getState(),
      productPlan: productPlanScene.getState(),
      target: targetIntegration.getState(),
    };
  }

  window.ReweavePrototype = {
    getState: getIntegrationState,
    setAppState: setAppState,
  };

  function boot() {
    initWelcome();
    loadMockData(function (err) {
      if (err) {
        console.error(err);
        $("btn-select-folder").textContent = t("loadFailed");
        return;
      }
      applyLocale();
      initDesktopBridge(function () {
        var params = new URLSearchParams(window.location.search);
        var compatibility = params.get("main") === "1";
        var skipWelcome =
          compatibility ||
          !!(desktopShellState && desktopShellState.skipWelcome && !isLumoLiteReadOnly());
        if (skipWelcome) {
          initMain({ compatibility: compatibility });
        } else {
          syncWelcomeSourceBoxMode();
        }
      });
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
