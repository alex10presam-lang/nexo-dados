(() => {
  const file = byId("table-file");
  const sheet = byId("table-sheet");
  const operation = byId("table-op");
  const ready = byId("table-ready");
  const result = byId("table-result");
  const error = byId("table-error");
  const status = byId("table-status");
  const header = byId("table-header");
  const treatment = byId("treatment-op");
  const treatments = {
    number: "Padronizar números", date: "Converter datas", category: "Padronizar categorias",
    duplicates: "Remover linhas idênticas"
  };
  const names = {
    count: "Contagem de linhas", sum: "Soma", mean: "Média", median: "Mediana",
    min: "Mínimo", max: "Máximo", missing: "Valores ausentes", ratio: "Taxa (%)"
  };
  let dataset;
  let proposedRule;
  let latest;
  let pinned = [];
  let examplePlans = [];
  let busy = false;
  let qualityMonths = [];
  let qualityCompared = false;
  let exampleBoardBuilt = false;
  let tableColumns = [];
  let originalColumns = [];
  let pendingSecond;
  let pendingRecipe;
  let proposedScope = {};
  let restoredScope;
  let appliedScope = {};
  const planKeys = ["operation", "column", "group", "denominator", "filter_column", "filter_value", "monthly"];
  const scopeKeys = ["dashboard_column", "dashboard_value", "dashboard_month"];

  function currentScope() {
    return {dashboard_column: byId("board-column").value, dashboard_value: byId("board-value").value,
      dashboard_month: byId("board-month").value};
  }

  function clearPendingFiles() {
    pendingSecond = pendingRecipe = restoredScope = undefined;
    appliedScope = {};
    byId("board-column").value = "";
    byId("board-value").value = "";
    byId("board-month").value = "";
    for (const id of ["combine-file", "recipe-file"]) byId(id).value = "";
    for (const id of ["combine-status", "recipe-summary", "combine-map"]) byId(id).replaceChildren();
    for (const id of ["combine-apply", "combine-sheet-field", "recipe-apply"]) byId(id).hidden = true;
  }

  async function previewSecond() {
    const current = dataset;
    const second = pendingSecond;
    const message = byId("combine-status");
    const map = byId("combine-map");
    map.replaceChildren();
    byId("combine-apply").hidden = true;
    message.textContent = "Lendo o segundo arquivo…";
    try {
      const preview = await postJson("/api/table", {...second, action: "preview"});
      if (dataset !== current || pendingSecond !== second) return;
      const sheets = byId("combine-sheet");
      sheets.replaceChildren(new Option("Selecione uma aba", ""),
        ...preview.sheets.map((name) => new Option(name, name)));
      sheets.value = preview.sheet || "";
      byId("combine-sheet-field").hidden = !preview.sheets.length;
      if (preview.sheets.length && !preview.sheet) {
        message.textContent = "Escolha a aba do segundo arquivo.";
        return;
      }
      const other = preview.columns.map(({name}) => name);
      for (const [index, name] of originalColumns.entries()) {
        const wrapper = node("div", "");
        const label = node("label", name);
        const field = node("select", "");
        field.id = "combine-column-" + index;
        field.dataset.source = name;
        label.htmlFor = field.id;
        field.replaceChildren(new Option("Selecione a coluna correspondente", ""),
          ...other.map((column) => new Option(column, column)));
        field.value = other.includes(name) ? name : "";
        wrapper.append(label, field);
        map.append(wrapper);
      }
      message.textContent = preview.count + " linhas no segundo arquivo. Confira a correspondência abaixo.";
      byId("combine-apply").hidden = false;
    } catch (problem) {
      if (dataset === current && pendingSecond === second) message.textContent = problem.message;
    }
  }

  function downloadFile(filename, content, type) {
    const url = URL.createObjectURL(new Blob([content], {type}));
    const link = node("a", "");
    link.href = url;
    link.download = filename;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  async function readTableFile(selected, headerNumber) {
    const format = selected.name.split(".").pop().toLowerCase();
    if (!["csv", "xlsx"].includes(format) || selected.size > 1024 * 1024) {
      throw new Error("Selecione um CSV ou XLSX de até 1 MiB.");
    }
    const bytes = await selected.arrayBuffer();
    let content;
    if (format === "xlsx") {
      let binary = "";
      for (const byte of new Uint8Array(bytes)) binary += String.fromCharCode(byte);
      content = btoa(binary);
    } else {
      content = new TextDecoder("utf-8", {fatal: true}).decode(bytes);
    }
    return {format, content, name: selected.name, header: headerNumber, rules: []};
  }

  function openPlanEditor(plan) {
    const fields = byId("plan-fields");
    fields.replaceChildren();
    const captions = {operation: "Tipo de cálculo", column: "Coluna da métrica", group: "Agrupar por",
      denominator: "Denominador", filter_column: "Coluna do filtro", filter_value: "Valor do filtro",
      monthly: "Agrupar por mês"};
    for (const key of planKeys) {
      const id = "review-" + key;
      const label = node("label", captions[key]);
      label.htmlFor = id;
      const field = node(key === "filter_value" ? "input" : "select", "");
      field.id = id;
      if (key !== "filter_value") {
        const options = key === "operation" ? Object.entries(names)
          : key === "monthly" ? [["false", "Não"], ["true", "Sim"]]
          : [["", "Nenhuma"], ...tableColumns.map((name) => [name, name])];
        field.replaceChildren(...options.map(([value, name]) => new Option(name, value)));
      }
      field.value = key === "monthly" ? String(plan.monthly === true) : plan[key] ?? "";
      const wrapper = node("div", "");
      wrapper.append(label, field);
      fields.append(wrapper);
    }
    fields.oninput = () => { byId("plan-method").textContent = describe(readPlan()); };
    fields.oninput();
    byId("plan-scope").textContent = [
      proposedScope.dashboard_column ? proposedScope.dashboard_column + " = " + proposedScope.dashboard_value : "",
      proposedScope.dashboard_month,
    ].filter(Boolean).join(" · ") || "Toda a tabela";
    byId("review-plan").hidden = false;
  }

  function readPlan() {
    return Object.fromEntries(planKeys.map((key) => {
      const value = byId("review-" + key).value;
      return [key, key === "monthly" ? value === "true" : value];
    }));
  }
  const qualityBefore = byId("quality-before");
  const qualityAfter = byId("quality-after");
  const explain = byId("explain-quality");
  const qualityError = byId("quality-error");
  const guide = byId("guided-case");
  const guideNext = byId("guided-next");

  function updateGuide() {
    guide.hidden = !examplePlans.length;
    if (guide.hidden) return;
    const cleaned = dataset.rules.some((rule) => rule.operation === "duplicates");
    const steps = !cleaned
      ? ["1 de 3 · A tabela tem sete registros. Confira o impacto de uma inspeção repetida.", "Revisar linha repetida"]
      : !exampleBoardBuilt
        ? ["2 de 3 · Confira a taxa geral, o volume, a evolução mensal e o ranking.", "Montar painel de qualidade"]
        : ["3 de 3 · Compare agosto e setembro. Clique na linha A para ver os registros e a fórmula.", "Investigar linha A"];
    byId("guided-copy").textContent = steps[0];
    guideNext.textContent = steps[1];
  }

  function downloadEvidence(rows) {
    const csv = rows.map((row) => row.map((value) => {
      let cell = String(value ?? "");
      if (/^\s*[=+@-]/.test(cell) && !/^-\d+(\.\d+)?$/.test(cell)) cell = "'" + cell;
      return '"' + cell.replaceAll('"', '""') + '"';
    }).join(";")).join("\r\n");
    downloadFile("nexo-dados-evidencias.csv", "\ufeff" + csv, "text/csv;charset=utf-8");
  }

  function selectStep(step) {
    for (const button of document.querySelectorAll("[data-step]")) {
      button.setAttribute("aria-pressed", String(button.dataset.step === step));
    }
    for (const area of document.querySelectorAll("[data-area]")) area.hidden = area.dataset.area !== step;
  }

  function resetQualityResult() {
    qualityCompared = false;
    explain.hidden = true;
    qualityError.hidden = true;
    byId("quality-result").replaceChildren();
  }

  async function updateFilterValues() {
    const column = byId("board-column").value;
    const values = byId("board-values");
    values.replaceChildren();
    byId("board-value-field").hidden = !column;
    if (!column) return;
    const current = dataset;
    try {
      const response = await postJson("/api/table", { ...current, action: "filter-values", column });
      if (dataset === current && byId("board-column").value === column) {
        values.replaceChildren(...response.values.map((value) => new Option(value)));
      }
    } catch {
      // The exact-value input remains usable if suggestions fail.
    }
  }

  function renderTable(container, headers, rows) {
    const table = document.createElement("table");
    const head = table.createTHead().insertRow();
    for (const title of headers) {
      const cell = node("th", title);
      cell.scope = "col";
      head.append(cell);
    }
    const body = table.createTBody();
    for (const row of rows) {
      const line = body.insertRow();
      for (const value of row) line.insertCell().textContent = value ?? "—";
    }
    (typeof container === "string" ? byId(container) : container).replaceChildren(table);
  }

  function updateOperation() {
    byId("table-column").disabled = operation.value === "count";
    byId("table-column").labels[0].textContent = operation.value === "ratio"
      ? "Coluna do numerador" : "Coluna a calcular";
    byId("table-denominator-field").hidden = operation.value !== "ratio";
  }

  function describe(plan) {
    const formula = plan.operation === "ratio"
      ? "100 × soma(" + plan.column + ") ÷ soma(" + plan.denominator + ")"
      : names[plan.operation] + (plan.column && plan.operation !== "count" ? " de " + plan.column : "");
    return [
      formula, plan.group ? (plan.monthly ? "Mês de " : "Grupo: ") + plan.group : "",
      plan.filter_column ? "Filtro: " + plan.filter_column + " = " + plan.filter_value : ""
    ].filter(Boolean).join(" · ");
  }

  function evidenceTable(container, response) {
    renderTable(container, ["Grupo", "Valor", "Linhas", "Usadas", "Numerador", "Denominador"],
      response.results.map((row) => [row.group === "" ? "(vazio)" : row.group ?? "Total", row.value, row.rows,
        row.used ?? row.rows, row.numerator, row.denominator]));
  }

  function drawChart(container, rows, type, format, title, selectGroup) {
    container.replaceChildren();
    const points = rows.filter((row) => row.value !== null && Number.isFinite(Number(row.value)));
    if (!points.length) return;
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    const width = 440;
    const height = type === "line" ? 160 : points.length * 29 + 12;
    svg.setAttribute("viewBox", "0 0 " + width + " " + height);
    svg.setAttribute("role", "img");
    svg.setAttribute("aria-label", title);
    function draw(tag, attributes, label) {
      const item = document.createElementNS(svg.namespaceURI, tag);
      for (const [name, value] of Object.entries(attributes)) item.setAttribute(name, value);
      if (label !== undefined) item.textContent = label;
      svg.append(item);
      return item;
    }
    draw("rect", {width, height, fill: "#102a37", rx: 8});
    const values = points.map((row) => Number(row.value));
    const min = Math.min(0, ...values), max = Math.max(0, ...values);
    const span = max - min || 1;
    const ink = "#e7f4f7", accent = "#79f2c7";
    const label = (x, y, value, align = "start") => draw("text", {
      x, y, fill: ink, "text-anchor": align, "font-family": "sans-serif", "font-size": 11
    }, value);
    if (type === "line") {
      const xy = points.map((row, i) => [36 + i * (width - 72) / Math.max(1, points.length - 1),
        110 - (Number(row.value) - min) / span * 82]);
      draw("polyline", {points: xy.map((p) => p.join(",")).join(" "), fill: "none", stroke: accent, "stroke-width": 2});
      xy.forEach(([x, y], i) => {
        const point = draw("circle", {cx: x, cy: y, r: 6, fill: accent});
        point.addEventListener("click", () => selectGroup(points[i].group));
        label(x, y - 9, format(points[i].value), "middle");
        label(x, 142, (points[i].group || "Total").slice(0, 8), "middle");
      });
    } else {
      const x = (value) => 115 + (value - min) / span * 233;
      points.forEach((row, i) => {
        const y = i * 29 + 10;
        label(10, y + 11, (row.group || "Total").slice(0, 15));
        const bar = draw("rect", {x: Math.min(x(0), x(values[i])), y,
          width: Math.abs(x(values[i]) - x(0)), height: 12, fill: accent});
        bar.addEventListener("click", () => selectGroup(row.group));
        label(430, y + 11, format(row.value), "end");
      });
    }
    container.append(svg);
  }

  function renderBoard(response) {
    const cards = byId("board-cards");
    cards.replaceChildren();
    response.indicators.forEach((indicator, index) => {
      const card = node("article", "", "indicator");
      const summary = node("details", "");
      const evidence = node("div", "", "table-wrap");
      const remove = node("button", "Remover do painel", "secondary");
      remove.type = "button";
      remove.addEventListener("click", () => {
        pinned.splice(index, 1);
        refreshBoard();
      });
      card.append(node("h3", pinned[index].title));
      const ratio = indicator.plan.operation === "ratio";
      const item = pinned[index];
      const format = (value) => value === null ? "—" : new Intl.NumberFormat("pt-BR", {
        maximumFractionDigits: 3
      }).format(Number(value)) + (ratio ? "%" : "");
      if (!indicator.plan.group) {
        card.append(node("strong", format(indicator.results[0].value), "kpi-value"));
      } else {
        const bars = node("ul", "", "indicator-bars");
        const rows = indicator.results.slice(0, 8);
        const max = Math.max(...rows.map((row) => Math.abs(Number(row.value))), 0);
        for (const row of rows) {
          const entry = node("li", "");
          const bar = node("span", "", "indicator-bar");
          bar.setAttribute("aria-hidden", "true");
          bar.style.width = (max ? 100 * Math.abs(Number(row.value)) / max : 0) + "%";
          let label = node("span", row.group || "(vazio)");
          if (indicator.plan.group === "Linha" && !byId("quality-form").hidden && row.group) {
            label = node("button", row.group, "indicator-link");
            label.type = "button";
            label.setAttribute("aria-label", "Ver evidências da linha " + row.group);
            label.addEventListener("click", () => {
              selectStep("investigate");
              run("quality", row.group);
            });
          }
          entry.append(label, bar, node("strong", format(row.value)));
          bars.append(entry);
        }
        card.append(rows.length ? bars : node("p", "Nenhum grupo no recorte."));
        if (indicator.total_groups > 8) card.append(node("p", "Exibindo 8 de " + indicator.total_groups + " grupos.", "help"));
      }
      summary.append(node("summary", "Ver fórmula e registros"), node("p", describe(indicator.plan)), evidence);
      evidenceTable(evidence, indicator);
      const tools = node("div", "", "chart-tools");
      const goalLabel = node("label", "Meta máxima");
      const goal = node("input", "");
      goal.type = "number";
      goal.step = "any";
      goal.value = item.target ?? "";
      goalLabel.append(goal);
      const flags = node("p", "", "over-target");
      const markTarget = () => {
        item.target = goal.value;
        const above = goal.value === "" ? [] : indicator.results.filter((row) =>
          row.value !== null && Number(row.value) > goal.valueAsNumber);
        flags.textContent = above.length ? "Acima da meta: " + above.map((row) => row.group || "Total").join(", ") : "";
      };
      goal.addEventListener("input", markTarget);
      markTarget();
      tools.append(goalLabel);
      if (indicator.plan.group) {
        const chart = node("div", "");
        const typeLabel = node("label", "Gráfico");
        const type = node("select", "");
        type.setAttribute("aria-label", "Gráfico");
        type.replaceChildren(new Option("Barras", "bar"), new Option("Linha", "line"));
        type.value = item.chart || (indicator.plan.monthly ? "line" : "bar");
        typeLabel.append(type);
        const selectGroup = (group) => {
          if (group === null) return;
          if (indicator.plan.monthly) {
            if (indicator.plan.group !== "Data" || !group) return;
            byId("board-month").value = group;
          } else {
            byId("board-column").value = indicator.plan.group;
            byId("board-value").value = group;
            updateFilterValues();
          }
          refreshBoard();
        };
        const redraw = () => {
          item.chart = type.value;
          drawChart(chart, indicator.results.slice(0, 8), type.value, format, item.title, selectGroup);
        };
        type.addEventListener("change", redraw);
        redraw();
        const exportChart = node("button", "Exportar SVG", "secondary-action");
        exportChart.type = "button";
        exportChart.addEventListener("click", () => {
          if (chart.firstElementChild) downloadFile("nexo-grafico.svg",
            new XMLSerializer().serializeToString(chart.firstElementChild), "image/svg+xml");
        });
        const groupLabel = node("label", "Filtrar painel por grupo");
        const groups = node("select", "");
        groups.setAttribute("aria-label", "Filtrar painel por grupo");
        const filterRows = indicator.results.filter((row) => row.group !== null &&
          (!indicator.plan.monthly || indicator.plan.group === "Data"));
        groups.replaceChildren(new Option("Escolher grupo", ""),
          ...filterRows.map((row, index) => new Option(row.group || "(vazio)", String(index))));
        groups.addEventListener("change", () => {
          if (groups.value === "") return;
          selectGroup(filterRows[Number(groups.value)].group);
        });
        groupLabel.append(groups);
        tools.append(typeLabel, exportChart);
        if (filterRows.length) tools.append(groupLabel);
        card.append(chart);
      }
      card.append(flags, tools, summary, remove);
      cards.append(card);
    });
    byId("board-source").textContent += " · " + response.filtered_rows + " registros no recorte";
  }

  function refreshBoard() {
    byId("board-source").textContent = [dataset.name, dataset.sheet,
      dataset.rules.length + " correções aplicadas"].filter(Boolean).join(" · ");
    byId("board-cards").replaceChildren();
    byId("board-empty").hidden = Boolean(pinned.length);
    byId("board-filters").hidden = !pinned.length;
    byId("ask-scope").disabled = !pinned.length;
    if (!pinned.length) appliedScope = {};
    if (pinned.length) return run("dashboard");
  }

  async function run(action, customPlan, title) {
    if (busy) return;
    busy = true;
    const preview = action === "preview";
    const controls = [...byId("table-explorer").querySelectorAll("input,select,button")];
    const states = controls.map((control) => control.disabled);
    const request = { ...dataset, action };
    if (action === "calculate") {
      request.plan = customPlan || { operation: operation.value, column: byId("table-column").value,
        group: byId("table-group").value, denominator: byId("table-denominator").value };
    } else if (action === "treatment") {
      request.rule = { operation: treatment.value, column: byId("treatment-column").value };
      byId("treatment-preview").hidden = true;
    } else if (action === "plan") {
      request.question = byId("table-question").value;
      proposedScope = byId("ask-scope").checked ? {...appliedScope} : {};
      Object.assign(request, proposedScope);
      byId("review-plan").hidden = true;
    } else if (action === "calculate-scoped") {
      request.plan = customPlan;
      Object.assign(request, proposedScope);
    } else if (action === "dashboard") {
      request.plans = pinned.map((item) => item.plan);
      request.dashboard_column = byId("board-column").value;
      request.dashboard_value = byId("board-value").value;
      request.dashboard_month = byId("board-month").value;
      byId("board-source").textContent = [dataset.name, dataset.sheet,
        dataset.rules.length + " correções aplicadas"].filter(Boolean).join(" · ");
    } else if (action === "quality" || action === "quality-ai") {
      request.previous = byId("quality-before").value;
      request.current = byId("quality-after").value;
      if (action === "quality" && typeof customPlan === "string") request.line = customPlan;
      qualityError.hidden = true;
      if (action === "quality") resetQualityResult();
    }
    controls.forEach((control) => { control.disabled = true; });
    error.hidden = result.hidden = true;
    status.textContent = preview ? "Lendo a tabela…" : "Calculando…";
    if (preview) {
      ready.hidden = true;
      byId("review-plan").hidden = true;
      byId("treatment-preview").hidden = true;
      byId("suggestion-list").replaceChildren();
    }
    if (action === "suggest") byId("suggestion-list").replaceChildren();
    try {
      const response = await postJson("/api/table", request);
      if (preview) {
        dataset.sheet = response.sheet;
        sheet.replaceChildren(...response.sheets.map((name) => new Option(name, name)));
        byId("table-sheet-field").hidden = !response.sheets.length;
        if (response.sheets.length && !response.sheet) {
          sheet.prepend(new Option("Selecione uma aba", ""));
          sheet.value = "";
          status.textContent = "Escolha a aba com a tabela que você quer analisar.";
          return;
        }
        sheet.value = response.sheet ?? "";
        const columns = response.columns;
        const columnNames = columns.map(({name}) => name);
        tableColumns = columnNames;
        if (!dataset.second) originalColumns = columnNames;
        byId("combine-clear").hidden = !dataset.second;
        byId("workspace-source").textContent = [dataset.name, dataset.sheet,
          response.count + " registros", dataset.rules.length + " correções"].filter(Boolean).join(" · ");
        const salesColumns = ["order_id", "order_date", "category", "region", "quantity", "unit_price_cents"];
        const salesLink = byId("use-sales");
        let salesWarning = "";
        salesLink.hidden = true;
        useSalesCsv(null);
        if (!dataset.second && dataset.format === "csv" && dataset.header === 1 && !dataset.rules.length
            && salesColumns.join() === columnNames.join()) {
          try {
            const sales = await postJson("/api/csv-preview", {csv: dataset.content});
            if (sales.months.length >= 2) {
              useSalesCsv(dataset.content, dataset.name, sales);
              salesLink.hidden = false;
            }
          } catch (problem) {
            salesWarning = " Indicadores de vendas: " + problem.message;
          }
        }
        const quality = ["Data", "Linha", "Rejeitados", "Inspecionados"].every((name) => columnNames.includes(name));
        byId("quality-form").hidden = !quality || response.months.length < 2;
        byId("quality-plans").hidden = !examplePlans.length;
        byId("board-month-field").hidden = !response.months.length;
        const activeMonth = byId("board-month").value;
        byId("board-month").replaceChildren(new Option("Todos", ""),
          ...response.months.map((month) => new Option(month, month)));
        byId("board-month").value = response.months.includes(activeMonth) ? activeMonth : "";
        qualityMonths = response.months;
        qualityBefore.replaceChildren(...qualityMonths.slice(0, -1).map((month) => new Option(month, month)));
        qualityBefore.selectedIndex = qualityMonths.length - 2;
        laterMonths(qualityBefore, qualityAfter, qualityMonths, qualityMonths.at(-1));
        const headers = columns.map(({name, type, missing}) =>
          name + " · " + (type === "number" ? "número" : "texto") + " · " + missing + " vazios");
        renderTable("table-preview", headers, response.sample);
        const diagnostic = response.diagnosis;
        byId("diagnosis-summary").textContent = diagnostic.duplicates + " linhas idênticas além da primeira ocorrência.";
        renderTable("diagnosis-values", ["Coluna", "Vazios", "Números válidos", "Datas válidas", "Formatos de data", "Variações de categoria"],
          diagnostic.columns.map((c) => [c.name, c.missing, c.numeric_values, c.date_values, c.date_formats, c.category_variants]));
        byId("treatment-log").replaceChildren(...dataset.rules.map((rule) =>
          node("li", treatments[rule.operation] + (rule.operation === "duplicates" ? "" : " · " + rule.column))));
        byId("treatment-reset").hidden = !dataset.rules.length;
        for (const id of ["table-column", "table-group", "table-denominator", "treatment-column", "board-column"]) {
          const select = byId(id);
          const previousValue = select.value;
          select.replaceChildren(new Option(id === "table-group" || id === "board-column" ? "Nenhum" : "Selecione", ""),
            ...columns.map(({name}) => new Option(name, name)));
          select.value = columnNames.includes(previousValue) ? previousValue : "";
        }
        if (restoredScope) {
          byId("board-column").value = restoredScope.dashboard_column;
          byId("board-value").value = restoredScope.dashboard_value;
          byId("board-month").value = restoredScope.dashboard_month;
          if (byId("board-month").selectedIndex < 0) {
            byId("board-month").value = "";
            byId("recipe-summary").textContent += " O mês salvo não existe no novo arquivo.";
          }
          restoredScope = undefined;
        }
        resetQualityResult();
        updateFilterValues();
        ready.hidden = false;
        updateGuide();
        status.textContent = response.count + " linhas na tabela · até 5 na prévia." + salesWarning;
      } else if (action === "treatment") {
        proposedRule = request.rule;
        byId("treatment-summary").textContent = response.affected + " linhas afetadas. "
          + (response.invalid ? response.invalid + " valores não puderam ser convertidos e serão preservados." : "");
        renderTable("treatment-values", ["Antes", "Depois"], response.examples);
        byId("treatment-apply").hidden = !response.affected;
        byId("treatment-preview").hidden = false;
        status.textContent = "";
      } else if (action === "suggest") {
        for (const suggestion of response.suggestions) {
          const item = node("article", "", "suggestion");
          const button = node("button", "Calcular este indicador");
          button.type = "button";
          button.addEventListener("click", () => run("calculate", suggestion.plan, suggestion.title));
          item.append(node("h3", suggestion.title), node("p", suggestion.topic + " · " + describe(suggestion.plan)),
            node("p", suggestion.assumption, "help"), button);
          byId("suggestion-list").append(item);
        }
        status.textContent = "";
      } else if (action === "dashboard") {
        appliedScope = Object.fromEntries(scopeKeys.map((key) => [key, request[key]]));
        renderBoard(response);
        status.textContent = "";
      } else if (action === "plan" && response.plan) {
        openPlanEditor(response.plan);
        status.textContent = "";
      } else if (action === "quality" || action === "quality-ai") {
        const target = byId("quality-result");
        target.replaceChildren();
        const increase = response.changes.find((row) => Number(row.delta) > 0);
        target.append(node("p", increase
          ? "Maior aumento comparável na linha " + increase.line + " · +" + increase.delta + " p.p."
          : "Nenhum aumento entre as linhas com taxa calculável nos dois meses."));
        const evidence = node("div", "", "table-wrap");
        target.append(evidence);
        renderTable(evidence, ["Linha", "Anterior (%)", "Atual (%)", "Variação (p.p.)", "Rejeitados / inspecionados"],
          response.changes.map((row) => [row.line, row.previous.value, row.current.value, row.delta,
            row.previous.numerator + " / " + row.previous.denominator + " → "
            + row.current.numerator + " / " + row.current.denominator]));
        if (response.records) {
          const row = response.changes.find((item) => item.line === request.line);
          const records = node("div", "", "table-wrap");
          target.append(node("h3", "Registros da linha " + request.line),
            node("p", "Períodos " + request.previous + " e " + request.current + " · " + describe(response.plan)),
            node("p", row ? "Variação de " + row.delta + " pontos percentuais." : "Taxa indisponível para comparar os dois meses."), records);
          renderTable(records, response.columns, response.records);
          const download = node("button", "Exportar recorte e evidências");
          download.type = "button";
          download.addEventListener("click", () => downloadEvidence([
            ["Linha", "Mês anterior", "Mês atual", "Fórmula", "Variação (p.p.)", "Correções aplicadas"],
            [request.line, request.previous, request.current, describe(response.plan), row?.delta,
              dataset.rules.map((rule) => treatments[rule.operation]).join(", ")],
            ["Período", "Rejeitados", "Inspecionados", "Taxa (%)"],
            [request.previous, row?.previous.numerator, row?.previous.denominator, row?.previous.value],
            [request.current, row?.current.numerator, row?.current.denominator, row?.current.value],
            [], response.columns, ...response.records
          ]));
          target.append(download);
        }
        if (response.commentary) target.append(node("h3", "Interpretação da IA"), node("p", response.commentary));
        else target.append(node("p", "Verifique mudanças de lote, equipamento ou processo para investigar a causa.", "help"));
        qualityCompared = true;
        explain.hidden = action === "quality-ai";
        status.textContent = "";
      } else {
        const investigation = action === "plan" || action === "calculate-scoped";
        byId(investigation ? "investigation-result-slot" : "indicator-result-slot").append(result);
        byId("table-result-title").textContent = response.clarification ? "A IA precisa de mais detalhes"
          : investigation ? "Resultado do plano revisado" : "Resultado do cálculo";
        const plan = response.plan;
        latest = plan && !(action === "calculate-scoped" && Object.values(proposedScope).some(Boolean))
          ? {plan, title: title || describe(plan)} : null;
        byId("pin-indicator").hidden = !latest;
        byId("table-method").textContent = response.clarification || [
          describe(plan),
          response.total_groups > 100 ? "Exibindo 100 de " + response.total_groups + " grupos" : "",
          response.total_groups === 0 ? "Nenhum grupo encontrado" : ""
        ].filter(Boolean).join(" · ");
        byId("table-values").replaceChildren();
        if (plan) evidenceTable("table-values", response);
        result.hidden = false;
        status.textContent = "";
      }
    } catch (problem) {
      if (action === "dashboard") appliedScope = {};
      const target = action === "quality" || action === "quality-ai" ? qualityError : error;
      target.textContent = problem.message;
      target.hidden = false;
      status.textContent = "";
    } finally {
      controls.forEach((control, index) => { control.disabled = states[index]; });
      busy = false;
      updateOperation();
    }
    if (preview && !ready.hidden) await refreshBoard();
  }

  file.addEventListener("change", async () => {
    dataset = null;
    pinned = [];
    examplePlans = [];
    exampleBoardBuilt = false;
    useSalesCsv(null);
    selectStep("data");
    ready.hidden = result.hidden = error.hidden = byId("table-sheet-field").hidden = true;
    status.textContent = "";
    const selected = file.files[0];
    if (!selected) return;
    file.disabled = true;
    try {
      dataset = await readTableFile(selected, header.valueAsNumber);
      clearPendingFiles();
      await run("preview");
    } catch (problem) {
      error.textContent = problem instanceof TypeError ? "Salve o CSV em UTF-8." : problem.message;
      error.hidden = false;
    } finally {
      file.disabled = false;
    }
  });
  sheet.addEventListener("change", () => {
    pinned = [];
    delete dataset.second;
    delete dataset.mapping;
    clearPendingFiles();
    dataset.sheet = sheet.value;
    dataset.rules = [];
    run("preview");
  });
  header.addEventListener("change", () => {
    if (!dataset || !header.reportValidity()) return;
    dataset.header = header.valueAsNumber;
    delete dataset.second;
    delete dataset.mapping;
    clearPendingFiles();
    pinned = [];
    dataset.rules = [];
    run("preview");
  });
  byId("table-treatment").addEventListener("submit", (event) => {
    event.preventDefault();
    run("treatment");
  });
  for (const id of ["treatment-op", "treatment-column"]) {
    byId(id).addEventListener("change", () => {
      byId("treatment-column-field").hidden = treatment.value === "duplicates";
      byId("treatment-preview").hidden = true;
    });
  }
  byId("treatment-apply").addEventListener("click", () => {
    if (dataset.rules.length >= 20) {
      error.textContent = "Aplique até 20 correções por tabela.";
      error.hidden = false;
      return;
    }
    dataset.rules.push(proposedRule);
    run("preview");
  });
  byId("treatment-reset").addEventListener("click", () => {
    dataset.rules = [];
    run("preview");
  });
  byId("suggest-indicators").addEventListener("click", () => run("suggest"));
  byId("pin-indicator").addEventListener("click", () => {
    if (!latest || pinned.some((item) => JSON.stringify(item.plan) === JSON.stringify(latest.plan))) return;
    if (pinned.length >= 8) {
      error.textContent = "O painel comporta até oito indicadores.";
      error.hidden = false;
      return;
    }
    pinned.push(latest);
    selectStep("indicators");
    refreshBoard();
  });
  byId("board-filters").addEventListener("submit", (event) => {
    event.preventDefault();
    refreshBoard();
  });
  byId("quality-form").addEventListener("submit", (event) => {
    event.preventDefault();
    run("quality");
  });
  explain.addEventListener("click", () => {
    if (qualityCompared) run("quality-ai");
  });
  qualityBefore.addEventListener("change", () => {
    laterMonths(qualityBefore, qualityAfter, qualityMonths);
    resetQualityResult();
  });
  qualityAfter.addEventListener("change", resetQualityResult);
  byId("board-column").addEventListener("change", () => {
    byId("board-value").value = "";
    updateFilterValues();
  });
  for (const button of document.querySelectorAll("[data-step]")) {
    button.addEventListener("click", () => selectStep(button.dataset.step));
  }
  byId("use-sales").addEventListener("click", () => {
    mode.value = "csv";
    setMode();
  });
  byId("quality-plans").addEventListener("click", () => {
    if (pinned.length && !window.confirm("Usar os quatro indicadores do exemplo? Isso substitui os indicadores fixados.")) return;
    pinned = [...examplePlans];
    exampleBoardBuilt = true;
    byId("quality-plans").textContent = "Restaurar painel do exemplo";
    updateGuide();
    refreshBoard();
  });
  guideNext.addEventListener("click", () => {
    if (!dataset.rules.some((rule) => rule.operation === "duplicates")) {
      selectStep("prep");
      byId("table-treatment").closest("details").open = true;
      treatment.value = "duplicates";
      treatment.dispatchEvent(new Event("change"));
      run("treatment");
    } else if (!exampleBoardBuilt) {
      selectStep("indicators");
      byId("quality-plans").click();
    } else {
      selectStep("investigate");
      run("quality", "A");
    }
  });
  byId("quality-example").addEventListener("click", async () => {
    if (busy) return;
    busy = true;
    const button = byId("quality-example");
    button.disabled = file.disabled = header.disabled = sheet.disabled = true;
    try {
      const response = await fetch("/api/quality-example");
      if (!response.ok) throw new Error("Não foi possível abrir o exemplo.");
      const example = await response.json();
      dataset = {format: "csv", content: example.content, name: "Inspeções industriais · exemplo sintético", header: 1, rules: []};
      clearPendingFiles();
      pinned = [];
      examplePlans = example.plans;
      exampleBoardBuilt = false;
      byId("quality-plans").textContent = "Adicionar indicadores do exemplo";
      selectStep("data");
      file.value = "";
      header.value = "1";
    } catch (problem) {
      error.textContent = problem.message;
      error.hidden = false;
      return;
    } finally {
      busy = false;
      button.disabled = file.disabled = header.disabled = sheet.disabled = false;
    }
    run("preview");
  });
  operation.addEventListener("change", updateOperation);
  for (const [id, action] of [["table-manual", "calculate"], ["table-ask", "plan"]]) {
    byId(id).addEventListener("submit", (event) => {
      event.preventDefault();
      run(action);
    });
  }
  byId("review-plan").addEventListener("submit", (event) => {
    event.preventDefault();
    run("calculate-scoped", readPlan());
  });

  byId("combine-file").addEventListener("change", async (event) => {
    const selected = event.target.files[0];
    const current = dataset;
    pendingSecond = undefined;
    byId("combine-map").replaceChildren();
    byId("combine-apply").hidden = byId("combine-sheet-field").hidden = true;
    byId("combine-status").textContent = "";
    if (!selected) return;
    try {
      const second = await readTableFile(selected, byId("combine-header").valueAsNumber);
      if (dataset !== current || event.target.files[0] !== selected) return;
      pendingSecond = second;
      await previewSecond();
    } catch (problem) {
      byId("combine-status").textContent = problem.message;
    }
  });
  for (const id of ["combine-header", "combine-sheet"]) {
    byId(id).addEventListener("change", () => {
      if (!pendingSecond || !byId(id).reportValidity()) return;
      pendingSecond = {...pendingSecond, header: byId("combine-header").valueAsNumber,
        sheet: byId("combine-sheet").value};
      previewSecond();
    });
  }
  byId("combine-apply").addEventListener("click", async () => {
    if (busy || !pendingSecond) return;
    const mapping = Object.fromEntries([...byId("combine-map").querySelectorAll("select")]
      .map((field) => [field.dataset.source, field.value]));
    if (Object.values(mapping).includes("")) {
      byId("combine-status").textContent = "Selecione uma correspondência para cada coluna.";
      return;
    }
    const next = {...dataset, second: pendingSecond, mapping};
    await validateAndApply(next, pinned, currentScope(), byId("combine-status"));
  });
  byId("combine-clear").addEventListener("click", () => {
    const {second, mapping, ...original} = dataset;
    validateAndApply(original, pinned, currentScope(), byId("combine-status"));
  });

  async function validateAndApply(next, indicators, scope, message) {
    if (busy) return;
    busy = true;
    const controls = [...byId("table-explorer").querySelectorAll("input,select,button")];
    const states = controls.map((control) => control.disabled);
    controls.forEach((control) => { control.disabled = true; });
    try {
      const preview = await postJson("/api/table", {...next, action: "preview"});
      const selectedScope = {...scope};
      if (selectedScope.dashboard_column && !preview.columns.some(({name}) => name === selectedScope.dashboard_column)) {
        throw new Error("A coluna do filtro salvo está ausente: " + selectedScope.dashboard_column + ".");
      }
      if (selectedScope.dashboard_month && !preview.months.includes(selectedScope.dashboard_month)) {
        selectedScope.dashboard_month = "";
        message.textContent = "O mês salvo não existe neste arquivo. O painel usará todos os meses.";
      } else {
        message.textContent = "Configuração aplicada a " + preview.count + " linhas.";
      }
      if (indicators.length) await postJson("/api/table", {...next, ...selectedScope,
        action: "dashboard", plans: indicators.map((item) => item.plan)});
      dataset = next;
      pinned = indicators;
      restoredScope = selectedScope;
    } catch (problem) {
      message.textContent = problem.message;
      return;
    } finally {
      controls.forEach((control, index) => { control.disabled = states[index]; });
      busy = false;
    }
    await run("preview");
  }

  byId("recipe-save").addEventListener("click", () => {
    downloadFile("nexo-receita.json", JSON.stringify({version: 1, rules: dataset.rules, indicators: pinned,
      scope: appliedScope}, null, 2), "application/json");
  });
  byId("recipe-file").addEventListener("change", async (event) => {
    pendingRecipe = undefined;
    byId("recipe-apply").hidden = true;
    const selected = event.target.files[0];
    const summary = byId("recipe-summary");
    summary.textContent = "";
    if (!selected) return;
    try {
      if (selected.size > 65536) throw new Error("Selecione uma receita de até 64 KiB.");
      const recipe = JSON.parse(await selected.text());
      if (event.target.files[0] !== selected) return;
      if (recipe?.version !== 1 || !Array.isArray(recipe.rules) || recipe.rules.length > 20
          || !Array.isArray(recipe.indicators) || recipe.indicators.length > 8
          || recipe.indicators.some((item) => typeof item?.title !== "string" || !item.plan
            || typeof item.plan !== "object" || Array.isArray(item.plan))) {
        throw new Error("Receita inválida ou incompatível.");
      }
      const indicators = recipe.indicators.map((item) => ({
        title: item.title.slice(0, 160), plan: Object.fromEntries(planKeys.map((key) => [key, item.plan[key]])),
        chart: item.chart === "line" ? "line" : "bar", target: typeof item.target === "string" ? item.target : "",
      }));
      const scope = Object.fromEntries(scopeKeys.map((key) =>
        [key, typeof recipe.scope?.[key] === "string" ? recipe.scope[key] : ""]));
      pendingRecipe = {rules: recipe.rules, indicators, scope};
      summary.textContent = recipe.rules.length + " correções e " + indicators.length
        + " indicadores. Aplicar substitui as correções, os indicadores e os filtros atuais.";
      byId("recipe-apply").hidden = false;
    } catch (problem) {
      summary.textContent = problem instanceof SyntaxError ? "O arquivo não é uma receita JSON válida." : problem.message;
    }
  });
  byId("recipe-apply").addEventListener("click", () => {
    if (!pendingRecipe) return;
    validateAndApply({...dataset, rules: pendingRecipe.rules}, pendingRecipe.indicators,
      pendingRecipe.scope, byId("recipe-summary"));
  });
})();
