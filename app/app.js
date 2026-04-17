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
  pauseTradingButton: document.getElementById('pauseTradingButton'),
  resumeTradingButton: document.getElementById('resumeTradingButton'),
  activateButton: document.getElementById('activateButton'),
  deactivateButton: document.getElementById('deactivateButton'),
  saveCredentialsButton: document.getElementById('saveCredentialsButton'),
  sendFeeReportButton: document.getElementById('sendFeeReportButton'),
  credentialsForm: document.getElementById('credentialsForm'),
  feeReportForm: document.getElementById('feeReportForm'),
  apiKeyInput: document.getElementById('apiKeyInput'),
  apiSecretInput: document.getElementById('apiSecretInput'),
  feeReportInput: document.getElementById('feeReportInput'),
  copyReferralCodeButton: document.getElementById('copyReferralCodeButton'),
  copyFeeInvoiceButton: document.getElementById('copyFeeInvoiceButton'),
  referralPayoutForm: document.getElementById('referralPayoutForm'),
  coinwUidInput: document.getElementById('coinwUidInput'),
  saveCoinwUidButton: document.getElementById('saveCoinwUidButton'),
  requestReferralPayoutButton: document.getElementById('requestReferralPayoutButton'),
  referralPayoutHint: document.getElementById('referralPayoutHint'),
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
  detailReferralCount: document.getElementById('detailReferralCount'),
  detailReferralDaily: document.getElementById('detailReferralDaily'),
  detailReferralTotal: document.getElementById('detailReferralTotal'),
  detailReferralAvailable: document.getElementById('detailReferralAvailable'),
  detailReferralReserved: document.getElementById('detailReferralReserved'),
  detailReferralLink: document.getElementById('detailReferralLink'),
  detailReferralUid: document.getElementById('detailReferralUid'),
  detailReferralMinimum: document.getElementById('detailReferralMinimum'),
  detailReferralRequest: document.getElementById('detailReferralRequest'),
  detailActivePosition: document.getElementById('detailActivePosition'),
  detailUpdatedAt: document.getElementById('detailUpdatedAt'),
  detailTelegramId: document.getElementById('detailTelegramId'),
  detailPaymentMethod: document.getElementById('detailPaymentMethod'),
  detailFeeThreshold: document.getElementById('detailFeeThreshold'),
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

function friendlyPauseReason(value) {
  if (!value) return 'Sin bloqueo';
  if (value === 'fee_due') return 'Bloqueado por fee pendiente';
  if (value === 'manual_pause') return 'Pausa manual';
  return String(value);
}

function tradingStatusLabel(user) {
  if (!user?.bot_activo) return 'Bot detenido';
  if (user.trading_pause_reason === 'fee_due') return 'Bloqueado por fee';
  if (!user.trading_enabled && user.trading_pause_reason === 'manual_pause') return 'Pausa manual';
  if (!user.trading_enabled) return 'Pausado';
  return 'Habilitado';
}

function paymentMethodLabel(value) {
  if (!value) return '--';
  if (value === 'coinw_internal') return 'Transferencia interna CoinW';
  return String(value);
}

async function copyToClipboard(value) {
  if (!value) throw new Error('No hay información disponible para copiar.');
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(value);
    return;
  }
  const area = document.createElement('textarea');
  area.value = value;
  area.setAttribute('readonly', 'readonly');
  area.style.position = 'absolute';
  area.style.left = '-9999px';
  document.body.appendChild(area);
  area.select();
  document.execCommand('copy');
  document.body.removeChild(area);
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
    els.pauseTradingButton,
    els.resumeTradingButton,
    els.deactivateButton,
    els.saveCredentialsButton,
    els.sendFeeReportButton,
    els.apiKeyInput,
    els.apiSecretInput,
    els.feeReportInput,
    els.coinwUidInput,
    els.saveCoinwUidButton,
    els.requestReferralPayoutButton,
  ].forEach((element) => {
    element.disabled = disabled;
  });
}

function renderReadonlyPreview() {
  els.profileName.textContent = 'Vista previa';
  els.profileMeta.textContent = 'Abre la Mini App desde Telegram para autenticar la sesión y cargar datos reales.';
  els.metricBotStatus.textContent = 'Preview';
  els.metricBotDetail.textContent = 'Sin sesión Telegram';
  els.topbarBotStatus?.textContent && (els.topbarBotStatus.textContent = 'Preview');
  els.topbarBotDetail?.textContent && (els.topbarBotDetail.textContent = 'Sin sesión Telegram');
  els.metricCapitalActivo.textContent = '--';
  els.metricCapitalTotal.textContent = 'Capital total --';
  els.topbarCapitalActivo?.textContent && (els.topbarCapitalActivo.textContent = '--');
  els.topbarCapitalTotal?.textContent && (els.topbarCapitalTotal.textContent = 'Capital total --');
  els.metricCapitalTotalCard.textContent = '--';
  els.metricFeeDue.textContent = '--';
  els.metricFeeStatus.textContent = 'Sin autenticación';
  els.metricReferralsCount.textContent = '--';
  els.metricReferralCode.textContent = 'Enlace --';
  els.metricCredentials.textContent = 'Pendiente';
  els.metricMaskedKey.textContent = 'Abre desde Telegram';
  els.detailTradingStatus.textContent = 'No autenticado';
  els.detailTradingPause.textContent = '--';
  els.detailEngineError.textContent = '--';
  els.detailReferralCount.textContent = '--';
  els.detailReferralDaily.textContent = '--';
  els.detailReferralTotal.textContent = '--';
  els.detailReferralAvailable.textContent = '--';
  els.detailReferralReserved.textContent = '--';
  els.detailReferralLink.textContent = '--';
  els.detailReferralUid.textContent = '--';
  els.detailReferralMinimum.textContent = '--';
  els.detailReferralRequest.textContent = '--';
  els.referralPayoutHint.textContent = 'Abre la Mini App desde Telegram para gestionar tu UID y solicitar payouts.';
  els.detailActivePosition.textContent = '--';
  els.detailTelegramId.textContent = '--';
  els.detailPaymentMethod.textContent = '--';
  els.detailFeeThreshold.textContent = '--';
  els.detailUpdatedAt.textContent = '--';
  els.feeInvoiceBlock.textContent = 'Sin factura cargada en modo vista previa.';
  els.feeInvoiceBlock.classList.add('invoice-card--empty');
  els.feeMessage.textContent = 'Las instrucciones de fee aparecerán aquí cuando el usuario autenticado tenga una factura pendiente.';
  els.copyReferralCodeButton.disabled = true;
  els.copyFeeInvoiceButton.disabled = true;
  els.requestReferralPayoutButton.disabled = true;
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
  if (els.topbarBotStatus) els.topbarBotStatus.textContent = user.bot_activo ? 'Activo' : 'Inactivo';
  if (!user.bot_activo) {
    els.metricBotDetail.textContent = 'Sin ejecución activa';
    if (els.topbarBotDetail) els.topbarBotDetail.textContent = 'Sin ejecución activa';
  } else if (user.trading_enabled) {
    els.metricBotDetail.textContent = 'Operativa habilitada';
    if (els.topbarBotDetail) els.topbarBotDetail.textContent = 'Operativa habilitada';
  } else {
    els.metricBotDetail.textContent = user.trading_pause_reason
      ? friendlyPauseReason(user.trading_pause_reason)
      : 'Operativa pausada';
    if (els.topbarBotDetail) els.topbarBotDetail.textContent = els.metricBotDetail.textContent;
  }
  els.metricCapitalActivo.textContent = formatMoney(user.capital_activo, user.payment_asset || 'USDT');
  els.metricCapitalTotal.textContent = `Capital total ${formatMoney(user.capital_total, user.payment_asset || 'USDT')}`;
  if (els.topbarCapitalActivo) els.topbarCapitalActivo.textContent = formatMoney(user.capital_activo, user.payment_asset || 'USDT');
  if (els.topbarCapitalTotal) els.topbarCapitalTotal.textContent = `Capital total ${formatMoney(user.capital_total, user.payment_asset || 'USDT')}`;
  els.metricCapitalTotalCard.textContent = formatMoney(user.capital_total, user.payment_asset || 'USDT');
  els.metricFeeDue.textContent = formatMoney(user.fee_due_total, user.payment_asset || 'USDT');
  els.metricFeeStatus.textContent = `Estado fee: ${textOrDash(user.fee_status)}`;
  els.metricReferralsCount.textContent = textOrDash(referrals.referidos_activos);
  els.metricReferralCode.textContent = referrals.enlace_referido ? 'Enlace listo para compartir' : 'Enlace --';
  els.metricCredentials.textContent = user.has_api_credentials ? 'Configuradas' : 'Pendientes';
  els.metricMaskedKey.textContent = user.api_key_masked || 'Clave no cargada';

  els.detailTradingStatus.textContent = tradingStatusLabel(user);
  els.detailTradingPause.textContent = friendlyPauseReason(user.trading_pause_reason);
  els.detailEngineError.textContent = textOrDash(user.last_engine_error || 'Sin error reciente');
  els.detailReferralCount.textContent = textOrDash(referrals.referidos_totales);
  els.detailReferralDaily.textContent = formatMoney(referrals.ganancia_diaria, user.payment_asset || 'USDT');
  els.detailReferralTotal.textContent = formatMoney(referrals.ganancia_acumulada, user.payment_asset || 'USDT');
  els.detailReferralAvailable.textContent = formatMoney(referrals.saldo_disponible, user.payment_asset || 'USDT');
  els.detailReferralReserved.textContent = formatMoney(referrals.saldo_reservado, user.payment_asset || 'USDT');
  els.detailReferralLink.textContent = referrals.enlace_referido ? 'Listo para compartir' : 'No disponible';
  els.detailReferralUid.textContent = textOrDash(referrals.coinw_uid || '--');
  els.detailReferralMinimum.textContent = formatMoney(referrals.minimum_amount, user.payment_asset || 'USDT');
  els.detailReferralRequest.textContent = referrals.active_payout_request
    ? `${textOrDash(referrals.active_payout_request.status)} · ${formatMoney(referrals.active_payout_request.amount_requested, user.payment_asset || 'USDT')}`
    : 'Sin solicitud activa';
  els.referralPayoutHint.textContent = referrals.payout_request_reason || `Mínimo ${formatMoney(referrals.minimum_amount, user.payment_asset || 'USDT')} · cooldown ${referrals.cooldown_hours || 24}h`;
  els.coinwUidInput.value = referrals.coinw_uid || '';
  els.detailActivePosition.textContent = user.active_position ? 'Sí' : 'No';
  els.detailTelegramId.textContent = textOrDash(user.telegram_id);
  els.detailPaymentMethod.textContent = paymentMethodLabel(user.payment_method);
  els.detailFeeThreshold.textContent = formatMoney(user.fee_threshold, user.payment_asset || 'USDT');
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
  els.pauseTradingButton.disabled = !user.bot_activo || user.trading_pause_reason === 'fee_due' || (!user.trading_enabled && user.trading_pause_reason === 'manual_pause');
  els.resumeTradingButton.disabled = !user.bot_activo || user.trading_pause_reason === 'fee_due' || user.trading_enabled;
  els.copyReferralCodeButton.disabled = !referrals.enlace_referido;
  els.copyFeeInvoiceButton.disabled = !invoice;
  els.requestReferralPayoutButton.disabled = !referrals.can_request_payout;

  if (user.bot_activo) {
    els.metricBotStatus.className = 'status-good';
    if (els.topbarBotStatus) els.topbarBotStatus.className = 'status-good';
  } else {
    els.metricBotStatus.className = '';
    if (els.topbarBotStatus) els.topbarBotStatus.className = '';
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

async function pauseTrading() {
  clearNotice();
  els.pauseTradingButton.disabled = true;
  try {
    await fetchJson(`${apiPrefix()}/me/trading/pause`, { method: 'POST' });
    showNotice('success', 'Trading pausado manualmente. El manager seguirá gestionando posiciones abiertas.');
    await loadDashboard();
  } catch (error) {
    showNotice('error', error.message);
  } finally {
    els.pauseTradingButton.disabled = false;
  }
}

async function resumeTrading() {
  clearNotice();
  els.resumeTradingButton.disabled = true;
  try {
    await fetchJson(`${apiPrefix()}/me/trading/resume`, { method: 'POST' });
    showNotice('success', 'Trading reanudado correctamente.');
    await loadDashboard();
  } catch (error) {
    showNotice('error', error.message);
  } finally {
    els.resumeTradingButton.disabled = false;
  }
}

async function copyReferralLink() {
  clearNotice();
  try {
    const link = state.dashboard?.referrals?.enlace_referido;
    await copyToClipboard(link);
    showNotice('success', 'Enlace de referido copiado.');
  } catch (error) {
    showNotice('error', error.message);
  }
}

async function copyFeeInvoice() {
  clearNotice();
  try {
    const text = invoiceText(state.dashboard?.fee_invoice || null);
    if (!state.dashboard?.fee_invoice) {
      throw new Error('No hay factura activa para copiar.');
    }
    await copyToClipboard(text);
    showNotice('success', 'Factura copiada al portapapeles.');
  } catch (error) {
    showNotice('error', error.message);
  }
}

async function saveReferralCoinwUid(event) {
  event.preventDefault();
  clearNotice();
  const coinwUid = els.coinwUidInput.value.trim();
  if (!coinwUid) {
    showNotice('error', 'Debes introducir tu UID de CoinW.');
    return;
  }
  els.saveCoinwUidButton.disabled = true;
  try {
    await fetchJson(`${apiPrefix()}/me/referrals/coinw-uid`, {
      method: 'POST',
      body: JSON.stringify({ coinw_uid: coinwUid }),
    });
    showNotice('success', 'UID de CoinW guardado correctamente.');
    await loadDashboard();
  } catch (error) {
    showNotice('error', error.message);
  } finally {
    els.saveCoinwUidButton.disabled = false;
  }
}

async function requestReferralPayout() {
  clearNotice();
  els.requestReferralPayoutButton.disabled = true;
  try {
    const payload = await fetchJson(`${apiPrefix()}/me/referrals/payout-request`, { method: 'POST' });
    const amount = payload?.request?.amount_requested || payload?.request?.amount_reserved || 0;
    showNotice('success', `Solicitud de payout creada por ${formatMoney(amount)}.`);
    await loadDashboard();
  } catch (error) {
    showNotice('error', error.message);
  } finally {
    els.requestReferralPayoutButton.disabled = false;
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
els.referralPayoutForm.addEventListener('submit', saveReferralCoinwUid);
els.activateButton.addEventListener('click', activateBot);
els.pauseTradingButton.addEventListener('click', pauseTrading);
els.resumeTradingButton.addEventListener('click', resumeTrading);
els.deactivateButton.addEventListener('click', deactivateBot);
els.refreshCapitalButton.addEventListener('click', refreshCapital);
els.copyReferralCodeButton.addEventListener('click', copyReferralLink);
els.copyFeeInvoiceButton.addEventListener('click', copyFeeInvoice);
els.requestReferralPayoutButton.addEventListener('click', requestReferralPayout);
els.refreshButton.addEventListener('click', () => loadDashboard({ refreshCapital: false }).catch((error) => showNotice('error', error.message)));

bootstrap();
