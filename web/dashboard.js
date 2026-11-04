const byId = (id) => document.getElementById(id);
const themeToggle = byId("theme-toggle");
const systemTheme = matchMedia("(prefers-color-scheme: dark)");
function updateThemeButton() {
  const dark = (document.documentElement.dataset.theme || (systemTheme.matches ? "dark" : "light")) === "dark";
  themeToggle.dataset.current = dark ? "dark" : "light";
  byId("theme-label").textContent = dark ? "Modo claro" : "Modo escuro";
}
updateThemeButton();
systemTheme.addEventListener("change", updateThemeButton);
themeToggle.addEventListener("click", () => {
  const theme = themeToggle.dataset.current === "dark" ? "light" : "dark";
  document.documentElement.dataset.theme = theme;
  updateThemeButton();
  try {
    localStorage.setItem("nexo-theme", theme);
  } catch {
    // The selected theme still works while this page is open.
  }
});

function markCurrentArea() {
  const target = document.getElementById(location.hash.slice(1));
  const area = target?.closest("#sales, #ai-settings")?.id || "workspace";
  for (const link of document.querySelectorAll(".masthead nav a")) {
    if (link.hash === "#" + area) link.setAttribute("aria-current", "location");
    else link.removeAttribute("aria-current");
  }
}

window.addEventListener("hashchange", markCurrentArea);
markCurrentArea();
document.querySelector(".skip-link").addEventListener("click", (event) => {
  event.preventDefault();
  byId("workspace").focus();
});

const form = byId("investigation");
const mode = byId("mode");
const example = byId("example");
const question = byId("question");
const run = byId("run");
const money = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" });
const percent = new Intl.NumberFormat("pt-BR", { style: "percent", maximumFractionDigits: 2 });
const labels = {
  mes: "Mês", pedidos: "Pedidos", grupo: "Grupo", receita_centavos: "Receita",
  ticket_centavos: "Ticket médio", anterior_centavos: "Anterior",
  atual_centavos: "Atual", variacao_centavos: "Variação"
};
const toolNames = { compare: "Comparação mensal", category: "Por categoria", region: "Por região" };
let cases = [];
const previousMonth = byId("csv-previous");
const currentMonth = byId("csv-current");
let validatedCsv = null;
let salesMonths = [];

function laterMonths(previous, current, months, selected = current.value) {
  const eligible = months.filter((month) => month > previous.value);
  current.replaceChildren(...eligible.map((month) => new Option(month, month)));
  current.value = eligible.includes(selected) ? selected : eligible.at(-1) || "";
}

function node(tag, text, className) {
  const element = document.createElement(tag);
  element.textContent = text;
  if (className) element.className = className;
  return element;
}

function setMode() {
  const live = mode.value === "live";
  const csv = mode.value === "csv";
  byId("live-field").hidden = !live;
  byId("demo-field").hidden = mode.value !== "demo";
  byId("csv-field").hidden = !csv;
  question.required = live;
  run.textContent = live ? "Perguntar à IA" : csv ? "Comparar vendas dos dois meses" : "Ver resultado do cenário";
  run.disabled = csv ? !validatedCsv : !live && !cases.length;
  byId("mode-help").textContent = live
    ? "Use o modelo ativado em Configuração de IA para analisar as vendas de exemplo."
    : csv ? "Compare dois meses do seu arquivo com cálculos locais."
    : "Respostas gravadas com consultas executadas sobre a base local.";
  byId("error").hidden = true;
}

async function postJson(path, payload) {
  const usesAI = (path === "/api/investigate" && payload.mode === "live")
    || (path === "/api/table" && ["ask", "plan", "suggest", "quality-ai"].includes(payload.action));
  if (usesAI && activeAI) payload = { ...payload, ai: activeAI };
  const response = await fetch(path, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload)
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error);
  return data;
}

let activeAI = null;

function useSalesCsv(csv, filename, preview) {
  if (mode.value === "csv") byId("result").hidden = true;
  validatedCsv = null;
  byId("csv-preview").hidden = true;
  if (preview) {
    validatedCsv = csv;
    salesMonths = preview.months;
    previousMonth.replaceChildren(...salesMonths.slice(0, -1).map((month) => new Option(month, month)));
    previousMonth.selectedIndex = salesMonths.length - 2;
    laterMonths(previousMonth, currentMonth, salesMonths, salesMonths.at(-1));
    byId("sales-source").textContent = filename;
    byId("csv-summary").textContent = preview.count + " itens válidos · " + salesMonths.length + " meses";
    byId("csv-preview").hidden = false;
  }
  mode.querySelector('[value="csv"]').disabled = !validatedCsv;
  if (!validatedCsv && mode.value === "csv") mode.value = "demo";
  setMode();
}

function addKpis(report) {
  const cards = byId("kpis");
  cards.replaceChildren();
  if (!report || report.rows.length !== 2) return;
  const [previous, current] = report.rows;
  for (const key of ["receita_centavos", "pedidos", "ticket_centavos"]) {
    const format = key === "pedidos" ? (value) => String(value) : (value) => money.format(value / 100);
    const card = node("article", "", "panel");
    card.append(node("div", labels[key]), node("strong", format(current[key]), "kpi-value"));
    card.append(node("small", "Anterior: " + format(previous[key]), "help"));
    if (key === "receita_centavos") {
      const delta = current[key] - previous[key];
      const rate = previous[key] ? " · " + percent.format(delta / previous[key]) : "";
      card.append(node("div", "Variação: " + format(delta) + rate, "help"));
    }
    cards.append(card);
  }
}

function addEvidence(report) {
  const details = document.createElement("details");
  details.id = "evidence-" + report.tool;
  const { previous, current } = report.params;
  details.append(node("summary", toolNames[report.tool] + " · " + previous + " → " + current));
  if (report.missing.length) {
    details.append(node("p", "Sem dados em " + report.missing.join(", ") + "."));
  } else {
    const wrap = node("div", "", "table-wrap");
    const table = document.createElement("table");
    table.setAttribute("aria-label", toolNames[report.tool]);
    const keys = Object.keys(report.rows[0]);
    const heading = table.createTHead().insertRow();
    for (const key of keys) {
      const cell = node("th", labels[key]);
      cell.scope = "col";
      heading.append(cell);
    }
    const body = table.createTBody();
    for (const row of report.rows) {
      const line = body.insertRow();
      for (const key of keys) {
        line.insertCell().textContent = key.endsWith("_centavos") ? money.format(row[key] / 100) : row[key];
      }
    }
    wrap.append(table);
    details.append(wrap);
  }
  details.append(node("h3", "SQL e parâmetros"), node("pre", report.sql),
    node("pre", JSON.stringify(report.params, null, 2)));
  byId("evidence").append(details);
}

function showContributions(report) {
  const container = byId("contributions");
  container.replaceChildren();
  if (!report) return;
  const category = report.tool === "category";
  const title = category ? "Contribuição por categoria" : "Contribuição por região";
  const chart = node("section", "", "panel contribution-chart");
  const values = report.rows.map((row) => Math.abs(row.variacao_centavos));
  const max = Math.max(1, ...values);
  chart.append(node("h2", title), node("p", "Variação da receita em reais · queda à esquerda, alta à direita", "help"));
  const list = node("ul", "", "contribution-list");
  for (const row of report.rows) {
    const delta = row.variacao_centavos;
    const entry = node("li", "", "contribution-row");
    const track = node("div", "", "contribution-track");
    const bar = node("span", "", delta < 0 ? "bar decrease" : "bar increase");
    bar.style.width = (50 * Math.abs(delta) / max) + "%";
    track.setAttribute("aria-hidden", "true");
    track.append(bar);
    entry.append(node("span", row.grupo), track,
      node("strong", (delta > 0 ? "+" : "") + money.format(delta / 100)));
    list.append(entry);
  }
  const evidence = node("a", "Conferir tabela e SQL");
  evidence.href = "#evidence-" + report.tool;
  evidence.addEventListener("click", () => {
    byId("evidence-" + report.tool).open = true;
  });
  chart.append(list, evidence);
  container.append(chart);
}

async function submit(event) {
  event?.preventDefault();
  const payload = { mode: mode.value };
  if (payload.mode === "demo") payload.example = Number(example.value);
  else if (payload.mode === "csv") {
    if (!validatedCsv) return;
    Object.assign(payload, { csv: validatedCsv, previous: previousMonth.value, current: currentMonth.value });
  }
  else payload.question = question.value;
  run.disabled = mode.disabled = example.disabled = question.disabled = true;
  previousMonth.disabled = currentMonth.disabled = true;
  byId("error").hidden = byId("result").hidden = true;
  byId("status").textContent = "Investigando…";
  try {
    const result = await postJson("/api/investigate", payload);
    byId("source").textContent = result.needs_clarification ? "Período a esclarecer"
      : result.mode === "demo" ? "Resposta gravada" : result.mode === "csv" ? "CSV local" : "Gerado pela IA";
    byId("asked").textContent = result.mode === "demo" ? cases[payload.example].question : payload.question || "";
    byId("answer").textContent = result.answer;
    addKpis(result.evidence.find((item) => item.tool === "compare"));
    byId("evidence").replaceChildren();
    result.evidence.forEach(addEvidence);
    byId("evidence-section").hidden = result.evidence.length === 0;
    const breakdowns = result.evidence.filter((item) => item.tool !== "compare" && item.rows.length);
    showContributions(breakdowns.find((item) => item.tool === "category") || breakdowns[0]);
    byId("result").hidden = false;
    byId("status").textContent = result.needs_clarification
      ? "Inclua os meses na pergunta e envie novamente." : "Investigação concluída.";
  } catch (error) {
    byId("status").textContent = "";
    byId("error").textContent = error instanceof TypeError
      ? "Falha de conexão com o servidor local. Tente novamente." : error.message;
    byId("error").hidden = false;
  } finally {
    run.disabled = mode.disabled = example.disabled = question.disabled = false;
    previousMonth.disabled = currentMonth.disabled = false;
  }
}

mode.addEventListener("change", () => {
  byId("result").hidden = true;
  byId("status").textContent = "";
  setMode();
});
previousMonth.addEventListener("change", () => {
  laterMonths(previousMonth, currentMonth, salesMonths);
  byId("result").hidden = true;
});
currentMonth.addEventListener("change", () => { byId("result").hidden = true; });
form.addEventListener("submit", submit);
async function loadExamples() {
  run.disabled = mode.disabled = true;
  try {
    const response = await fetch("/api/examples");
    if (!response.ok) throw new Error();
    cases = await response.json();
    cases.forEach((item, index) => example.add(new Option(item.title, index)));
  } catch {
    byId("error").textContent = "Falha ao carregar os exemplos. Recarregue a página.";
    byId("error").hidden = false;
    mode.disabled = false;
    return;
  }
  mode.disabled = false;
  setMode();
  await submit();
}
loadExamples();
