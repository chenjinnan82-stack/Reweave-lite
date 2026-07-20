(function () {
  "use strict";

  var FIXTURE_ID = "reweave_product_plan_fixture.v1";
  var PROTOTYPE_ID = "product-plan-prototype-001";
  var SECTION_FIXTURES = [
    { id: "frontend", title: "前端", subtitle: "工作台与审阅体验", summary: "页面结构、键盘路径与只读 Review。", gap: "真实页面候选尚未生成" },
    { id: "backend", title: "后端", subtitle: "服务与权限边界", summary: "服务职责、授权边界与失败关闭。", gap: "真实 API 候选尚未生成" },
    { id: "data", title: "数据", subtitle: "模型与生命周期", summary: "数据模型、迁移与保留策略。", gap: "真实数据方案尚未生成" },
    { id: "infrastructure", title: "基础设施", subtitle: "运行与验证", summary: "运行环境、测试与交付门。", gap: "真实运行方案尚未生成" },
  ];

  function create(host) {
    var state = {
      active: false,
      fixtureVisible: false,
      goal: "",
      view: "overview",
      sectionId: "",
      developerMode: false,
      expanded: { frontend: true, backend: false, data: false, infrastructure: false },
      overviewScroll: 0,
      reviewScroll: 0,
      overviewFocusId: "product-plan-goal",
      reviewFocusId: "",
      warehousePending: false,
    };
    var bound = false;
    var els = {};

    function $(id) { return document.getElementById(id); }

    function formalCapsules() {
      var capsules = host.getCapsules ? host.getCapsules() : [];
      return (Array.isArray(capsules) ? capsules : []).filter(function (cap) {
        return cap && cap.formal_version === true && String(cap.status || "active") === "active";
      }).slice().sort(function (left, right) {
        return capsuleId(left).localeCompare(capsuleId(right));
      });
    }

    function capsuleId(cap) {
      return String((cap && (cap.capsule_id || cap.id)) || "");
    }

    function capsuleName(cap) {
      return String((cap && cap.name) || capsuleId(cap) || "原型候选");
    }

    function sectionById(id) {
      return SECTION_FIXTURES.find(function (section) { return section.id === id; }) || null;
    }

    function capsuleForSection(sectionId) {
      var capsules = formalCapsules();
      var index = SECTION_FIXTURES.findIndex(function (section) { return section.id === sectionId; });
      return capsules.length && index >= 0 ? capsules[index % capsules.length] : null;
    }

    function setText(id, value) {
      var element = $(id);
      if (element) element.textContent = value;
    }

    function copy() {
      var zh = !host.getLocale || host.getLocale() === "zh";
      return zh ? {
        entry: "产品计划原型",
        back: "返回独立产品",
        kicker: "只读低保真原型",
        title: "产品计划总览",
        goalLabel: "产品目标",
        goalPlaceholder: "描述希望创建的产品",
        submit: "生成原型计划",
        prototype: "原型数据 · 不代表真实匹配或验证事实",
        openReview: "进入只读 Review",
        match: "匹配胶囊",
        gap: "能力缺口",
        reviewBack: "返回计划总览",
        candidateEmpty: "真实候选尚未生成",
        developer: "开发者模式",
        warehouseReturn: "返回计划 Review",
      } : {
        entry: "Product plan prototype",
        back: "Back to standalone product",
        kicker: "READ-ONLY LOW-FIDELITY PROTOTYPE",
        title: "Product plan overview",
        goalLabel: "Product goal",
        goalPlaceholder: "Describe the product you want to create",
        submit: "Build prototype plan",
        prototype: "Prototype data · not a real match or validation fact",
        openReview: "Open read-only Review",
        match: "Matched capsule",
        gap: "Capability gap",
        reviewBack: "Back to plan overview",
        candidateEmpty: "Real candidates have not been generated",
        developer: "Developer mode",
        warehouseReturn: "Back to plan Review",
      };
    }

    function renderSections() {
      els.sections.textContent = "";
      if (!state.fixtureVisible) return;
      SECTION_FIXTURES.forEach(function (section) {
        var capsule = capsuleForSection(section.id);
        var details = document.createElement("details");
        details.className = "product-plan-section";
        details.dataset.sectionId = section.id;
        details.open = state.expanded[section.id] === true;

        var summary = document.createElement("summary");
        var heading = document.createElement("span");
        heading.className = "product-plan-section-heading";
        heading.textContent = section.title + " · " + section.subtitle;
        var counts = document.createElement("span");
        counts.className = "product-plan-section-counts";
        counts.textContent = "1 " + copy().match + " · 1 " + copy().gap;
        summary.appendChild(heading);
        summary.appendChild(counts);
        details.appendChild(summary);

        var body = document.createElement("div");
        body.className = "product-plan-section-body";
        var prototype = document.createElement("p");
        prototype.className = "prototype-note";
        prototype.textContent = copy().prototype;
        var items = document.createElement("div");
        items.className = "product-plan-items";
        var match = document.createElement("span");
        match.className = "product-plan-pill is-capsule";
        match.textContent = copy().match + " · " + capsuleName(capsule);
        var gap = document.createElement("span");
        gap.className = "product-plan-pill is-gap";
        gap.textContent = copy().gap + " · " + section.gap;
        var open = document.createElement("button");
        open.type = "button";
        open.id = "btn-open-product-review-" + section.id;
        open.className = "btn-ghost product-plan-open-review";
        open.dataset.openReview = section.id;
        open.textContent = copy().openReview;
        items.appendChild(match);
        items.appendChild(gap);
        body.appendChild(prototype);
        body.appendChild(items);
        body.appendChild(open);
        details.appendChild(body);
        details.addEventListener("toggle", function () { state.expanded[section.id] = details.open; });
        els.sections.appendChild(details);
      });
    }

    function developerProjection(section, capsule) {
      return {
        fixture_id: FIXTURE_ID,
        prototype_id: state.fixtureVisible ? PROTOTYPE_ID : null,
        scope: "prototype_only",
        scene: state.view,
        section_id: section ? section.id : null,
        fixture_label_visible: state.fixtureVisible,
        candidate: {
          capsule_id: capsule ? capsuleId(capsule) : null,
          evidence_status: "prototype_navigation_only",
          formal_match_claimed: false,
          validation_claimed: false,
        },
        calls: { bridge: 0, network: 0, model: 0 },
        writes: 0,
      };
    }

    function renderReview() {
      var section = sectionById(state.sectionId);
      var capsule = section ? capsuleForSection(section.id) : null;
      if (!section) return;
      setText("product-review-path", copy().title + " / " + section.title);
      setText("product-review-title", section.title + " · " + section.subtitle);
      setText("product-review-summary", section.summary);
      setText("product-review-prototype-note", copy().prototype);
      setText("product-review-empty", copy().candidateEmpty);
      els.reviewCapsules.textContent = "";
      var capsuleButton = document.createElement("button");
      capsuleButton.type = "button";
      capsuleButton.id = "product-review-capsule-" + section.id;
      capsuleButton.className = "product-plan-pill is-capsule product-review-capsule";
      capsuleButton.textContent = copy().match + " · " + capsuleName(capsule);
      capsuleButton.disabled = !capsule;
      if (capsule) capsuleButton.dataset.capsuleId = capsuleId(capsule);
      var gap = document.createElement("span");
      gap.className = "product-plan-pill is-gap";
      gap.textContent = copy().gap + " · " + section.gap;
      els.reviewCapsules.appendChild(capsuleButton);
      els.reviewCapsules.appendChild(gap);
      els.developerEvidence.textContent = JSON.stringify(developerProjection(section, capsule), null, 2);
    }

    function render() {
      var c = copy();
      setText("btn-open-product-plan", c.entry);
      setText("btn-product-plan-back", c.back);
      setText("product-plan-kicker", c.kicker);
      setText("product-plan-title", c.title);
      setText("product-plan-goal-label", c.goalLabel);
      setText("btn-submit-product-goal", c.submit);
      setText("product-plan-prototype-note", c.prototype);
      setText("btn-product-review-back", c.reviewBack);
      setText("product-plan-developer-label", c.developer);
      setText("btn-warehouse-return-product-plan", c.warehouseReturn);
      if (els.goal) els.goal.placeholder = c.goalPlaceholder;
      els.overview.classList.toggle("hidden", state.view !== "overview");
      els.review.classList.toggle("hidden", state.view !== "review");
      els.fixture.classList.toggle("hidden", !state.fixtureVisible);
      els.screen.classList.toggle("developer-mode", state.developerMode);
      els.developerMode.checked = state.developerMode;
      renderSections();
      if (state.view === "review") renderReview();
    }

    function enterScene() {
      state.active = true;
      state.view = "overview";
      host.showScreen("screen-product-plan");
      render();
      window.setTimeout(function () { (state.fixtureVisible ? els.sections : els.goal).focus(); }, 0);
    }

    function leaveScene() {
      state.active = false;
      host.showScreen("screen-main");
      window.setTimeout(function () { els.entry.focus(); }, 0);
    }

    function submitGoal() {
      var goal = String(els.goal.value || "").trim();
      if (!goal) { els.goal.focus(); return; }
      state.goal = goal;
      state.fixtureVisible = true;
      state.view = "overview";
      render();
      window.setTimeout(function () { $("btn-open-product-review-frontend").focus(); }, 0);
    }

    function openReview(sectionId) {
      var section = sectionById(sectionId);
      if (!section) return;
      state.overviewScroll = els.stage.scrollTop;
      state.overviewFocusId = document.activeElement && document.activeElement.id || "btn-open-product-review-" + sectionId;
      state.view = "review";
      state.sectionId = sectionId;
      render();
      els.stage.scrollTop = state.reviewScroll;
      window.setTimeout(function () { $("product-review-title").focus(); }, 0);
    }

    function closeReview() {
      state.reviewScroll = els.stage.scrollTop;
      state.view = "overview";
      render();
      window.setTimeout(function () {
        ($(state.overviewFocusId) || els.sections).focus();
        els.stage.scrollTop = state.overviewScroll;
      }, 0);
    }

    function openWarehouse(capsuleIdValue) {
      if (!capsuleIdValue) return;
      state.reviewScroll = els.stage.scrollTop;
      state.reviewFocusId = document.activeElement && document.activeElement.id || "product-review-title";
      state.warehousePending = true;
      els.warehouseReturn.classList.remove("hidden");
      if (host.openWarehouse) host.openWarehouse(capsuleIdValue);
    }

    function consumeWarehouseReturn() {
      if (!state.warehousePending) return false;
      state.warehousePending = false;
      state.active = true;
      state.view = "review";
      els.warehouseReturn.classList.add("hidden");
      render();
      window.setTimeout(function () {
        ($(state.reviewFocusId) || $("product-review-title")).focus();
        els.stage.scrollTop = state.reviewScroll;
      }, 0);
      return true;
    }

    function returnFromWarehouse() {
      var back = $("btn-warehouse-scene-back");
      var warehouseState = host.getWarehouseState ? host.getWarehouseState() : null;
      for (var count = 0; back && warehouseState && warehouseState.active && count < 3; count += 1) {
        back.click();
        warehouseState = host.getWarehouseState();
      }
    }

    function cacheElements() {
      els.entry = $("btn-open-product-plan");
      els.screen = $("screen-product-plan");
      els.stage = $("product-plan-stage");
      els.overview = $("product-plan-overview");
      els.review = $("product-plan-review");
      els.fixture = $("product-plan-fixture");
      els.goal = $("product-plan-goal");
      els.sections = $("product-plan-sections");
      els.developerMode = $("product-plan-developer-mode");
      els.reviewCapsules = $("product-review-items");
      els.developerEvidence = $("product-plan-developer-evidence");
      els.warehouseReturn = $("btn-warehouse-return-product-plan");
    }

    function bind() {
      if (bound) return;
      cacheElements();
      if (!els.entry || !els.screen) return;
      bound = true;
      els.entry.addEventListener("click", enterScene);
      $("btn-product-plan-back").addEventListener("click", leaveScene);
      $("btn-submit-product-goal").addEventListener("click", submitGoal);
      els.goal.addEventListener("keydown", function (event) {
        if ((event.metaKey || event.ctrlKey) && event.key === "Enter") submitGoal();
      });
      els.sections.addEventListener("click", function (event) {
        var button = event.target.closest("[data-open-review]");
        if (button) openReview(button.dataset.openReview);
      });
      $("btn-product-review-back").addEventListener("click", closeReview);
      els.developerMode.addEventListener("change", function () {
        state.developerMode = els.developerMode.checked === true;
        render();
      });
      els.reviewCapsules.addEventListener("click", function (event) {
        var button = event.target.closest("[data-capsule-id]");
        if (button) openWarehouse(button.dataset.capsuleId);
      });
      els.warehouseReturn.addEventListener("click", returnFromWarehouse);
      document.addEventListener("keydown", function (event) {
        if (!state.active || state.warehousePending || event.key !== "Escape") return;
        event.preventDefault();
        if (state.view === "review") closeReview();
        else leaveScene();
      });
      render();
    }

    function sync() {
      if (state.active) render();
    }

    function getState() {
      return {
        active: state.active,
        scope: "prototype_only",
        fixture_id: FIXTURE_ID,
        prototype_id: state.fixtureVisible ? PROTOTYPE_ID : null,
        fixture_visible: state.fixtureVisible,
        view: state.view,
        section_id: state.sectionId || null,
        expanded: Object.assign({}, state.expanded),
        developer_mode: state.developerMode,
        warehouse_pending: state.warehousePending,
        goal_entered: !!state.goal,
      };
    }

    return { bind: bind, sync: sync, getState: getState, consumeWarehouseReturn: consumeWarehouseReturn };
  }

  window.ReweaveProductPlanScene = { create: create };
})();
