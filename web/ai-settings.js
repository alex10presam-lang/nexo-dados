(() => {
  const form = byId("ai-form");
  const provider = byId("ai-provider");
  const model = byId("ai-model");
  const key = byId("ai-key");
  const status = byId("ai-status");
  const error = byId("ai-error");
  const clear = byId("ai-clear");
  const keyLinks = {
    openai: "https://platform.openai.com/api-keys",
    claude: "https://platform.claude.com/settings/keys",
    gemini: "https://aistudio.google.com/apikey",
    groq: "https://console.groq.com/keys",
    deepseek: "https://platform.deepseek.com/api_keys",
  };

  function showProvider() {
    const local = provider.value === "ollama";
    byId("ai-key-field").hidden = local;
    byId("ai-cloud-help").hidden = local;
    byId("ai-ollama-help").hidden = !local;
    key.required = !local;
    if (!local) byId("ai-key-link").href = keyLinks[provider.value];
    model.placeholder = local ? "Nome exibido em ollama list" : "Identificador no painel do provedor";
  }

  function showActive() {
    status.textContent = activeAI
      ? "Em uso nesta sessão: " + activeAI.model + "."
      : "Nenhum modelo selecionado nesta sessão. Se o servidor tiver uma configuração, ela será usada.";
  }

  provider.addEventListener("change", () => {
    key.value = "";
    model.value = "";
    error.hidden = true;
    showProvider();
  });
  clear.addEventListener("click", () => {
    activeAI = null;
    key.value = "";
    error.hidden = true;
    showActive();
  });
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const config = {provider: provider.value, model: model.value.trim(),
      key: provider.value === "ollama" ? "" : key.value.trim()};
    const controls = [...form.elements];
    controls.forEach((control) => { control.disabled = true; });
    error.hidden = true;
    status.textContent = "Testando conexão, ferramentas e resposta estruturada…";
    try {
      const check = await postJson("/api/ai/validate", {ai: config});
      activeAI = config;
      key.value = "";
      status.textContent = "Conexão validada. " + config.model + " está em uso nesta sessão. "
        + (check.tools ? "Chamada de ferramenta confirmada. " : "O modelo não confirmou a chamada de ferramenta. ")
        + (check.json ? "Resposta JSON confirmada." : "O modelo não confirmou a resposta JSON. ")
        + (check.warning ? " " + check.warning : "");
    } catch (problem) {
      showActive();
      error.textContent = problem instanceof TypeError
        ? "O painel não conseguiu acessar o servidor local. Tente novamente." : problem.message;
      error.hidden = false;
    } finally {
      controls.forEach((control) => { control.disabled = false; });
    }
  });
  showProvider();
  showActive();
})();
