const state = {
  token: null,
  preview: false,
  dashboard: null,
  appInfo: null,
  telegramIdentity: null,
  isAuthenticated: false,
};

const els = {
  app: document.getElementById('app'),
  connectionBadge: document.getElementById('connectionBadge'),
  previewBanner: document.getElementById('previewBanner'),
  globalError: document.getElementById('globalError'),
  globalSuccess: document.getElementById('globalSuccess'),
  refreshButton: document.getElementById('refreshButton'),
  refreshCapitalButton: document.getElementById('refreshCapitalButton'),
  activateButton: document.getElementById('activateButton'),
  deactivateButton: document.getElementById('deactivateButton'),
  saveCredentialsButton: document.getElementById('saveCredentialsButton'),
  sendFeeReportButton: document.getElementById('sendFeeReportButton'),
  credentialsForm: document.getElementById('credentialsForm'),
  feeReportForm: document.getElementById('feeReportForm'),
  apiKeyInput: document.getElementById('apiKeyInput'),
  apiSecretInput: document.getElementById('apiSecretInput'),
  feeReportInput: document.getElementById('feeReportInput'),
  metricBotStatus: document.getElementById('metricBotStatus'),
  metricBotDetail: document.getElementById('metricBotDetail'),
  metricCapitalActivo: document.getElementById('metricCapitalActivo'),
  metricCapitalTotal: document.getElementById('metricCapitalTotal'),
  metricCapitalTotalCard: document.getElementById('metricCapitalTotalCard'),
  metricFeeDue: document.getElementById('metricFeeDue'),
  metricFeeStatus: document.getElementById('metricFeeStatus'),
  metricReferralsCount: document.getElementById('metricReferralsCount'),
  metricReferralCode: document.getElementById('metricReferralCode'),
  metricCredentials: document.getElementById('metricCredentials'),
  metricMaskedKey: document.getElementById('metricMaskedKey'),
  detailTradingStatus: document.getElementById('detailTradingStatus'),
  detailTradingPause: document.getElementById('detailTradingPause'),
  detailEngineError: document.getElementById('detailEngineError'),
  detailReferralDaily: document.getElementById('detailReferralDaily'),
  detailReferralTotal: document.getElementById('detailReferralTotal'),
  detailActivePosition: document.getElementById('detailActivePosition'),
  detailUpdatedAt: document.getElementById('detailUpdatedAt'),
  profileName: document.getElementById('profileName'),
  profileMeta: document.getElementById('profileMeta'),
  feeInvoiceBlock: document.getElementById('feeInvoiceBlock'),
  feeMessage: document.getElementById('feeMessage'),
  operationsPanel: document.getElementById('operationsPanel'),
  statesPanel: document.getElementById('statesPanel'),
  eventsPanel: document.getElementById('eventsPanel'),
  tabs: Array.from(document.querySelectorAll('.tab')),
  listEmptyTemplate: document.getElementById('listEmptyTemplate'),
};

function apiPrefix() {
  return state.appInfo?.api_prefix || '/api/v1';
}

function showNotice(type, message) {
  const success = els.globalSuccess;
  const error = els.globalError;
  success.classList.add('hidden');
  error.classList.add('hidden');
  if (!message) return;
  const target = type === 'success' ? success : error;
  target.textContent = message;
  target.classList.remove('hidden');
}

function clearNotice() {
  showNotice(null, '');
}

function setConnectionBadge(kind, text) {
  els.connectionBadge.className = 'badge';
  if (kind === 'success') {
    els.connectionBadge.classList.add('badge--success');
  } else if (kind === 'warning') {
    els.connectionBadge.classList.add('badge--warning');
  } else if (kind === 'danger') {
    els.connectionBadge.classList.add('badge--danger');
  } else {
    els.connectionBadge.classList.add('badge--neutral');
  }
  els.connectionBadge.textContent = text;
}

function formatMoney(value, asset = 'USDT') {
  const number = Number(value || 0);
  return `${number.toFixed(2)} ${asset}`;
}

function formatDate(value) {
  if (!value) return '--';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return new Intl.DateTimeFormat('es-ES', {
    dateStyle: 'short',
    timeStyle: 'short',
  }).format(date);
}

function textOrDash(value) {
  if (value === null || value === undefined || value === '') return '--';
  return String(value);
}

async function fetchJson(path, options = {}) {
  const headers = new Headers(options.headers || {});
  if (state.token) {
    headers.set('Authorization', `Bearer ${state.token}`);
  }
  if (!headers.has('Content-Type') && options.body) {
    headers.set('Content-Type', 'application/json');
  }

  const response = await fetch(path, { ...options, headers });
  let payload = null;
  const text = await response.text();
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      payload = { raw: text };
    }
  }
  if (!response.ok) {
    const detail = payload?.detail || payload?.raw || `HTTP ${response.status}`;
    throw new Error(detail);
  }
  return payload;
}

async function loadAppInfo() {
  state.appInfo = await fetchJson(`${apiPrefix()}/app-info`).catch(async () => {
    const payload = await fetch('/api/v1/app-info').then(async (response) => {
      const text = await response.text();
      return text ? JSON.parse(text) : null;
    });
    state.appInfo = payload;
    return payload;
  });
}

async function authenticateTelegram() {
  const tg = window.Telegram?.WebApp;
  if (!tg || !tg.initData) {
    state.preview = true;
    state.isAuthenticated = false;
    setConnectionBadge('warning', 'Vista previa');
    els.previewBanner.classList.remove('hidden');
    return false;
  }

  tg.ready();
  tg.expand();
  state.telegramIdentity = tg.initDataUnsafe?.user || null;

  const authPayload = await fetchJson(`${apiPrefix()}/auth/telegram`, {
    method: 'POST',
    body: JSON.stringify({ init_data: tg.initData }),
  });
  state.token = authPayload.access_token;
  state.isAuthenticated = true;
  sessionStorage.setItem('neotrade-miniapp-token', state.token);
  setConnectionBadge('success', 'Conectado');
  els.previewBanner.classList.add('hidden');
  return true;
}

async function restoreOrAuthenticate() {
  const cached = sessionStorage.getItem('neotrade-miniapp-token');
  if (cached) {
    state.token = cached;
    try {
      await fetchJson(`${apiPrefix()}/me`);
      state.isAuthenticated = true;
      setConnectionBadge('success', 'Sesión activa');
      return true;
    } catch {
      sessionStorage.removeItem('neotrade-miniapp-token');
      state.token = null;
    }
  }
  return authenticateTelegram();
}

function setButtonsDisabled(disabled) {
  [
    els.refreshButton,
    els.refreshCapitalButton,
    els.activateButton,
    els.deactivateButton,
    els.saveCredentialsButton,
    els.sendFeeReportButton,
    els.apiKeyInput,
    els.apiSecretInput,
    els.feeReportInput,
  ].forEach((element) => {
    element.disabled = disabled;
  });
}

function renderReadonlyPreview() {
  els.profileName.textContent = 'Vista previa';
  els.profileMeta.textContent = 'Abre la Mini App desde Telegram para autenticar la sesión y cargar datos reales.';
  els.metricBotStatus.textContent = 'Preview';
  els.metricBotDetail.textContent = 'Sin sesión Telegram';
  els.metricCapitalActivo.textContent = '--';
  els.metricCapitalTotal.textContent = 'Capital total --';
  els.metricCapitalTotalCard.textContent = '--';
  els.metricFeeDue.textContent = '--';
  els.metricFeeStatus.textContent = 'Sin autenticación';
  els.metricReferralsCount.textContent = '--';
  els.metricReferralCode.textContent = 'Código --';
  els.metricCredentials.textContent = 'Pendiente';
  els.metricMaskedKey.textContent = 'Abre desde Telegram';
  els.detailTradingStatus.textContent = 'No autenticado';
  els.detailTradingPause.textContent = '--';
  els.detailEngineError.textContent = '--';
  els.detailReferralDaily.textContent = '--';
  els.detailReferralTotal.textContent = '--';
  els.detailActivePosition.textContent = '--';
  els.detailUpdatedAt.textContent = '--';
  els.feeInvoiceBlock.textContent = 'Sin factura cargada en modo vista previa.';
  els.feeInvoiceBlock.classList.add('invoice-card--empty');
  els.feeMessage.textContent = 'Las instrucciones de fee aparecerán aquí cuando el usuario autenticado tenga una factura pendiente.';
  setButtonsDisabled(true);
  renderList(els.operationsPanel, []);
  renderList(els.statesPanel, []);
  renderList(els.eventsPanel, []);
}

function renderList(container, items, formatter) {
  container.innerHTML = '';
  if (!items || !items.length) {
    container.appendChild(els.listEmptyTemplate.content.cloneNode(true));
    return;
  }
  items.forEach((item) => {
    container.appendChild(formatter(item));
  });
}

function makeTimelineCard(title, subtitle, body, footerChips = []) {
  const card = document.createElement('article');
  card.className = 'timeline-card';
  card.innerHTML = `
    <div class="timeline-card__head">
      <strong>${title}</strong>
      <span class="timeline-card__meta">${subtitle}</span>
    </div>
    <div class="timeline-card__body">${body}</div>
    <div class="timeline-card__footer"></div>
  `;
  const footer = card.querySelector('.timeline-card__footer');
  footerChips.filter(Boolean).forEach((chip) => {
    const span = document.createElement('span');
    span.className = 'chip';
    span.textContent = chip;
    footer.appendChild(span);
  });
  if (!footer.children.length) {
    footer.remove();
  }
  return card;
}

function operationCard(item) {
  const symbol = textOrDash(item.symbol);
  const status = textOrDash(item.status);
  const side = textOrDash(item.side || item.direction);
  const amount = item.quantity || item.amount || item.quote_amount || '--';
  const body = `Orden ${textOrDash(item.order_number)} · ${side} · cantidad ${amount}`;
  return makeTimelineCard(
    `${symbol} · ${status}`,
    formatDate(item.updated_at || item.closed_at || item.created_at),
    body,
    [
      item.entry_price ? `Entrada ${item.entry_price}` : null,
      item.exit_price ? `Salida ${item.exit_price}` : null,
      item.pnl_quote !== undefined && item.pnl_quote !== null ? `PnL ${Number(item.pnl_quote).toFixed(2)}` : null,
    ],
  );
}

function tradeStateCard(item) {
  const payload = item.active_position || item.payload || {};
  const body = `Trade ${textOrDash(item.trade_id)} · ${textOrDash(item.status)} · ${textOrDash(payload.reason || item.reason || '')}`;
  return makeTimelineCard(
    `${textOrDash(item.symbol)} · ${textOrDash(item.status)}`,
    formatDate(item.updated_at || item.created_at),
    body,
    [
      item.entry_price ? `Entrada ${item.entry_price}` : null,
      item.stop_loss ? `SL ${item.stop_loss}` : null,
      item.take_profit ? `TP ${item.take_profit}` : null,
    ],
  );
}

function tradeEventCard(item) {
  const payload = item.payload || {};
  const payloadSummary = Object.keys(payload).slice(0, 4).map((key) => `${key}: ${payload[key]}`).join(' · ');
  return makeTimelineCard(
    `${textOrDash(item.type)} · ${textOrDash(item.trade_id)}`,
    formatDate(item.created_at),
    payloadSummary || 'Evento sin payload adicional.',
    [item.symbol ? `Símbolo ${item.symbol}` : null],
  );
}

function invoiceText(invoice) {
  if (!invoice) {
    return 'Sin factura pendiente.';
  }
  const lines = [
    `ID factura: ${textOrDash(invoice.invoice_id)}`,
    `Estado: ${textOrDash(invoice.status)}`,
    `Monto: ${formatMoney(invoice.amount_due || invoice.amount || 0, invoice.asset || 'USDT')}`,
    `Método: ${textOrDash(invoice.payment_method)}`,
  ];
  if (invoice.destination_uid) {
    lines.push(`UID destino: ${invoice.destination_uid}`);
  }
  if (invoice.notes) {
    lines.push(`Notas: ${invoice.notes}`);
  }
  return lines.join('\n');
}

function updateDashboardView(payload) {
  state.dashboard = payload;
  const user = payload.user || {};
  const referrals = payload.referrals || {};
  const invoice = payload.fee_invoice || null;
  const stats = user.stats || {};

  els.metricBotStatus.textContent = user.bot_activo ? 'Activo' : 'Inactivo';
  if (!user.bot_activo) {
    els.metricBotDetail.textContent = 'Sin ejecución activa';
  } else if (user.trading_enabled) {
    els.metricBotDetail.textContent = 'Operativa habilitada';
  } else {
    els.metricBotDetail.textContent = user.trading_pause_reason
      ? `Pausa: ${textOrDash(user.trading_pause_reason)}`
      : 'Operativa pausada';
  }
  els.metricCapitalActivo.textContent = formatMoney(user.capital_activo, user.payment_asset || 'USDT');
  els.metricCapitalTotal.textContent = `Capital total ${formatMoney(user.capital_total, user.payment_asset || 'USDT')}`;
  els.metricCapitalTotalCard.textContent = formatMoney(user.capital_total, user.payment_asset || 'USDT');
  els.metricFeeDue.textContent = formatMoney(user.fee_due_total, user.payment_asset || 'USDT');
  els.metricFeeStatus.textContent = `Estado fee: ${textOrDash(user.fee_status)}`;
  els.metricReferralsCount.textContent = textOrDash(referrals.referidos_activos);
  els.metricReferralCode.textContent = `Código ${textOrDash(referrals.codigo_referido)}`;
  els.metricCredentials.textContent = user.has_api_credentials ? 'Configuradas' : 'Pendientes';
  els.metricMaskedKey.textContent = user.api_key_masked || 'Clave no cargada';

  els.detailTradingStatus.textContent = user.trading_enabled ? 'Habilitado' : 'Pausado';
  els.detailTradingPause.textContent = textOrDash(user.trading_pause_reason || 'Sin bloqueo');
  els.detailEngineError.textContent = textOrDash(user.last_engine_error || 'Sin error reciente');
  els.detailReferralDaily.textContent = formatMoney(referrals.ganancia_diaria, user.payment_asset || 'USDT');
  els.detailReferralTotal.textContent = formatMoney(referrals.ganancia_acumulada, user.payment_asset || 'USDT');
  els.detailActivePosition.textContent = user.active_position ? 'Sí' : 'No';
  els.detailUpdatedAt.textContent = formatDate(user.updated_at);

  const profileName = user.nombre || state.telegramIdentity?.first_name || 'Usuario';
  const usernameText = state.telegramIdentity?.username ? `@${state.telegramIdentity.username}` : 'Cuenta Telegram autenticada';
  els.profileName.textContent = profileName;
  els.profileMeta.textContent = `${usernameText} · abiertas ${stats.opened || 0} · cerradas ${stats.closed || 0}`;

  els.feeInvoiceBlock.textContent = invoiceText(invoice);
  els.feeInvoiceBlock.classList.toggle('invoice-card--empty', !invoice);
  els.feeMessage.textContent = invoice
    ? 'Si ya realizaste el pago, envía aquí el detalle o referencia para revisión administrativa.'
    : 'Sin factura activa. Cuando el sistema genere una, aparecerá en este bloque.';

  renderList(els.operationsPanel, payload.recent_operations || [], operationCard);
  renderList(els.statesPanel, payload.recent_trade_states || [], tradeStateCard);
  renderList(els.eventsPanel, payload.recent_trade_events || [], tradeEventCard);

  els.activateButton.disabled = !user.has_api_credentials;
  els.deactivateButton.disabled = false;
  els.sendFeeReportButton.disabled = !invoice;
  els.feeReportInput.disabled = !invoice;

  if (user.bot_activo) {
    els.metricBotStatus.className = 'status-good';
  } else {
    els.metricBotStatus.className = '';
  }

  if (user.fee_due_total > 0) {
    els.metricFeeDue.className = 'status-warn';
  } else {
    els.metricFeeDue.className = '';
  }
}

async function loadDashboard({ refreshCapital = false } = {}) {
  if (!state.isAuthenticated) {
    renderReadonlyPreview();
    return;
  }
  clearNotice();
  setConnectionBadge('neutral', refreshCapital ? 'Actualizando capital' : 'Sincronizando');
  const query = new URLSearchParams({
    operations_limit: '10',
    events_limit: '10',
    refresh_capital: String(refreshCapital),
  });
  const payload = await fetchJson(`${apiPrefix()}/me/dashboard?${query.toString()}`);
  updateDashboardView(payload);
  setConnectionBadge('success', 'Conectado');
  els.app.classList.remove('shell--loading');
  setButtonsDisabled(false);
}

async function submitCredentials(event) {
  event.preventDefault();
  clearNotice();
  const apiKey = els.apiKeyInput.value.trim();
  const apiSecret = els.apiSecretInput.value.trim();
  if (!apiKey || !apiSecret) {
    showNotice('error', 'Debes introducir API Key y API Secret.');
    return;
  }
  els.saveCredentialsButton.disabled = true;
  try {
    await fetchJson(`${apiPrefix()}/me/credentials`, {
      method: 'POST',
      body: JSON.stringify({ api_key: apiKey, api_secret: apiSecret }),
    });
    els.apiSecretInput.value = '';
    showNotice('success', 'Credenciales validadas y guardadas correctamente.');
    await loadDashboard();
  } catch (error) {
    showNotice('error', error.message);
  } finally {
    els.saveCredentialsButton.disabled = false;
  }
}

async function activateBot() {
  clearNotice();
  els.activateButton.disabled = true;
  try {
    const payload = await fetchJson(`${apiPrefix()}/me/bot/activate`, { method: 'POST' });
    showNotice('success', payload.status === 'activated' ? 'Bot activado correctamente.' : `Estado: ${payload.status}`);
    await loadDashboard();
  } catch (error) {
    showNotice('error', error.message);
  } finally {
    els.activateButton.disabled = false;
  }
}

async function deactivateBot() {
  clearNotice();
  els.deactivateButton.disabled = true;
  try {
    await fetchJson(`${apiPrefix()}/me/bot/deactivate`, { method: 'POST' });
    showNotice('success', 'Bot desactivado correctamente.');
    await loadDashboard();
  } catch (error) {
    showNotice('error', error.message);
  } finally {
    els.deactivateButton.disabled = false;
  }
}

async function refreshCapital() {
  clearNotice();
  els.refreshCapitalButton.disabled = true;
  try {
    const payload = await fetchJson(`${apiPrefix()}/me/capital`);
    showNotice('success', payload.status === 'ok' ? 'Capital actualizado.' : `Estado capital: ${payload.status}`);
    await loadDashboard();
  } catch (error) {
    showNotice('error', error.message);
  } finally {
    els.refreshCapitalButton.disabled = false;
  }
}

async function sendFeeReport(event) {
  event.preventDefault();
  clearNotice();
  const reportText = els.feeReportInput.value.trim();
  if (!reportText) {
    showNotice('error', 'Debes introducir el detalle del pago o referencia.');
    return;
  }
  els.sendFeeReportButton.disabled = true;
  try {
    await fetchJson(`${apiPrefix()}/me/fee/report`, {
      method: 'POST',
      body: JSON.stringify({ report_text: reportText }),
    });
    els.feeReportInput.value = '';
    showNotice('success', 'Reporte de fee enviado correctamente.');
    await loadDashboard();
  } catch (error) {
    showNotice('error', error.message);
  } finally {
    els.sendFeeReportButton.disabled = false;
  }
}

function setupTabs() {
  const panels = {
    operations: els.operationsPanel,
    states: els.statesPanel,
    events: els.eventsPanel,
  };
  els.tabs.forEach((tab) => {
    tab.addEventListener('click', () => {
      els.tabs.forEach((button) => button.classList.remove('is-active'));
      Object.values(panels).forEach((panel) => panel.classList.add('hidden'));
      tab.classList.add('is-active');
      panels[tab.dataset.tab].classList.remove('hidden');
    });
  });
}

async function bootstrap() {
  setupTabs();
  setButtonsDisabled(true);
  try {
    await loadAppInfo();
    await restoreOrAuthenticate();
    if (state.isAuthenticated) {
      await loadDashboard();
    } else {
      renderReadonlyPreview();
    }
  } catch (error) {
    setConnectionBadge('danger', 'Error');
    showNotice('error', error.message || 'No se pudo inicializar la Mini App.');
    renderReadonlyPreview();
  } finally {
    els.app.classList.remove('shell--loading');
  }
}

els.credentialsForm.addEventListener('submit', submitCredentials);
els.feeReportForm.addEventListener('submit', sendFeeReport);
els.activateButton.addEventListener('click', activateBot);
els.deactivateButton.addEventListener('click', deactivateBot);
els.refreshCapitalButton.addEventListener('click', refreshCapital);
els.refreshButton.addEventListener('click', () => loadDashboard({ refreshCapital: false }).catch((error) => showNotice('error', error.message)));

bootstrap();
