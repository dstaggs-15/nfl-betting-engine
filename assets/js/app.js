import {$, node, pct, time, data, cell, theme, showError, empty, outcome} from './api.js';
import {playerSearch} from './player-search.js';
theme();
let selected = '', games = [], predictions = [], tickets = [], teams = {}, status = {}, lines = [], players = [];
const firstTD = p => p.line.market === 'first_touchdown';
const unknown = p => p.status === 'INSUFFICIENT_DATA';

function logo(abbr) {
  const el = node('img', '', 'team-logo');
  el.src = teams[abbr]?.logo || ''; el.alt = abbr; el.loading = 'lazy';
  el.addEventListener('error', () => el.replaceWith(node('span', abbr, 'badge')), {once: true});
  return el;
}
function renderGames() {
  const box = $('games'); box.replaceChildren();
  const query = $('search').value.trim().toLowerCase();
  const matching = games.filter(g => !query ||
    `${g.event_id} ${teams[g.home]?.name || g.home} ${teams[g.away]?.name || g.away}`.toLowerCase().includes(query) ||
    players.some(p => (p.team === g.home || p.team === g.away) && p.player_name.toLowerCase().includes(query)) ||
    lines.some(l => l.event_id === g.event_id && `${l.player_name} ${l.market}`.toLowerCase().includes(query)));
  if (!matching.length) empty(box, query ? 'No games match your search.' : 'No upcoming games in the current schedule window.');
  for (const game of matching) {
    const card = node('article', '', `game-card ${selected === game.event_id ? 'active' : ''}`);
    const meta = node('div', '', 'game-meta');
    meta.append(node('span', time(game.kickoff)), node('span', game.status.toUpperCase())); card.append(meta);
    for (const abbr of [game.away, game.home]) {
      const row = node('div', '', 'team-row'); row.append(logo(abbr), node('span', teams[abbr]?.name || abbr)); card.append(row);
    }
    const props = lines.filter(l => l.event_id === game.event_id);
    const latest = props.map(l => l.collected_at).sort().at(-1);
    card.append(node('p', props.length ? `${props.length} lines · updated ${time(latest)}` : 'No published lines'));
    if (!props.length) card.append(node('small', 'No supported provider lines collected for this game.', 'muted'));
    const button = node('button', 'View game');
    button.addEventListener('click', () => {
      selected = game.event_id; renderGames(); render(); $('selected-game').scrollIntoView({behavior: 'smooth', block: 'center'});
    });
    card.append(button); box.append(card);
  }
}
function visible(p) {
  const l = p.line, search = $('search').value.toLowerCase();
  return (!selected || l.event_id === selected) && ($('provider').value === 'all' || l.provider === $('provider').value) &&
    (!search || `${l.player_name} ${l.team} ${l.event_id} ${l.market}`.toLowerCase().includes(search)) &&
    (!$('fresh').checked || p.status !== 'STALE_LINE') &&
    (!$('exclude-player').value || l.player_name.toLowerCase() !== $('exclude-player').value.toLowerCase()) &&
    (!$('exclude-market').value || l.market !== $('exclude-market').value);
}
function controls() {
  const ranking = $('ranking').value;
  const valueAvailable = tickets.some(t => t.eligibility === 'verified' && t.expected_profit != null);
  const payoutAvailable = tickets.some(t => t.eligibility === 'verified' && t.multiplier != null);
  $('ranking').querySelector('[value="ev"]').disabled = !valueAvailable;
  $('ranking').querySelector('[value="payout"]').disabled = !payoutAvailable;
  for (const button of document.querySelectorAll('.quick-actions button')) {
    const active = button.dataset.legs ? button.dataset.legs === $('legs').value :
      button.dataset.scope ? button.dataset.scope === $('scope').value :
      button.dataset.ranking ? button.dataset.ranking === ranking : !selected;
    button.setAttribute('aria-pressed', String(active)); button.classList.toggle('active', active);
    if (button.dataset.ranking === 'ev') {
      button.disabled = !valueAvailable;
      button.title = valueAvailable ? 'Rank by verified expected return' : 'Value ranking requires verified full-ticket payouts.';
      button.textContent = valueAvailable ? 'Best value' : 'Best value unavailable';
    }
  }
  $('ranking-status').textContent = ranking === 'safest' ?
    'Safest: combinations sorted by joint hit probability; player lines sorted by outcome probability. First-touchdown markets are excluded from combinations until validated. High hit probability does not establish value.' :
    ranking === 'ev' ? 'Sorted by expected return using verified ticket payouts.' : 'Sorted by verified ticket payout.';
}
function render() {
  controls(); $('selected-game').textContent = selected || 'All games';
  const props = predictions.filter(visible);
  props.sort((a,b) => Number(unknown(a)) - Number(unknown(b)) || Number(firstTD(a)) - Number(firstTD(b)) ||
    ($('alternate').checked && a.line.player_id === b.line.player_id && a.line.market === b.line.market && a.line.direction === 'over' && b.line.direction === 'over' ? a.line.threshold - b.line.threshold : b.probability - a.probability));
  $('props').replaceChildren();
  for (const p of props.slice(0,100)) {
    const tr = node('tr'); cell(tr, p.line.player_name, `${p.line.team} · ${p.line.event_id}`);
    cell(tr, p.line.market.replaceAll('_',' '), outcome(p.line));
    cell(tr, p.line.provider, `${p.line.price_type === 'contract' ? 'Ask $' + p.line.price.toFixed(2) + ' · ' : ''}${time(p.line.collected_at)} · ${p.status}`);
    cell(tr, unknown(p) ? '—' : pct(p.probability), firstTD(p) ? 'Experimental estimate · excluded from combinations' : `Mean ${p.mean.toFixed(1)} / median ${p.median.toFixed(1)}`);
    cell(tr, `${pct(p.historical_hit_rate)} / ${pct(p.recent_hit_rate)}`, `n=${p.sample_size}`);
    cell(tr, pct(p.confidence), 'Data quality indicator · not hit probability');
    cell(tr, `Opponent ×${p.opponent_factor.toFixed(2)}`, p.risk_codes.join(' · ').replaceAll('_',' ').toLowerCase());
    $('props').append(tr);
  }
  $('line-count').textContent = `${props.length} lines${props.length > 100 ? ' · first 100 shown; search to narrow' : ''}`;
  $('board-empty').hidden = props.length > 0;
  $('board-empty').textContent = predictions.some(p => visible({...p,status:'WATCH'})) && $('fresh').checked ?
    'Matching lines are stale. Uncheck “Hide stale lines” to view them.' :
    $('search').value ? `No provider lines match “${$('search').value}” with the current filters.` : 'No published provider lines match the current filters.';
  const ids = new Set(props.filter(p => !firstTD(p) && !unknown(p) && p.probability >= .55 && p.confidence >= Number($('confidence').value)/100).map(p => p.prediction_id));
  const count = Number($('legs').value), same = $('scope').value === 'same', ranking = $('ranking').value;
  let candidates = tickets.filter(t => t.legs.length === count && t.same_game === same && t.joint_probability >= Number($('joint').value)/100 &&
    t.legs.every(id => ids.has(id)) && (Number($('payout').value) === 0 || t.multiplier != null && t.multiplier >= Number($('payout').value)));
  if (ranking === 'ev') candidates = candidates.filter(t => t.eligibility === 'verified' && t.expected_profit != null).sort((a,b) => b.expected_profit-a.expected_profit);
  else if (ranking === 'payout') candidates = candidates.filter(t => t.eligibility === 'verified' && t.multiplier != null).sort((a,b) => b.multiplier-a.multiplier);
  else candidates.sort((a,b) => b.joint_probability-a.joint_probability);
  const box = $('tickets'); box.replaceChildren();
  if (!candidates.length) empty(box, `No saved ${count}-leg combinations match these filters. ${!ids.size && props.length ? 'No eligible lines remain after data-quality and market checks.' : 'Try another game or adjust the filters.'}`);
  for (const t of candidates.slice(0,6)) {
    const card = node('article','','ticket'), head = node('div','','ticket-heading');
    head.append(node('h3',`${t.provider} · ${count} legs`),node('span',t.eligibility === 'verified' ? 'Eligible' : 'Theoretical','badge warn'));
    card.append(head,node('div',pct(t.joint_probability),'probability'),node('p',`Joint estimate ±${pct(t.uncertainty)} sampling error · independent estimate ${pct(t.naive_probability)}`));
    const list = node('ul');
    for (const id of t.legs) {
      const p = predictions.find(p => p.prediction_id === id);
      list.append(node('li', `${p.line.player_name} · ${p.line.market.replaceAll('_',' ')} · ${outcome(p.line)} — ${pct(p.probability)}${id === t.weakest_leg ? ' · weakest leg' : ''}`));
    }
    card.append(list,node('p', `Available multiplier: ${t.multiplier ?? 'unverified'} · break-even ${pct(t.break_even)} · EV/$1 ${t.expected_profit?.toFixed(2) ?? 'unavailable'}`),node('p',t.correlation_notes));
    box.append(card);
  }
}
try {
  [status,teams,games,predictions,tickets,lines,players] = await Promise.all([...['status','teams','schedule','current_predictions','current_parlays','current_lines'].map(data),data('players').catch(() => [])]);
  if (!players.length) players = [...new Map(lines.map(l => [l.player_id,{player_id:l.player_id,player_name:l.player_name,team:l.team,line_count:lines.filter(x => x.player_id === l.player_id).length}])).values()];
  playerSearch($('search'),$('player-suggestions'),players,() => {selected = '';renderGames();render();});
  for (const p of predictions) if (Date.now()-Date.parse(p.line.collected_at) > 1800000 || !p.line.available) p.status = 'STALE_LINE';
  for (const p of Object.values(status.providers)) if (p.last_success && Date.now()-Date.parse(p.last_success) > 1800000) p.status = 'STALE';
  $('week').textContent = status.current_week ? `WEEK ${status.current_week}` : 'NFL';
  $('refresh').textContent = `Refreshed ${time(status.generated_at)}`;
  $('model').textContent = `${status.model_version} · ${status.model_status}`;
  for (const [name,p] of Object.entries(status.providers)) {
    const el = node('div','','provider'); el.append(node('span','',`dot ${p.status}`));
    const description = node('div'); description.append(node('strong',`${name.toUpperCase()} · ${p.status}`),node('p',p.message),node('p',`Last collection: ${time(p.last_success)}`));
    el.append(description); $('providers').append(el);
  }
  for (const market of [...new Set(predictions.map(p => p.line.market))].sort()) {
    const option = node('option',market.replaceAll('_',' '));option.value = market;$('exclude-market').append(option);
  }
  renderGames();render();
} catch(e) {showError(e);}
for (const input of document.querySelectorAll('.controls input,.controls select')) input.addEventListener('input',render);
$('search').addEventListener('input',() => {renderGames();render();});
for (const button of document.querySelectorAll('.quick-actions button')) button.addEventListener('click',() => {
  if (button.dataset.legs) { $('legs').value = button.dataset.legs; $('ranking').value = 'safest'; }
  if (button.dataset.scope) $('scope').value = button.dataset.scope;
  if (button.dataset.ranking) $('ranking').value = button.dataset.ranking;
  if (button.id === 'clear-game') {selected = '';renderGames();}
  render();$('ranking-status').scrollIntoView({behavior:'smooth',block:'center'});
});
